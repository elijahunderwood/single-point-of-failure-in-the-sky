#!/usr/bin/env python3
"""flare_logger.py - solar-flare X-ray logger + ionospheric TEC-response analysis.

Idea: Bekker, Milligan & Ryakhovsky (2024, arXiv:2407.14287). Flare X-ray/EUV light ionises the
sunlit ionosphere within ~1 minute, so total electron content (TEC) jumps. They removed the slow
background by fitting a parabola to TEC around the flare and looked at what was left (dTEC).

Commands (run with ./venv/bin/python flare_logger.py <command>):
  poll                 fetch NOAA SWPC GOES X-ray flux + flare list, then analyse any M1+ flare whose
                       home-TEC window is now complete (this is what the systemd timer runs)
  backfill [--start D] [--end D]
                       NOAA/NCEI GOES-19 science archive: daily flare lists + 1-min flux, then analyse
                       every M/X flare against the home TEC data
  analyse [--redo]     (re)run the home-station analysis for every M1+ flare
  global [--min-class M5] [--flare ID] [--redo] [--max N]
                       same analysis on the global_logger stations that were on the dayside. The global
                       database only stores ROTI (no per-epoch TEC), so this re-downloads each station's
                       30-s RINEX file for the flare day from Geoscience Australia and computes phase TEC
                       with the global_logger code (files deleted afterwards)
  plot [--flare ID]    figures/strongest_event.png (X-ray flux over dTEC) + figures/summary_scatter.png
  status               counts and the latest results
"""
import os, sys, json, math, time, sqlite3, argparse, logging, fcntl, urllib.request, datetime as dt
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser("~")
DB = os.path.join(HERE, "flare.db")
HOME_DB = os.path.join(HOME, "gnss-logger", "gnss_tec.db")
GLOBAL_DIR = os.path.join(HOME, "global_logger")
GLOBAL_DB = os.path.join(GLOBAL_DIR, "data", "global_roti.db")
FIG = os.path.join(HERE, "figures"); RAW = os.path.join(HERE, "raw"); LOGD = os.path.join(HERE, "logs")
BELFAST = (54.6, -5.9)
SWPC = "https://services.swpc.noaa.gov/json/goes/primary/"
NCEI = "https://data.ngdc.noaa.gov/platforms/solar-space-observing-satellites/goes/goes{sat}/l2/data/"
GOES_SAT = 19                       # GOES-19 has been the primary X-ray satellite since 2025
HOME_START = dt.date(2026, 7, 30)   # first day of home TEC data

# ---- analysis settings (see README) ----
PRE_MIN, POST_MIN = 30, 90          # analysis window: flare start -30 min ... start +90 min (longer if the flare is long)
EXCL_PRE_MIN, EXCL_POST_MIN = 2, 15 # left out of the parabola fit: start-2 min ... end+15 min (the flare period)
ELEV_MASK = 30.0                    # degrees
BIN_S = 30                          # residuals averaged into 30-s bins
SIGMA_MULT, MIN_DTEC = 3.0, 0.10    # a satellite "responds" if peak dTEC AND its rise above the pre-flare level are both >= max(3 x noise, 0.10 TECU)
MIN_SIDE_MIN = 10                   # need >= 10 min of clean data both before and after the flare period
DETECT_FRAC, DETECT_MIN_RESP = 0.5, 2   # event "detected" if >= 2 satellites AND >= half of the usable ones respond

os.makedirs(LOGD, exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(os.path.join(LOGD, "flare_logger.log"))])
log = logging.getLogger("flare")
UTC = dt.timezone.utc

def now(): return dt.datetime.now(UTC)
def iso(t): return pd.Timestamp(t).tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%S+00:00") if pd.Timestamp(t).tzinfo else pd.Timestamp(t).tz_localize("UTC").strftime("%Y-%m-%dT%H:%M:%S+00:00")
def ts(s): return pd.Timestamp(s).tz_convert("UTC") if pd.Timestamp(s).tzinfo else pd.Timestamp(s).tz_localize("UTC")

def class_flux(c):
    try: return {"A": 1e-8, "B": 1e-7, "C": 1e-6, "M": 1e-5, "X": 1e-4}[c[0].upper()] * float(c[1:])
    except Exception: return None

def flux_class(f):
    for L, b in (("X", 1e-4), ("M", 1e-5), ("C", 1e-6), ("B", 1e-7), ("A", 1e-8)):
        if f >= b: return f"{L}{f/b:.1f}"
    return "A0.0"

