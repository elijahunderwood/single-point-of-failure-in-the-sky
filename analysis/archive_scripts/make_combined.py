#!/usr/bin/env python3
"""Build one compact hourly timeline CSV from all local loggers (measured data
only). Reads each DB read-only, aggregates to an hourly grid, writes a tiny CSV.
Standard library only; the 2.4 GB TEC DB is streamed so memory stays low."""
import argparse, csv, math, os, sqlite3, statistics
from collections import defaultdict

RE, H = 6371.0, 350.0  # thin-shell radii (km) for slant->vertical TEC

def ro(path):
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=60)

def vtec_from_stec(stec, elev_deg):          # map slant TEC to vertical
    z = math.radians(90.0 - elev_deg)
    s = RE * math.sin(z) / (RE + H)
    return stec * math.sqrt(max(0.0, 1.0 - s * s))

def agg_starlink(path, rows):
    try:
        c = ro(path)
        for hr, lat, drop, dl, n in c.execute(
            "SELECT substr(ts_utc,1,13) hr, AVG(ping_latency_ms), AVG(ping_drop_rate), "
            "AVG(downlink_bps), COUNT(*) FROM history GROUP BY hr"):
            rows[hr].update(sl_lat_ms=lat, sl_drop=drop, sl_dl_bps=dl, sl_n=n)
        c.close(); print("  starlink: ok")
    except Exception as e:
        print("  starlink: SKIPPED --", e)

def agg_roti(path, rows):
    try:
        c = ro(path)
        for hr, r2, rmed in c.execute(
            "SELECT substr(window_start,1,13) hr, MAX(roti_2nd), AVG(roti_med) "
            "FROM roti_network GROUP BY hr"):
            rows[hr].update(roti2nd_max=r2, roti_med=rmed)
        c.close(); print("  roti: ok")
    except Exception as e:
        print("  roti: SKIPPED --", e)

def agg_spaceweather(path, rows):
    try:
        c = ro(path)
        for hr, d in c.execute("SELECT substr(ts_utc,1,13), dst FROM dst_index"):
            rows[hr]["dst"] = d
        for ts, kp in c.execute("SELECT ts_utc, kp FROM kp_index"):
            yr, hh = ts[:10], int(ts[11:13])
            for k in range(3):
                if hh + k < 24:
                    rows[f"{yr}T{hh+k:02d}"]["kp"] = kp
        for hr, bz in c.execute("SELECT substr(ts_utc,1,13) hr, MIN(bz_gsm) "
                                "FROM solar_wind_mag GROUP BY hr"):
            rows[hr]["bz_min"] = bz
        for hr, v in c.execute("SELECT substr(ts_utc,1,13) hr, AVG(speed_kms) "
                               "FROM solar_wind_plasma WHERE speed_kms>100 "
                               "AND speed_kms<1500 GROUP BY hr"):
            rows[hr]["vsw_mean"] = v
        c.close(); print("  spaceweather: ok")
    except Exception as e:
        print("  spaceweather: SKIPPED --", e)

def agg_vtec(path, rows, mask):
    try:
        c = ro(path)
        cur, vals, n = None, [], 0
        for ts, elev, stec in c.execute(
            "SELECT ts_utc, elev_deg, code_tec FROM tec WHERE elev_deg IS NOT NULL "
            "AND elev_deg >= ? AND code_tec IS NOT NULL ORDER BY ts_utc", (mask,)):
            hr = ts[:13]
            if hr != cur:
                if cur and vals: rows[cur]["vtec_med"] = statistics.median(vals)
                cur, vals = hr, []
            vals.append(vtec_from_stec(stec, elev)); n += 1
        if cur and vals: rows[cur]["vtec_med"] = statistics.median(vals)
        c.close(); print(f"  vtec: ok ({n:,} obs streamed)")
    except Exception as e:
        print("  vtec: SKIPPED --", e)

def main():
    home = os.path.expanduser("~")
    p = argparse.ArgumentParser()
    p.add_argument("--starlink", default=f"{home}/starlink-logger/starlink_history.db")
    p.add_argument("--tec", default=f"{home}/gnss-logger/gnss_tec.db")
    p.add_argument("--roti", default=f"{home}/gnss-logger/roti.db")
    p.add_argument("--spaceweather", default=f"{home}/spaceweather-logger/spaceweather.db")
    p.add_argument("--mask", type=float, default=30.0)
    p.add_argument("--out", default=f"{home}/combined_full.csv")
    a = p.parse_args()
    rows = defaultdict(dict)
    print("Aggregating (streams the 2.4 GB TEC file, ~a few minutes):")
    agg_spaceweather(a.spaceweather, rows)
    agg_roti(a.roti, rows)
    agg_starlink(a.starlink, rows)
    agg_vtec(a.tec, rows, a.mask)
    cols = ["hour","kp","dst","bz_min","vsw_mean","vtec_med",
            "roti2nd_max","roti_med","sl_lat_ms","sl_drop","sl_dl_bps","sl_n"]
    with open(a.out, "w", newline="") as f:
        w = csv.writer(f); w.writerow(cols)
        for hr in sorted(rows):
            w.writerow([hr] + [rows[hr].get(c, "") for c in cols[1:]])
    print(f"\nWrote {a.out}  ({len(rows)} hourly rows) -- upload THIS one file.")

if __name__ == "__main__":
    main()
