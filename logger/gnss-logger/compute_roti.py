#!/usr/bin/env python3
"""
ROTI analysis
============

Reads the GNSS logger's `tec` table and computes the Rate of TEC Index (ROTI) --
the scintillation proxy you correlate against Starlink link quality and space
weather.

Method (standard):
  ROT_i  = (phase_TEC_i - phase_TEC_{i-1}) / dt   [TECU/min]   per satellite,
           only between consecutive epochs WITHIN one continuous phase-lock arc
           (never across a cycle slip -- that's what the `slip` flag guards).
  ROTI   = standard deviation of ROT over a 5-minute window, per satellite.

Uses the smooth `phase_tec` (its per-arc constant offset cancels in the
difference) and `rcv_tow` for a precise dt. Low-elevation observations are
dropped (multipath). Results go to a separate roti.db so the live logger is
undisturbed; join it to the other databases on the window timestamp.

Standard library only -- runs on the Pi, reads the live DB safely (WAL).
"""

import argparse
import math
import sqlite3
import statistics
import sys
from datetime import datetime, timedelta, timezone

OUT_SCHEMA = """
DROP TABLE IF EXISTS roti;
DROP TABLE IF EXISTS roti_network;
CREATE TABLE roti (
    window_start TEXT NOT NULL,     -- 5-min window start (UTC)
    sv           INTEGER NOT NULL,  -- GPS PRN
    roti         REAL,              -- std dev of ROT in the window, TECU/min
    n_samples    INTEGER,
    mean_elev    REAL,
    PRIMARY KEY (window_start, sv)
);
CREATE TABLE roti_network (
    window_start TEXT PRIMARY KEY,  -- 5-min window start (UTC)
    roti_max     REAL,              -- worst satellite (fragile: one bad sat inflates it)
    roti_2nd     REAL,              -- second-worst satellite (robust: needs >=2 sats to agree)
    roti_med     REAL,              -- median across satellites
    roti_mean    REAL,              -- mean across satellites
    n_sats       INTEGER
);
"""