def sza(t, lat, lon):
    """Solar zenith angle (deg), NOAA general solar position formulae (accurate to ~0.5 deg)."""
    t = ts(t); doy = t.dayofyear; hr = t.hour + t.minute/60 + t.second/3600
    g = 2*math.pi/365*(doy - 1 + (hr - 12)/24)
    dec = (0.006918 - 0.399912*math.cos(g) + 0.070257*math.sin(g) - 0.006758*math.cos(2*g)
           + 0.000907*math.sin(2*g) - 0.002697*math.cos(3*g) + 0.00148*math.sin(3*g))
    eqt = 229.18*(0.000075 + 0.001868*math.cos(g) - 0.032077*math.sin(g) - 0.014615*math.cos(2*g) - 0.040849*math.sin(2*g))
    ha = math.radians((hr*60 + eqt + 4*lon)/4 - 180)
    la = math.radians(lat)
    c = math.sin(la)*math.sin(dec) + math.cos(la)*math.cos(dec)*math.cos(ha)
    return math.degrees(math.acos(max(-1, min(1, c))))

def http(url, timeout=60, tries=4):
    err = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "flare_logger (school science project)"})
            with urllib.request.urlopen(req, timeout=timeout) as r: return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404: raise
            err = e
        except Exception as e: err = e
        time.sleep(5 * 2**i)
    raise RuntimeError(f"giving up on {url}: {err}")

# ------------------------------------------------------------------ database
SCHEMA = """
CREATE TABLE IF NOT EXISTS xray_flux(        -- GOES 1-minute X-ray flux, W/m2
  ts_utc TEXT PRIMARY KEY, flux_short REAL,  -- 0.05-0.4 nm (XRS-A)
  flux_long REAL,                            -- 0.1-0.8 nm (XRS-B, the one flare classes use)
  satellite INTEGER, source TEXT);
CREATE TABLE IF NOT EXISTS flares(           -- one row per flare (all classes the feed/archive lists)
  flare_id TEXT PRIMARY KEY,                 -- start time YYYYMMDDHHMM (same id NOAA/NCEI uses)
  begin_utc TEXT, peak_utc TEXT, end_utc TEXT, class TEXT, peak_flux REAL, satellite INTEGER,
  source TEXT,                               -- swpc (real-time feed) or ncei (science archive)
  belfast_sza_deg REAL,                      -- solar zenith angle at Belfast at the flare peak
  belfast_sunlit INTEGER,                    -- 1 if that SZA < 90
  updated_utc TEXT);
CREATE TABLE IF NOT EXISTS flare_response(   -- one row per flare x station x kind
  flare_id TEXT, station TEXT,               -- HOME = Belfast receiver, else global_logger code
  kind TEXT,                                 -- 'flare' or 'control' (same clock time 24 h earlier)
  sza_deg REAL, sunlit INTEGER,
  status TEXT,                               -- ok | waiting | no_data | night | error
  n_sats_used INTEGER, n_sats_responded INTEGER,
  peak_dtec REAL,                            -- largest dTEC of any responding satellite, TECU
  median_peak_dtec REAL,                     -- median peak dTEC of the responding satellites
  mean_peak_dtec_all REAL,                   -- mean peak dTEC over ALL usable satellites
  time_to_peak_min REAL,                     -- median minutes from flare start to dTEC peak (responders)
  lag_after_xray_peak_min REAL,              -- same, measured from the X-ray peak
  noise_tecu REAL,                           -- median residual noise (1 sigma) outside the flare period
  detected INTEGER, message TEXT, updated_utc TEXT,
  PRIMARY KEY(flare_id, station, kind));
CREATE TABLE IF NOT EXISTS flare_response_sat(
  flare_id TEXT, station TEXT, kind TEXT, sv INTEGER, mean_elev REAL, n_points INTEGER,
  noise_tecu REAL, peak_dtec REAL, time_to_peak_min REAL, responded INTEGER,
  PRIMARY KEY(flare_id, station, kind, sv));
CREATE TABLE IF NOT EXISTS fetch_log(id INTEGER PRIMARY KEY AUTOINCREMENT, ts_utc TEXT, source TEXT, rows_new INTEGER, status TEXT);
"""

def db():
    c = sqlite3.connect(DB, timeout=60)
    c.execute("PRAGMA journal_mode=WAL"); c.executescript(SCHEMA); return c

def flog(c, source, n, status):
    c.execute("insert into fetch_log(ts_utc,source,rows_new,status) values(?,?,?,?)", (iso(now()), source, n, status)); c.commit()

