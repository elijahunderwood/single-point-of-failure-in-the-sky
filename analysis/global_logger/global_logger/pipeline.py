"""pipeline.py - one station, one UTC day:
download -> read RINEX -> satellite elevations -> phase TEC -> ROT -> ROTI -> SQLite."""
import os, logging, datetime as dt
import numpy as np, pandas as pd
from . import archives, rinex, roti as R

log = logging.getLogger("global_logger")

def band_of(mlat):
    a = abs(mlat)
    return ("polar cap" if a >= 75 else "auroral" if a >= 62 else "sub-auroral" if a >= 52
            else "mid-latitude" if a >= 30 else "low-latitude" if a >= 15 else "equatorial")

def iso(sec):
    return pd.to_datetime(sec, unit="s", utc=True).strftime("%Y-%m-%dT%H:%M:%S+00:00")

def process_station_day(conn, station, day, cfg, force=False):
    day_s = day.isoformat()
    row = conn.execute("select status from station_days where station=? and day=?", (station, day_s)).fetchone()
    if row and row[0] in ("ok", "no_data") and not force:
        log.info("%s %s already %s - skipping (resume)", station, day_s, row[0]); return row[0]
    p = cfg["processing"]; raw_dir = os.path.join(cfg["paths"]["raw"], day.strftime("%Y/%j"))
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    def mark(status, **kw):
        conn.execute("insert or replace into station_days values(?,?,?,?,?,?,?,?,?)",
                     (station, day_s, status, kw.get("file"), kw.get("n_obs"), kw.get("n_windows"),
                      kw.get("rej"), kw.get("msg"), now)); conn.commit()
    try:
        path = archives.download_obs(station, day, raw_dir)
        if path is None:
            log.warning("%s %s: no daily 30-s file in archive", station, day_s); mark("no_data", msg="not in archive"); return "no_data"
        nav = archives.download_nav(day, os.path.join(cfg["paths"]["raw"], "nav"))
        text = rinex.open_obs(path)
        obs, info = rinex.read_obs(text); del text
        if obs.empty or info["xyz"] is None: raise ValueError("no GPS L1/L2 observations or no position")
        lat, lon, h = rinex.ecef_to_geodetic(info["xyz"]); mlat = rinex.geomag_lat(lat, lon)
        conn.execute("insert or replace into stations values(?,?,?,?,?,?,?,?,?,?,?)",
                     (station, cfg["_names"].get(station, ""), lat, lon, h, mlat, band_of(mlat),
                      info["receiver"], info["antenna"], info["interval"], "Geoscience Australia GNSS Data Repository"))
        eph = rinex.read_nav2(nav)
        obs = obs[obs.tsec.between(pd.Timestamp(day, tz="UTC").value/1e9, pd.Timestamp(day, tz="UTC").value/1e9 + 86400 - 1)]
        obs = obs.reset_index(drop=True)
        obs["elev_deg"] = rinex.add_elevations(obs, info["xyz"], eph)
        obs["phase_tec"] = R.phase_tec(obs.L1, obs.L2)
        obs["slip"] = ((obs.lli & 1) > 0).astype(int)
        obs["t"] = pd.to_datetime(obs.tsec, unit="s", utc=True)
        obs = obs.dropna(subset=["phase_tec", "elev_deg"])
        rot, qc = R.compute_rot(obs, elev_mask=p["elev_mask_deg"], base_s=p["rot_base_s"], gap_s=p["arc_gap_s"],
                                jump_tecu=p["slip_jump_tecu"], rot_reject=p["rot_reject_tecu_min"])
        ro = R.compute_roti(rot, win_s=p["roti_window_s"], base_s=p["rot_base_s"])
        net = R.network(ro, thr=p["disturbed_threshold"], min_sats=p["min_sats_network"])
        conn.executemany("insert or replace into roti values(?,?,?,?,?,?)",
                         [(iso(w), station, int(sv), float(r), int(n), float(e)) for w, sv, r, n, e in ro[["win", "sv", "roti", "n", "elev"]].itertuples(index=False)])
        conn.executemany("insert or replace into roti_network values(?,?,?,?,?,?,?,?)",
                         [(iso(x.win), station, x.roti_max, x.roti_2nd, x.roti_med, x.roti_mean, int(x.n_sats), x.frac_gt) for x in net.itertuples()])
        rej = round(100 * qc["rot_rejected"] / max(1, qc["rot_total"]), 3)
        mark("ok", file=os.path.basename(path), n_obs=len(obs), n_windows=len(net), rej=rej,
             msg=f"mlat {mlat:.1f}, {info['receiver']}, RINEX {info['version']}")
        log.info("%s %s ok: %d obs, %d network windows, median ROTI %.3f, %.1f%% windows >0.5",
                 station, day_s, len(obs), len(net), ro.roti.median() if len(ro) else np.nan,
                 100 * (ro.roti > p["disturbed_threshold"]).mean() if len(ro) else np.nan)
        if not cfg["paths"].get("keep_raw", False): os.remove(path)
        return "ok"
    except Exception as e:
        log.exception("%s %s failed: %s", station, day_s, e); mark("error", msg=str(e)[:300]); return "error"

