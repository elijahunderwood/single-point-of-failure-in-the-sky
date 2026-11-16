#!/usr/bin/env python3
"""
Eclipse TEC analysis, per-satellite differential
================================================

Sharpened version: rather than comparing the across-satellite median between
days (noisy, because the satellite set changes and each satellite carries a
large constant hardware bias), difference EACH SATELLITE AGAINST ITSELF at the
same clock time across days. The GPS constellation geometry nearly repeats
daily, so SV7-at-18:00 on eclipse day vs SV7-at-18:00 on control days shares
satellite, receiver, and geometry -- the biases cancel exactly, leaving only
what differed about the day.

Significance is empirical: the identical leave-one-out procedure is applied to
every control day, yielding the distribution of "deltas a perfectly ordinary
evening produces through this method." The eclipse curve is then judged
against that null band -- no assumed statistics, just the data's own spread.

Standard library only; database opened read-only.
"""

import argparse
import os
import sqlite3
import statistics
import sys

ECLIPSE_DAY = "2026-08-12"
T_START, T_MAX, T_END = "17:10", "18:08", "19:03"      # UTC contacts
CONTROL_DAYS = ["2026-08-10", "2026-08-11", "2026-08-13", "2026-08-14",
                "2026-08-15", "2026-08-16"]


def ro(path):
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)