def upsert_flare(c, fid, b, p, e, cls, pf, sat, source):
    """Insert a flare; an NCEI (science) row wins over a real-time SWPC row for the same flare (start within 3 min)."""
    bt = ts(b)
    near = c.execute("select flare_id, source from flares where begin_utc between ? and ?",
                     (iso(bt - pd.Timedelta(minutes=3)), iso(bt + pd.Timedelta(minutes=3)))).fetchall()
    for oid, osrc in near:
        if osrc == "ncei" and source == "swpc": return 0
        if oid != fid:   # replace the other-source duplicate, keep analysis rows pointing at the new id
            c.execute("delete from flares where flare_id=?", (oid,))
            for tb in ("flare_response", "flare_response_sat"):
                c.execute(f"update or ignore {tb} set flare_id=? where flare_id=?", (fid, oid))
                c.execute(f"delete from {tb} where flare_id=?", (oid,))
    z = sza(p, *BELFAST)
    new = c.execute("select 1 from flares where flare_id=?", (fid,)).fetchone() is None
    c.execute("insert or replace into flares values(?,?,?,?,?,?,?,?,?,?,?)",
              (fid, iso(b), iso(p), iso(e) if e else None, cls, pf, sat, source, round(z, 2), int(z < 90), iso(now())))
    return int(new)

# ------------------------------------------------------------------ fetching
def fetch_swpc(c, first=False):
    n = 0
    for name in (["xrays-7-day.json"] if first else ["xrays-1-day.json"]):
        try:
            rows = json.loads(http(SWPC + name)); d = {}
            for r in rows:
                k = r["time_tag"]; e = r.get("energy"); f = r.get("flux")
                d.setdefault(k, {"sat": r.get("satellite")})
                if e == "0.05-0.4nm": d[k]["s"] = f
                elif e == "0.1-0.8nm": d[k]["l"] = f
            before = c.total_changes
            c.executemany("insert or ignore into xray_flux values(?,?,?,?,?)",
                          [(iso(k), v.get("s"), v.get("l"), v["sat"], "swpc") for k, v in d.items()])
            n = c.total_changes - before; flog(c, name, n, "ok")
            log.info("%s: %d records, %d new", name, len(d), n)
        except Exception as e:
            flog(c, name, None, f"error: {str(e)[:200]}"); log.error("%s failed: %s", name, e)
    try:
        rows = json.loads(http(SWPC + "xray-flares-7-day.json")); m = 0
        for r in rows:
            if not r.get("max_class") or r.get("end_time") in (None, "Unk") or r.get("max_time") in (None, "Unk"): continue
            fid = ts(r["begin_time"]).strftime("%Y%m%d%H%M")
            m += upsert_flare(c, fid, r["begin_time"], r["max_time"], r["end_time"], r["max_class"],
                              r.get("max_xrlong") or class_flux(r["max_class"]), r.get("satellite"), "swpc")
        c.commit(); flog(c, "xray-flares-7-day.json", m, "ok"); log.info("flare list: %d listed, %d new", len(rows), m)
    except Exception as e:
        flog(c, "xray-flares-7-day.json", None, f"error: {str(e)[:200]}"); log.error("flare list failed: %s", e)

def ncei_file(kind, day, tmpdir):
    import netCDF4
    base = NCEI.format(sat=GOES_SAT) + f"xrsf-l2-{kind}_science/{day:%Y/%m}/"
    for v in ("v2-2-2", "v2-2-1", "v2-2-0", "v2-1-0"):
        fn = f"sci_xrsf-l2-{kind}_g{GOES_SAT}_d{day:%Y%m%d}_{v}.nc"
        try: data = http(base + fn, tries=2)
        except urllib.error.HTTPError: continue
        p = os.path.join(tmpdir, fn); open(p, "wb").write(data)
        ds = netCDF4.Dataset(p); return ds, p
    return None, None