def floor_window(ts_iso, minutes):
    dt = datetime.fromisoformat(ts_iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    floored = dt - timedelta(minutes=dt.minute % minutes,
                             seconds=dt.second, microseconds=dt.microsecond)
    return floored.isoformat(timespec="seconds")


def compute_rot(conn, mask_deg, max_gap_s, interval_s):
    """Yield (ts_utc, sv, rot, elev) for valid in-arc pairs ~interval_s apart.

    ROT is computed over interval_s (standard: 30 s, Pi et al. 1997), not per
    epoch: differencing 1-s phase amplifies mm-level measurement noise into a
    ~3 TECU/min false floor; a 30-s base shrinks it ~30x while real ionospheric
    rates are unaffected.
    """
    cur = conn.execute(
        "SELECT sv, id, rcv_tow, ts_utc, phase_tec, slip, elev_deg "
        "FROM tec ORDER BY sv, id")
    prev = None
    prev_sv = None
    for sv, _id, tow, ts, phase, slip, elev in cur:
        if sv != prev_sv:
            prev, prev_sv = None, sv           # new satellite
        if slip == 1 or phase is None or tow is None:
            prev = (tow, phase)                # arc break: reset baseline, no ROT
            continue
        if prev is None or prev[0] is None:
            prev = (tow, phase)
            continue
        dt = tow - prev[0]
        if dt < interval_s:
            continue                           # not yet a full interval: keep waiting
        if dt <= max_gap_s:
            if elev is not None and elev >= mask_deg:
                rot = (phase - prev[1]) / dt * 60.0
                yield (ts, sv, rot, elev)
        prev = (tow, phase)                    # advance the interval baseline


def main():
    p = argparse.ArgumentParser(description="Compute ROTI from the GNSS TEC log.")
    p.add_argument("--db", default="gnss_tec.db", help="Input GNSS TEC database")
    p.add_argument("--out", default="roti.db", help="Output ROTI database")
    p.add_argument("--mask", type=float, default=20.0, help="Elevation mask, degrees")
    p.add_argument("--window", type=int, default=5, help="ROTI window, minutes")
    p.add_argument("--rot-interval", type=float, default=30.0,
                   help="Interval (s) over which ROT is computed (standard: 30)")
    p.add_argument("--min-samples", type=int, default=5,
                   help="Min ROT samples per window to compute ROTI "
                        "(a 5-min window holds ~10 samples at 30-s ROT)")
    p.add_argument("--max-gap", type=float, default=90.0,
                   help="Max interval (s) before treating as an arc break")
    p.add_argument("--flag", type=float, default=0.5,
                   help="ROTI threshold (TECU/min) to flag as disturbed")
    p.add_argument("--rot-max", type=float, default=10.0,
                   help="Reject |ROT| above this (TECU/min) as a cycle slip. Real "
                        "ionospheric ROT stays well under this; the smallest cycle "
                        "slip is ~100, so this cleanly removes slip artifacts.")
    p.add_argument("--csv", help="Optional path to write the network ROTI time series")
    args = p.parse_args()

    src = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True, timeout=30)

    total = src.execute("SELECT COUNT(*) FROM tec").fetchone()[0]
    if total == 0:
        print("No TEC data yet -- let the logger run a while, then re-run.")
        return
    tmin, tmax = src.execute("SELECT MIN(ts_utc), MAX(ts_utc) FROM tec").fetchone()

    # bucket ROT samples by (window, sv), rejecting cycle-slip outliers
    buckets = {}   # (window, sv) -> ([rot...], [elev...])
    n_rot = 0
    n_slip = 0
    for ts, sv, rot, elev in compute_rot(src, args.mask, args.max_gap, args.rot_interval):
        if abs(rot) > args.rot_max:
            n_slip += 1                       # cycle-slip artifact -> discard
            continue
        w = floor_window(ts, args.window)
        b = buckets.setdefault((w, sv), ([], []))
        b[0].append(rot)
        b[1].append(elev)
        n_rot += 1
    src.close()

    # per-(window,sv) ROTI
    per_sv = []
    for (w, sv), (rots, elevs) in buckets.items():
        if len(rots) >= args.min_samples:
            per_sv.append((w, sv, statistics.stdev(rots), len(rots),
                           sum(elevs) / len(elevs)))

    # network aggregation per window
    net = {}
    for w, sv, roti, n, me in per_sv:
        net.setdefault(w, []).append(roti)
    net_rows = []
    for w, v in net.items():
        vs = sorted(v, reverse=True)
        second = vs[1] if len(vs) >= 2 else None
        net_rows.append((w, vs[0], second, statistics.median(vs),
                         sum(vs) / len(vs), len(vs)))

    # write results
    out = sqlite3.connect(args.out, timeout=30)
    out.executescript(OUT_SCHEMA)
    out.executemany(
        "INSERT INTO roti (window_start, sv, roti, n_samples, mean_elev) VALUES (?,?,?,?,?)",
        per_sv)
    out.executemany(
        "INSERT INTO roti_network (window_start, roti_max, roti_2nd, roti_med, "
        "roti_mean, n_sats) VALUES (?,?,?,?,?,?)",
        net_rows)
    out.commit()
    out.close()

    # optional CSV of the network time series
    if args.csv:
        with open(args.csv, "w") as f:
            f.write("window_start,roti_max,roti_2nd,roti_med,roti_mean,n_sats\n")
            for w, mx, s2, md, mn, ns in sorted(net_rows):
                s2s = f"{s2:.4f}" if s2 is not None else ""
                f.write(f"{w},{mx:.4f},{s2s},{md:.4f},{mn:.4f},{ns}\n")

    # summary
    print(f"TEC rows analysed : {total:,}")
    print(f"Time span         : {tmin}  ->  {tmax}")
    kept_pct = 100.0 * n_slip / (n_rot + n_slip) if (n_rot + n_slip) else 0.0
    print(f"ROT samples (masked >= {args.mask:g} deg): {n_rot:,}")
    print(f"Rejected as cycle slips (|ROT| > {args.rot_max:g}): {n_slip:,} ({kept_pct:.1f}%)")
    print(f"{args.window}-min windows with ROTI (per-sat): {len(per_sv):,}")
    print(f"Network windows   : {len(net_rows):,}")
    if net_rows:
        med_max = statistics.median([r[1] for r in net_rows])
        seconds = [r[2] for r in net_rows if r[2] is not None]
        med_2nd = statistics.median(seconds) if seconds else float("nan")
        flagged_max = sum(1 for r in net_rows if r[1] >= args.flag)
        flagged_net = sum(1 for r in net_rows if r[2] is not None and r[2] >= args.flag)
        peak = max(net_rows, key=lambda r: (r[2] if r[2] is not None else 0.0))
        print(f"Median ROTI_max   : {med_max:.3f} TECU/min   (fragile single-sat index)")
        print(f"Median ROTI_2nd   : {med_2nd:.3f} TECU/min   (robust network index)")
        print(f"Windows with 1 sat elevated  (max >= {args.flag}): {flagged_max}")
        print(f"Windows with >=2 sats elevated (2nd >= {args.flag}): {flagged_net}  <- disturbed")
        if peak[2] is not None:
            print(f"Peak network (2nd-highest) : {peak[2]:.3f} TECU/min at {peak[0]} "
                  f"({peak[5]} sats)")
        if flagged_net == 0:
            print("  -> no network-wide disturbance: single-sat flags above are local")
            print("     artifacts (multipath / residual slips), not ionosphere.")
    else:
        print("Not enough per-window samples yet -- try a lower --min-samples or wait.")


if __name__ == "__main__":
    main()