def update_indices(conn, start, end):
    """Kp (GFZ) and Dst (Kyoto) for the date range."""
    try:
        rows = archives.gfz_kp(start, end)
        conn.executemany("insert or replace into kp_index values(?,?,?,?)", [(t, k, s, "GFZ") for t, k, s in rows])
        conn.execute("insert into fetch_log(ts_utc,source,status) values(datetime('now'),'gfz_kp',?)", (f"ok {len(rows)}",))
    except Exception as e:
        log.warning("Kp fetch failed: %s", e); conn.execute("insert into fetch_log(ts_utc,source,status) values(datetime('now'),'gfz_kp',?)", (str(e)[:200],))
    months = sorted({(d.year, d.month) for d in pd.date_range(start, end)})
    for y, m in months:
        try:
            prod, rows = archives.kyoto_dst(y, m)
            conn.executemany("insert or replace into dst_index values(?,?,?)", [(t, v, prod) for t, v in rows])
            conn.execute("insert into fetch_log(ts_utc,source,status) values(datetime('now'),'kyoto_dst',?)", (f"ok {prod} {y}-{m}",))
        except Exception as e:
            log.warning("Dst fetch failed %s-%s: %s", y, m, e)
    conn.commit()

def import_home(conn, home_db, start=None, end=None, station="HOME", cfg=None):
    """Bring the home station's own gnss_tec.db through the SAME ROTI code
    (1-Hz data: arc gap 2.5 s and slip jump 1 TECU, as in the reanalysis)."""
    import sqlite3
    p = cfg["processing"]
    if home_db.endswith(".csv"):            # a per-second CSV export (same columns as the tec table)
        chunks = [pd.read_csv(home_db, usecols=["ts_utc", "sv", "elev_deg", "phase_tec", "slip"])]
    else:
        src = sqlite3.connect(f"file:{home_db}?mode=ro", uri=True)
        q = "select ts_utc, sv, elev_deg, phase_tec, slip from tec"
        if start: q += f" where ts_utc >= '{start}' and ts_utc < '{end}'"
        chunks = pd.read_sql(q, src, chunksize=2_000_000)
    for chunk in chunks:
        chunk["t"] = pd.to_datetime(chunk.ts_utc, utc=True, format="ISO8601")
        chunk = chunk.drop_duplicates(subset=["sv", "t"])
        rot, qc = R.compute_rot(chunk, elev_mask=p["elev_mask_deg"], base_s=p["rot_base_s"], gap_s=2.5, jump_tecu=1.0, rot_reject=p["rot_reject_tecu_min"])
        ro = R.compute_roti(rot, win_s=p["roti_window_s"], base_s=p["rot_base_s"])
        net = R.network(ro, thr=p["disturbed_threshold"], min_sats=p["min_sats_network"])
        conn.executemany("insert or replace into roti values(?,?,?,?,?,?)", [(iso(w), station, int(sv), float(r), int(n), float(e)) for w, sv, r, n, e in ro[["win", "sv", "roti", "n", "elev"]].itertuples(index=False)])
        conn.executemany("insert or replace into roti_network values(?,?,?,?,?,?,?,?)", [(iso(x.win), station, x.roti_max, x.roti_2nd, x.roti_med, x.roti_mean, int(x.n_sats), x.frac_gt) for x in net.itertuples()])
        conn.commit(); log.info("HOME chunk: %d network windows", len(net))