def backfill_ncei(c, start, end):
    os.makedirs(RAW, exist_ok=True); day = start; nf = nx = 0; missing = []
    while day <= end:
        ds, p = ncei_file("flsum", day, RAW)
        if ds is None: missing.append(day.isoformat())
        else:
            import netCDF4
            t = netCDF4.num2date(ds["time"][:], ds["time"].units, only_use_cftime_datetimes=False)
            st = [str(s) for s in ds["status"][:]]; cl = ds["flare_class"][:]; fl = ds["xrsb_flux"][:]; ids = ds["flare_id"][:]
            ev = {}
            for i in range(len(t)):
                k = str(ids[i]); e = ev.setdefault(k, {})
                tt = pd.Timestamp(t[i]).tz_localize("UTC")
                if st[i] == "EVENT_START": e["b"] = tt
                elif st[i] == "EVENT_PEAK": e["p"] = tt; e["c"] = str(cl[i]); e["f"] = float(fl[i])
                elif st[i] == "EVENT_END": e["e"] = tt
            for k, e in ev.items():
                if "b" in e and "p" in e and e.get("c"):
                    nf += upsert_flare(c, e["b"].strftime("%Y%m%d%H%M"), e["b"], e["p"], e.get("e"), e["c"], e["f"], GOES_SAT, "ncei")
            ds.close(); os.remove(p)
        ds, p = ncei_file("avg1m", day, RAW)
        if ds is not None:
            import netCDF4
            t = netCDF4.num2date(ds["time"][:], ds["time"].units, only_use_cftime_datetimes=False)
            a = np.ma.filled(ds["xrsa_flux"][:].astype(float), np.nan); b = np.ma.filled(ds["xrsb_flux"][:].astype(float), np.nan)
            fa = np.ma.filled(ds["xrsa_flag"][:], 0); fb = np.ma.filled(ds["xrsb_flag"][:], 0)
            a[fa != 0] = np.nan; b[fb != 0] = np.nan
            rows = [(iso(pd.Timestamp(t[i]).tz_localize("UTC")), None if np.isnan(a[i]) else float(a[i]),
                     None if np.isnan(b[i]) else float(b[i]), GOES_SAT, "ncei") for i in range(len(t))]
            before = c.total_changes; c.executemany("insert or ignore into xray_flux values(?,?,?,?,?)", rows); nx += c.total_changes - before
            ds.close(); os.remove(p)
        c.commit(); day += dt.timedelta(days=1)
    flog(c, "ncei-backfill", nf, "ok" + (f" (missing {len(missing)} days)" if missing else ""))
    log.info("NCEI backfill %s..%s: %d new flares, %d new flux rows, no archive file for %s", start, end, nf, nx, missing or "none")
    return missing

# ------------------------------------------------------------------ TEC analysis
def windows(fl, shift=pd.Timedelta(0)):
    b = ts(fl["begin_utc"]) - shift; p = ts(fl["peak_utc"]) - shift
    e = ts(fl["end_utc"]) - shift if fl["end_utc"] else p + pd.Timedelta(minutes=10)
    return dict(b=b, p=p, e=e, w0=b - pd.Timedelta(minutes=PRE_MIN), w1=max(b + pd.Timedelta(minutes=POST_MIN), e + pd.Timedelta(minutes=30)),
                x0=b - pd.Timedelta(minutes=EXCL_PRE_MIN), x1=e + pd.Timedelta(minutes=EXCL_POST_MIN))

def analyse_sats(df, W, gap_s, jump_tecu, min_arc_fit):
    """df: t (UTC), sv, elev_deg, phase_tec, slip. Per satellite: split into phase arcs, fit ONE parabola
    in time plus a separate offset for each arc to the points outside the flare period (least squares),
    subtract it, average the residual (dTEC) into 30-s bins. Returns list of per-sat dicts and binned series."""
    out, series = [], {}
    if df.empty: return out, series
    tmin = ((df.t - W["b"]).dt.total_seconds() / 60.0).to_numpy()
    df = df.assign(m=tmin)
    x0 = (W["x0"] - W["b"]).total_seconds()/60; x1 = (W["x1"] - W["b"]).total_seconds()/60
    for sv, d in df.groupby("sv"):
        d = d.sort_values("m")
        d = d[(d.elev_deg >= ELEV_MASK) & d.phase_tec.notna()]
        if len(d) < 10: continue
        dm = np.diff(d.m.to_numpy(), prepend=-1e9) * 60; dtec = np.abs(np.diff(d.phase_tec.to_numpy(), prepend=np.nan))
        new = (d.slip.to_numpy() == 1) | (dm > gap_s) | (dtec > jump_tecu)
        arc = np.cumsum(new); d = d.assign(arc=arc)
        fitm = (d.m < x0) | (d.m > x1)
        good = d[fitm].groupby("arc").size(); good = good[good >= min_arc_fit].index
        d = d[d.arc.isin(good)]; fitm = (d.m < x0) | (d.m > x1)
        pre = d[(d.m < x0)].m; post = d[(d.m > x1)].m
        if pre.empty or post.empty: continue
        if (pre.max() - pre.min()) < MIN_SIDE_MIN or (post.max() - post.min()) < MIN_SIDE_MIN: continue
        arcs = sorted(d.arc.unique()); ai = {a: i for i, a in enumerate(arcs)}
        xs = d.m.to_numpy() / 60.0
        A = np.zeros((len(d), len(arcs) + 2)); A[np.arange(len(d)), [ai[a] for a in d.arc]] = 1; A[:, -2] = xs; A[:, -1] = xs**2
        y = d.phase_tec.to_numpy(); fm = fitm.to_numpy()
        coef, *_ = np.linalg.lstsq(A[fm], y[fm], rcond=None)
        res = y - A @ coef
        bins = np.floor(d.m.to_numpy() * 60 / BIN_S).astype(int)
        s = pd.Series(res).groupby(bins).mean(); s.index = s.index * BIN_S / 60.0   # minutes from flare start
        sfit = s[(s.index < x0) | (s.index > x1)]; sresp = s[(s.index >= x0) & (s.index <= x1)]
        need = (x1 - x0) * 60 / BIN_S
        if len(sresp) < 0.5 * need or len(sfit) < 10: continue
        noise = float(sfit.std()); pk = float(sresp.max()); tpk = float(sresp.idxmax())
        pre = s[(s.index >= x0 - 8) & (s.index < x0)]          # level just before the flare
        rise = pk - (float(pre.mean()) if len(pre) else 0.0)
        thr = max(SIGMA_MULT * noise, MIN_DTEC)
        resp = (pk >= thr) and (rise >= thr)                   # must be a rise at the flare, not an old trend
        out.append(dict(sv=int(sv), mean_elev=float(d.elev_deg.mean()), n_points=int(len(d)), noise=noise,
                        peak=pk, tpk=tpk, resp=int(resp)))
        series[int(sv)] = s
    return out, series