def hm(s):
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def load_day(conn, day, w0, w1, binm, mask):
    """day -> {(bin_minutes, sv): median code_tec}"""
    rows = conn.execute(
        "SELECT ts_utc, sv, code_tec FROM tec "
        "WHERE ts_utc >= ? AND ts_utc < ? AND elev_deg >= ? AND code_tec IS NOT NULL",
        (f"{day}T{w0 // 60:02d}:{w0 % 60:02d}",
         f"{day}T{w1 // 60:02d}:{w1 % 60:02d}", mask)).fetchall()
    acc = {}
    for ts, sv, tec in rows:
        mins = int(ts[11:13]) * 60 + int(ts[14:16])
        acc.setdefault(((mins // binm) * binm, sv), []).append(tec)
    return {k: statistics.median(v) for k, v in acc.items() if len(v) >= 3}


def day_delta(day_data, ref_days, min_ref=2):
    """Per-bin mean of per-satellite (day - mean(refs)) deltas.
    Returns {bin: (delta_mean, n_sats)}."""
    out = {}
    bins = sorted({b for (b, _sv) in day_data})
    for b in bins:
        svs = [sv for (bb, sv) in day_data if bb == b]
        deltas = []
        for sv in svs:
            refs = [r[(b, sv)] for r in ref_days if (b, sv) in r]
            if len(refs) >= min_ref:
                deltas.append(day_data[(b, sv)] - statistics.mean(refs))
        if len(deltas) >= 3:
            out[b] = (statistics.mean(deltas), len(deltas))
    return out


def main():
    home = os.path.expanduser("~")
    p = argparse.ArgumentParser(description="Per-satellite differential eclipse analysis.")
    p.add_argument("--db", default=f"{home}/gnss-logger/gnss_tec.db")
    p.add_argument("--eclipse-day", default=ECLIPSE_DAY)
    p.add_argument("--controls", default=",".join(CONTROL_DAYS))
    p.add_argument("--window", default="15:30-21:00")
    p.add_argument("--bin", type=int, default=10)
    p.add_argument("--mask", type=float, default=30.0)
    p.add_argument("--csv", help="Optional CSV output path")
    args = p.parse_args()

    w0, w1 = (hm(x) for x in args.window.split("-"))
    controls = [d.strip() for d in args.controls.split(",") if d.strip()]
    tmax = hm(T_MAX)

    conn = ro(args.db)
    ecl = load_day(conn, args.eclipse_day, w0, w1, args.bin, args.mask)
    ctl = {d: load_day(conn, d, w0, w1, args.bin, args.mask) for d in controls}
    conn.close()
    ctl = {d: v for d, v in ctl.items() if v}
    if not ecl or len(ctl) < 3:
        print("Not enough data (need the eclipse day and >=3 control days).")
        sys.exit(1)

    # eclipse deltas vs all controls
    e_delta = day_delta(ecl, list(ctl.values()))

    # null band: each control day vs the OTHER controls (leave-one-out)
    null = {}
    for d, data in ctl.items():
        others = [v for dd, v in ctl.items() if dd != d]
        null[d] = day_delta(data, others)

    bins = sorted(b for b in e_delta
                  if sum(b in nd for nd in null.values()) >= 3)

    print(f"Per-satellite differential: {args.eclipse_day} vs "
          f"{len(ctl)} controls ({', '.join(sorted(ctl))})")
    print(f"Window {args.window} UTC, {args.bin}-min bins, mask {args.mask:g} deg")
    print(f"Contacts {T_START} - {T_MAX} (max) - {T_END} UTC\n")
    print(f"{'bin':<7}{'eclipse_d':>10}{'null_mean':>10}{'null_std':>9}{'z':>6}{'sats':>5}")

    rows_out = []
    for b in bins:
        ed, ns = e_delta[b]
        nvals = [nd[b][0] for nd in null.values() if b in nd]
        nm = statistics.mean(nvals)
        nstd = statistics.stdev(nvals) if len(nvals) >= 2 else float("nan")
        z = (ed - nm) / nstd if nstd and nstd == nstd and nstd > 0 else float("nan")
        mark = ""
        if hm(T_START) <= b <= hm(T_END):
            mark = "  <eclipse" + ("+max" if b == (tmax // args.bin) * args.bin else "")
        print(f"{b // 60:02d}:{b % 60:02d}  {ed:>10.2f}{nm:>10.2f}{nstd:>9.2f}"
              f"{z:>6.1f}{ns:>5}{mark}")
        rows_out.append((b, ed, nm, nstd, z, ns))

    # verdict: deepest eclipse delta between first contact and +90 min after end
    hunt = [(b, ed, z) for b, ed, nm, nstd, z, ns in rows_out
            if hm(T_START) <= b <= hm(T_END) + 90]
    pre = [ed for b, ed, nm, nstd, z, ns in rows_out if b < hm(T_START)]
    if hunt:
        bmin, dmin, zmin = min(hunt, key=lambda r: r[1])
        in_ecl = [z for b, ed, z in hunt if z == z]
        deep_bins = sum(1 for _b, _ed, z in hunt if z == z and z <= -2)
        print(f"\nDeepest eclipse-window delta: {dmin:+.2f} TECU at "
              f"{bmin // 60:02d}:{bmin % 60:02d} UTC (z = {zmin:+.1f})")
        print(f"Lag after maximum obscuration: {bmin - tmax:+d} min")
        print(f"Pre-eclipse mean delta: {statistics.mean(pre):+.2f} TECU"
              if pre else "")
        print(f"Bins in eclipse+recovery with z <= -2: {deep_bins} of {len(hunt)}")
        if zmin <= -3 and deep_bins >= 3:
            print("=> DETECTION: sustained depletion far outside the ordinary-day band.")
        elif zmin <= -2 and deep_bins >= 2:
            print("=> Probable depletion: repeatedly outside the ordinary-day band;")
            print("   state with the z-scores rather than as certainty.")
        else:
            print("=> No depletion distinguishable from ordinary day-to-day variability.")

    if args.csv:
        with open(args.csv, "w") as f:
            f.write("bin_utc,eclipse_delta,null_mean,null_std,z,n_sats\n")
            for b, ed, nm, nstd, z, ns in rows_out:
                f.write(f"{args.eclipse_day}T{b // 60:02d}:{b % 60:02d},"
                        f"{ed:.3f},{nm:.3f},{nstd:.3f},{z:.2f},{ns}\n")
        print(f"\nCSV written: {args.csv}")


if __name__ == "__main__":
    main()
