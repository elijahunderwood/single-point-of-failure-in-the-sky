#!/usr/bin/env python3
"""High-resolution multi-source slice for ONE time window (for detailed timelines).
Pulls space weather, VTEC, ROTI and Starlink, binned to --bin minutes, for --start..--end.
Standard library only; DBs opened read-only; TEC streamed."""
import argparse, csv, math, os, sqlite3, statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone

RE, H = 6371.0, 350.0
def ro(p): return sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=60)
def vtec(stec, elev):
    z = math.radians(90 - elev); s = RE*math.sin(z)/(RE+H)
    return stec*math.sqrt(max(0.0, 1 - s*s))
def binlab(ts, b):
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
    f = dt - timedelta(minutes=dt.minute % b, seconds=dt.second, microseconds=dt.microsecond)
    return f.isoformat(timespec="minutes")

def main():
    home = os.path.expanduser("~")
    p = argparse.ArgumentParser()
    p.add_argument("--start", required=True); p.add_argument("--end", required=True)
    p.add_argument("--bin", type=int, default=5); p.add_argument("--mask", type=float, default=30.0)
    p.add_argument("--out", required=True)
    p.add_argument("--starlink", default=f"{home}/starlink-logger/starlink_history.db")
    p.add_argument("--tec", default=f"{home}/gnss-logger/gnss_tec.db")
    p.add_argument("--roti", default=f"{home}/gnss-logger/roti.db")
    p.add_argument("--sw", default=f"{home}/spaceweather-logger/spaceweather.db")
    a = p.parse_args()
    lo, hi = a.start[:16], a.end[:16]
    W = "substr(%s,1,16)>=? AND substr(%s,1,16)<=?"
    rows = defaultdict(dict)

    c = ro(a.sw)
    for ts, kp in c.execute(f"SELECT ts_utc,kp FROM kp_index WHERE {W%('ts_utc','ts_utc')}", (lo,hi)):
        rows[binlab(ts,a.bin)]["kp"] = kp
    for ts, d in c.execute(f"SELECT ts_utc,dst FROM dst_index WHERE {W%('ts_utc','ts_utc')}", (lo,hi)):
        rows[binlab(ts,a.bin)]["dst"] = d
    bz, vs = defaultdict(list), defaultdict(list)
    for ts, b in c.execute(f"SELECT ts_utc,bz_gsm FROM solar_wind_mag WHERE {W%('ts_utc','ts_utc')}", (lo,hi)):
        if b is not None and b > -9998: bz[binlab(ts,a.bin)].append(b)
    for ts, v in c.execute(f"SELECT ts_utc,speed_kms FROM solar_wind_plasma WHERE {W%('ts_utc','ts_utc')}", (lo,hi)):
        if v is not None and 100 < v < 1500: vs[binlab(ts,a.bin)].append(v)
    c.close()
    for k,v in bz.items(): rows[k]["bz_min"] = min(v)
    for k,v in vs.items(): rows[k]["vsw"] = statistics.mean(v)

    c = ro(a.roti); rr = defaultdict(list)
    for ts, r2 in c.execute(f"SELECT window_start,roti_2nd FROM roti_network WHERE {W%('window_start','window_start')}", (lo,hi)):
        if r2 is not None: rr[binlab(ts,a.bin)].append(r2)
    c.close()
    for k,v in rr.items(): rows[k]["roti2nd"] = max(v)

    c = ro(a.starlink); lat, drp = defaultdict(list), defaultdict(list)
    for ts, l, d in c.execute(f"SELECT ts_utc,ping_latency_ms,ping_drop_rate FROM history WHERE {W%('ts_utc','ts_utc')}", (lo,hi)):
        k = binlab(ts,a.bin)
        if l is not None: lat[k].append(l)
        if d is not None: drp[k].append(d)
    c.close()
    for k,v in lat.items(): rows[k]["sl_lat_ms"] = statistics.mean(v)
    for k,v in drp.items(): rows[k]["sl_drop"] = statistics.mean(v)

    c = ro(a.tec); vt = defaultdict(list); n=0
    for ts, elev, stec in c.execute(f"SELECT ts_utc,elev_deg,code_tec FROM tec WHERE {W%('ts_utc','ts_utc')} AND elev_deg>=? AND code_tec IS NOT NULL", (lo,hi,a.mask)):
        if elev is not None: vt[binlab(ts,a.bin)].append(vtec(stec,elev)); n+=1
    c.close()
    for k,v in vt.items():
        if v: rows[k]["vtec_med"] = statistics.median(v)

    cols = ["bin","kp","dst","bz_min","vsw","vtec_med","roti2nd","sl_lat_ms","sl_drop"]
    with open(a.out,"w",newline="") as f:
        w = csv.writer(f); w.writerow(cols)
        for k in sorted(rows): w.writerow([k]+[rows[k].get(c,"") for c in cols[1:]])
    print(f"Wrote {a.out}: {len(rows)} bins at {a.bin}-min ({n:,} TEC obs) for {a.start}..{a.end}")

if __name__ == "__main__": main()