def summarise(sats, W):
    if not sats: return dict(n_used=0, n_resp=0, peak=None, med=None, mean_all=None, tpk=None, lag=None, noise=None, det=0)
    r = [s for s in sats if s["resp"]]; lagoff = (W["p"] - W["b"]).total_seconds()/60
    tpk = float(np.median([s["tpk"] for s in r])) if r else None
    return dict(n_used=len(sats), n_resp=len(r), peak=max(s["peak"] for s in r) if r else None,
                med=float(np.median([s["peak"] for s in r])) if r else None,
                mean_all=float(np.mean([s["peak"] for s in sats])), tpk=tpk, lag=(tpk - lagoff) if tpk is not None else None,
                noise=float(np.median([s["noise"] for s in sats])),
                det=int(len(r) >= DETECT_MIN_RESP and len(r) >= DETECT_FRAC * len(sats)))

def save_result(c, fid, station, kind, z, status, S=None, sats=(), msg=""):
    S = S or {}
    c.execute("insert or replace into flare_response values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
              (fid, station, kind, None if z is None else round(z, 2), None if z is None else int(z < 90), status,
               S.get("n_used"), S.get("n_resp"), S.get("peak"), S.get("med"), S.get("mean_all"), S.get("tpk"), S.get("lag"),
               S.get("noise"), S.get("det"), msg, iso(now())))
    c.execute("delete from flare_response_sat where flare_id=? and station=? and kind=?", (fid, station, kind))
    c.executemany("insert into flare_response_sat values(?,?,?,?,?,?,?,?,?,?)",
                  [(fid, station, kind, s["sv"], s["mean_elev"], s["n_points"], s["noise"], s["peak"], s["tpk"], s["resp"]) for s in sats])
    c.commit()

def load_home(t0, t1):
    h = sqlite3.connect(f"file:{HOME_DB}?mode=ro", uri=True, timeout=60)
    df = pd.read_sql_query("select ts_utc, sv, elev_deg, phase_tec, slip from tec where ts_utc >= ? and ts_utc < ?",
                           h, params=(iso(t0)[:19], iso(t1)[:19])); h.close()
    df["t"] = pd.to_datetime(df.ts_utc, utc=True, format="ISO8601"); return df

def home_latest():
    h = sqlite3.connect(f"file:{HOME_DB}?mode=ro", uri=True, timeout=60)
    v = h.execute("select max(ts_utc) from tec").fetchone()[0]; h.close(); return ts(v)

def m_plus(c, where="", args=()):
    c.row_factory = sqlite3.Row
    rows = c.execute(f"select * from flares where (class like 'M%' or class like 'X%') {where} order by begin_utc", args).fetchall()
    c.row_factory = None; return rows

def analyse_home(c, redo=False):
    latest = home_latest(); done = 0
    for fl in m_plus(c):
        for kind, shift in (("flare", pd.Timedelta(0)), ("control", pd.Timedelta(hours=24))):
            row = c.execute("select status from flare_response where flare_id=? and station='HOME' and kind=?", (fl["flare_id"], kind)).fetchone()
            if row and row[0] in ("ok", "no_data", "night") and not redo: continue
            W = windows(fl, shift); z = sza(W["p"], *BELFAST)
            if z >= 90:
                save_result(c, fl["flare_id"], "HOME", kind, z, "night", msg="Belfast in darkness at flare peak"); continue
            if W["w1"] + pd.Timedelta(minutes=2) > latest:
                if (now() - W["w1"]).total_seconds() > 3*86400:
                    save_result(c, fl["flare_id"], "HOME", kind, z, "no_data", msg="home TEC logger has no data for this window")
                else:
                    save_result(c, fl["flare_id"], "HOME", kind, z, "waiting", msg="waiting for home TEC data to cover the window")
                continue
            try:
                df = load_home(W["w0"], W["w1"])
                if df.empty: save_result(c, fl["flare_id"], "HOME", kind, z, "no_data", msg="no home TEC rows in window"); continue
                sats, _ = analyse_sats(df, W, gap_s=10, jump_tecu=1.0, min_arc_fit=60)
                S = summarise(sats, W)
                save_result(c, fl["flare_id"], "HOME", kind, z, "ok", S, sats,
                            msg=f"{len(df)} rows, {df.sv.nunique()} sats in window")
                done += 1
                if kind == "flare":
                    log.info("HOME %s %s SZA %.0f: %d/%d sats responded, peak %s TECU, detected=%d", fl["flare_id"], fl["class"], z,
                             S["n_resp"], S["n_used"], f"{S['peak']:.2f}" if S["peak"] else "-", S["det"])
            except Exception as e:
                log.exception("HOME analysis %s failed", fl["flare_id"]); save_result(c, fl["flare_id"], "HOME", kind, z, "error", msg=str(e)[:300])
    return done

# ------------------------------------------------------------------ global stations
_gl = None
def gl_modules():
    global _gl
    if _gl is None:
        sys.path.insert(0, GLOBAL_DIR)
        from global_logger import archives, rinex, roti as R
        _gl = (archives, rinex, R)
    return _gl

_daycache = {}
def load_global_day(station, day):
    key = (station, day)
    if key in _daycache: return _daycache[key]
    archives, rinex, R = gl_modules()
    raw = os.path.join(RAW, day.strftime("%Y/%j")); os.makedirs(raw, exist_ok=True)
    path = archives.download_obs(station, day, raw)
    if path is None: _daycache[key] = None; return None
    try:
        nav = archives.download_nav(day, os.path.join(RAW, "nav"))
        text = rinex.open_obs(path); obs, info = rinex.read_obs(text); del text
        if obs.empty or info["xyz"] is None: raise ValueError("no GPS L1/L2 observations or no position")
        eph = rinex.read_nav2(nav)
        d0 = pd.Timestamp(day, tz="UTC").value / 1e9
        obs = obs[obs.tsec.between(d0, d0 + 86399)].reset_index(drop=True)
        obs["elev_deg"] = rinex.add_elevations(obs, info["xyz"], eph)
        obs["phase_tec"] = R.phase_tec(obs.L1, obs.L2)
        obs["slip"] = ((obs.lli & 1) > 0).astype(int)
        obs["t"] = pd.to_datetime(obs.tsec, unit="s", utc=True)
        obs = obs.dropna(subset=["phase_tec", "elev_deg"])[["t", "sv", "elev_deg", "phase_tec", "slip"]]
    finally:
        os.remove(path)
    if len(_daycache) > 6: _daycache.clear()
    _daycache[key] = obs; return obs

def global_stations():
    g = sqlite3.connect(f"file:{GLOBAL_DB}?mode=ro", uri=True, timeout=60)
    r = g.execute("select station, name, lat, lon, geomag_lat from stations where lat is not null order by station").fetchall(); g.close()
    return r

def analyse_global(c, min_class="M1", only=None, redo=False, max_flares=None, pending_only=False):
    mf = class_flux(min_class); n = 0
    stations = global_stations()
    for fl in m_plus(c):
        if only and fl["flare_id"] != only: continue
        if (fl["peak_flux"] or class_flux(fl["class"]) or 0) < mf: continue
        W = windows(fl)
        if (now() - W["w1"]).total_seconds() < 30*3600: continue        # GA daily files appear the next day
        did = False
        for st, name, lat, lon, mlat in stations:
            row = c.execute("select status from flare_response where flare_id=? and station=? and kind='flare'", (fl["flare_id"], st)).fetchone()
            if row and row[0] in ("ok", "no_data", "night") and not redo: continue
            if row and row[0] == "error" and pending_only and not redo: continue
            z = sza(W["p"], lat, lon)
            if z >= 90: save_result(c, fl["flare_id"], st, "flare", z, "night", msg="station in darkness at flare peak"); continue
            did = True
            try:
                days = sorted({W["w0"].date(), W["w1"].date()})
                parts = [load_global_day(st, d) for d in days]
                if any(p is None for p in parts):
                    save_result(c, fl["flare_id"], st, "flare", z, "no_data", msg="no daily 30-s file in archive"); continue
                df = pd.concat(parts); df = df[(df.t >= W["w0"]) & (df.t < W["w1"])]
                sats, _ = analyse_sats(df, W, gap_s=45, jump_tecu=5.0, min_arc_fit=6)
                S = summarise(sats, W)
                save_result(c, fl["flare_id"], st, "flare", z, "ok", S, sats, msg=f"{name}; mlat {mlat:.1f}; 30-s RINEX")
                log.info("%s %s %s SZA %.0f: %d/%d sats responded, peak %s TECU", st, fl["flare_id"], fl["class"], z,
                         S["n_resp"], S["n_used"], f"{S['peak']:.2f}" if S["peak"] else "-")
            except Exception as e:
                log.exception("%s %s failed", st, fl["flare_id"]); save_result(c, fl["flare_id"], st, "flare", z, "error", msg=str(e)[:300])
        if did:
            n += 1
            if max_flares and n >= max_flares: break
    return n

# ------------------------------------------------------------------ plots
def plot(c, fid=None):
    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt, matplotlib.dates as mdates
    os.makedirs(FIG, exist_ok=True)
    outname = "strongest_event.png" if fid is None else f"flare_{fid}.png"
    if fid is None:
        r = c.execute("""select f.flare_id from flares f join flare_response r on r.flare_id=f.flare_id
                         where r.station='HOME' and r.kind='flare' and r.status='ok' order by f.peak_flux desc limit 1""").fetchone()
        if not r: log.warning("no analysed daytime flare to plot"); return None
        fid = r[0]
    c.row_factory = sqlite3.Row; fl = c.execute("select * from flares where flare_id=?", (fid,)).fetchone()
    res = c.execute("select * from flare_response where flare_id=? and station='HOME' and kind='flare'", (fid,)).fetchone(); c.row_factory = None
    W = windows(fl); df = load_home(W["w0"], W["w1"])
    sats, series = analyse_sats(df, W, gap_s=10, jump_tecu=1.0, min_arc_fit=60)
    fx = pd.read_sql_query("select ts_utc, flux_short, flux_long from xray_flux where ts_utc between ? and ? order by ts_utc", c,
                           params=(iso(W["w0"]), iso(W["w1"])))
    fx["t"] = pd.to_datetime(fx.ts_utc, utc=True)
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(10, 7.5), sharex=True, gridspec_kw={"height_ratios": [1, 1.4]})
    a1.semilogy(fx.t, fx.flux_long, color="tab:red", label="GOES 0.1-0.8 nm (XRS-B)")
    a1.semilogy(fx.t, fx.flux_short, color="tab:purple", label="GOES 0.05-0.4 nm (XRS-A)")
    for lv, L in ((1e-6, "C"), (1e-5, "M"), (1e-4, "X")): a1.axhline(lv, color="grey", lw=0.5, ls=":"); a1.text(W["w0"], lv*1.1, L, color="grey", fontsize=8)
    a1.set_ylabel("X-ray flux (W m$^{-2}$)"); a1.legend(loc="upper right", fontsize=8)
    a1.set_title(f"{fl['class']} flare {ts(fl['begin_utc']):%d %b %Y}, start {ts(fl['begin_utc']):%H:%M} UTC, "
                 f"peak {ts(fl['peak_utc']):%H:%M} UTC  |  Belfast SZA {fl['belfast_sza_deg']:.0f}°")
    resp = {s["sv"]: s for s in sats}; allbins = []
    for sv, s in series.items():
        tt = W["b"] + pd.to_timedelta(s.index, unit="min")
        a2.plot(tt, s.values, lw=1.0 if resp[sv]["resp"] else 0.6, alpha=0.9 if resp[sv]["resp"] else 0.4,
                label=f"G{sv:02d} ({resp[sv]['mean_elev']:.0f}°){' *' if resp[sv]['resp'] else ''}")
        allbins.append(s)
    if allbins:
        m = pd.concat(allbins, axis=1).mean(axis=1); a2.plot(W["b"] + pd.to_timedelta(m.index, unit="min"), m.values, color="k", lw=2.2, label="mean of satellites")
    for a in (a1, a2):
        a.axvspan(W["b"], W["e"], color="orange", alpha=0.15); a.axvspan(W["x0"], W["x1"], color="orange", alpha=0.07)
        a.axvline(W["p"], color="tab:red", lw=0.8, ls="--")
    a2.axhline(0, color="grey", lw=0.6)
    a2.set_ylabel("dTEC (TECU)  [phase TEC minus parabolic trend]")
    a2.set_xlabel("Time (UTC)"); a2.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    txt = (f"Belfast receiver, elevation > {ELEV_MASK:.0f}°: {res['n_sats_responded']}/{res['n_sats_used']} satellites responded"
           + (f", peak dTEC {res['peak_dtec']:.2f} TECU, median time to peak {res['time_to_peak_min']:.1f} min" if res["peak_dtec"] else "")
           + f"  (noise ~{res['noise_tecu']:.3f} TECU)")
    a2.set_title(txt, fontsize=9); a2.legend(fontsize=7, ncol=4, loc="upper left")
    fig.text(0.01, 0.005, "Shaded: flare start-end (dark) and the period left out of the parabola fit (light). Dashed: X-ray peak. "
             "* = responded (peak and rise >= 3x noise, >= 0.1 TECU). After Bekker et al. 2024.", fontsize=7)
    fig.tight_layout(rect=(0, 0.02, 1, 1)); out = os.path.join(FIG, outname); fig.savefig(out, dpi=130); plt.close(fig)
    log.info("wrote %s (%s)", out, fid)
    # summary scatter: peak dTEC vs X-ray peak flux, flares vs 24-h-earlier controls
    q = pd.read_sql_query("""select f.flare_id, f.class, f.peak_flux, r.kind, r.sza_deg, r.mean_peak_dtec_all, r.detected
                             from flare_response r join flares f on f.flare_id=r.flare_id
                             where r.station='HOME' and r.status='ok'""", c)
    if not q.empty:
        fig, ax = plt.subplots(figsize=(8, 5.5))
        for kind, col, mk in (("control", "grey", "x"), ("flare", "tab:red", "o")):
            d = q[q.kind == kind]
            if kind == "flare":
                sc = ax.scatter(d.peak_flux, d.mean_peak_dtec_all, c=d.sza_deg, cmap="viridis_r", marker=mk, s=40, edgecolor=np.where(d.detected == 1, "k", "none"), label="flare window (colour = SZA)")
                fig.colorbar(sc, ax=ax, label="Belfast solar zenith angle (°)")
            else:
                ax.scatter(d.peak_flux, d.mean_peak_dtec_all, color=col, marker=mk, s=25, label="control: same time 24 h earlier")
        ax.set_xscale("log"); ax.set_xlabel("GOES X-ray peak flux 0.1-0.8 nm (W m$^{-2}$)"); ax.set_ylabel("mean peak dTEC over satellites (TECU)")
        ax.set_title("Belfast TEC response to daytime M/X flares (black edge = detected)"); ax.legend(fontsize=8)
        fig.tight_layout(); fig.savefig(os.path.join(FIG, "summary_scatter.png"), dpi=130); plt.close(fig)
    return out

# ------------------------------------------------------------------ status
def status(c):
    p = lambda q, a=(): c.execute(q, a).fetchall()
    print("xray_flux rows:", p("select count(*), min(ts_utc), max(ts_utc) from xray_flux")[0])
    print("flares:", p("select count(*) from flares")[0][0], " M/X:", p("select count(*) from flares where class like 'M%' or class like 'X%'")[0][0])
    print("HOME results:", p("select kind, status, count(*), sum(detected) from flare_response where station='HOME' group by kind, status"))
    print("global results:", p("select status, count(*), sum(detected) from flare_response where station!='HOME' group by status"))
    for r in p("""select f.flare_id, f.class, round(f.belfast_sza_deg), r.status, r.n_sats_responded, r.n_sats_used, round(r.peak_dtec,2), r.detected
                  from flares f left join flare_response r on r.flare_id=f.flare_id and r.station='HOME' and r.kind='flare'
                  where f.class like 'M%' or f.class like 'X%' order by f.begin_utc desc limit 10"""): print("  ", r)

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["poll", "backfill", "analyse", "global", "plot", "status"])
    ap.add_argument("--start"); ap.add_argument("--end"); ap.add_argument("--flare"); ap.add_argument("--redo", action="store_true")
    ap.add_argument("--min-class", default="M1"); ap.add_argument("--max", type=int)
    a = ap.parse_args()
    if a.cmd != "status":
        lk = open(os.path.join(HERE, f".lock-{'global' if a.cmd == 'global' else 'main'}"), "w")
        try: fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: log.warning("another %s run is active - exiting", a.cmd); return
    c = db()
    if a.cmd == "poll":
        first = c.execute("select count(*) from xray_flux").fetchone()[0] == 0
        fetch_swpc(c, first); analyse_home(c)
    elif a.cmd == "backfill":
        s = dt.date.fromisoformat(a.start) if a.start else HOME_START
        e = dt.date.fromisoformat(a.end) if a.end else (now() - dt.timedelta(days=1)).date()
        backfill_ncei(c, s, e); fetch_swpc(c, first=True); analyse_home(c, redo=a.redo); plot(c)
    elif a.cmd == "analyse": analyse_home(c, redo=a.redo)
    elif a.cmd == "global": log.info("global: %d flares processed", analyse_global(c, a.min_class, a.flare, a.redo, a.max))
    elif a.cmd == "plot": print(plot(c, a.flare))
    elif a.cmd == "status": status(c)

if __name__ == "__main__":
    main()
