#!/usr/bin/env python3
"""
Eclipse TEC analysis
===================

Did the 2026-08-12 partial solar eclipse (~93% obscuration over Belfast,
maximum 18:08 UTC) depress the ionosphere's Total Electron Content?

Method
------
The ionosphere is produced by solar EUV; an eclipse switches most production
off on a known schedule, and published events show TEC dropping by tens of
percent, lagging maximum obscuration by tens of minutes (the plasma
recombination timescale).

For each evening in the record, slice a fixed UTC window into bins and take
the MEDIAN code TEC across all satellites above the elevation mask. Compare
the eclipse evening against the mean/std of the control evenings at the same
clock time. Because the GPS constellation geometry nearly repeats day to day,
same-time comparisons largely cancel satellite/receiver hardware biases (DCBs)
and the ordinary evening decline -- what remains is the eclipse.

Outputs a per-bin table, a depletion summary (magnitude + lag), a Kp check on
all involved days (geomagnetic confounder), and an optional CSV for plotting.
Standard library only; databases opened read-only.
"""

import argparse
import os
import sqlite3
import statistics
import sys

ECLIPSE_DAY = "2026-08-12"
T_START = "17:10"    # first contact, UTC
T_MAX = "18:08"      # maximum obscuration, UTC
T_END = "19:03"      # last contact, UTC
CONTROL_DAYS = ["2026-08-10", "2026-08-11", "2026-08-13", "2026-08-14",
                "2026-08-15", "2026-08-16"]


def ro(path):
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)


def hm_to_min(hm):
    h, m = hm.split(":")
    return int(h) * 60 + int(m)


def bin_label(day, minutes):
    return f"{day}T{minutes // 60:02d}:{minutes % 60:02d}"


def day_bins(conn, day, w0, w1, binm, mask):
    """day -> {bin_start_minutes: median code_tec} using per-(bin,sv) medians
    first, then the median across satellites (robust to unequal sample counts).
    """
    rows = conn.execute(
        "SELECT ts_utc, sv, code_tec FROM tec "
        "WHERE ts_utc >= ? AND ts_utc < ? AND elev_deg >= ? AND code_tec IS NOT NULL",
        (f"{day}T{w0 // 60:02d}:{w0 % 60:02d}", f"{day}T{w1 // 60:02d}:{w1 % 60:02d}",
         mask)).fetchall()
    per = {}
    for ts, sv, tec in rows:
        mins = int(ts[11:13]) * 60 + int(ts[14:16])
        b = (mins // binm) * binm
        per.setdefault(b, {}).setdefault(sv, []).append(tec)
    out = {}
    for b, svs in per.items():
        sv_meds = [statistics.median(v) for v in svs.values() if len(v) >= 3]
        if len(sv_meds) >= 3:                      # need a few satellites to be robust
            out[b] = statistics.median(sv_meds)
    return out


def kp_table(sw_path, days):
    out = {}
    if not sw_path or not os.path.exists(sw_path):
        return out
    with ro(sw_path) as c:
        for d in days:
            r = c.execute(
                "SELECT MAX(kp) FROM kp_index WHERE ts_utc >= ? AND ts_utc < ?",
                (f"{d}T12:00", f"{d}T21:00")).fetchone()
            out[d] = r[0]
    return out


def main():
    home = os.path.expanduser("~")
    p = argparse.ArgumentParser(description="Eclipse TEC depletion analysis.")
    p.add_argument("--db", default=f"{home}/gnss-logger/gnss_tec.db")
    p.add_argument("--spaceweather", default=f"{home}/spaceweather-logger/spaceweather.db")
    p.add_argument("--eclipse-day", default=ECLIPSE_DAY)
    p.add_argument("--controls", default=",".join(CONTROL_DAYS),
                   help="Comma-separated control days")
    p.add_argument("--window", default="15:30-21:00", help="UTC window to analyse")
    p.add_argument("--bin", type=int, default=10, help="Bin size, minutes")
    p.add_argument("--mask", type=float, default=30.0, help="Elevation mask, deg")
    p.add_argument("--csv", help="Optional CSV output path")
    args = p.parse_args()

    w0, w1 = (hm_to_min(x) for x in args.window.split("-"))
    controls = [d.strip() for d in args.controls.split(",") if d.strip()]
    tmax = hm_to_min(T_MAX)

    conn = ro(args.db)
    ecl = day_bins(conn, args.eclipse_day, w0, w1, args.bin, args.mask)
    ctl = {d: day_bins(conn, d, w0, w1, args.bin, args.mask) for d in controls}
    conn.close()

    ctl = {d: b for d, b in ctl.items() if b}      # drop empty control days
    if not ecl:
        print(f"No eclipse-day data found for {args.eclipse_day} in {args.window} UTC.")
        sys.exit(1)
    if len(ctl) < 2:
        print("Fewer than 2 usable control days -- results would be unreliable.")
        sys.exit(1)

    kp = kp_table(args.spaceweather, [args.eclipse_day] + list(ctl))

    # per-bin comparison
    bins = sorted(b for b in ecl if sum(b in c for c in ctl.values()) >= 2)
    table = []
    for b in bins:
        cvals = [c[b] for c in ctl.values() if b in c]
        cmean = statistics.mean(cvals)
        cstd = statistics.stdev(cvals) if len(cvals) >= 2 else float("nan")
        delta = ecl[b] - cmean
        pct = 100.0 * delta / cmean if cmean else float("nan")
        table.append((b, ecl[b], cmean, cstd, delta, pct, len(cvals)))

    print(f"Eclipse day {args.eclipse_day} vs {len(ctl)} control evenings "
          f"({', '.join(sorted(ctl))})")
    print(f"Window {args.window} UTC, {args.bin}-min bins, elev mask {args.mask:g} deg")
    print(f"Eclipse contacts: {T_START} - {T_MAX} (max) - {T_END} UTC\n")
    print(f"{'bin (UTC)':<12}{'eclipse':>9}{'ctl_mean':>10}{'ctl_std':>9}"
          f"{'delta':>8}{'pct':>8}{'n':>3}")
    for b, e, cm, cs, d, pc, n in table:
        mark = ""
        if hm_to_min(T_START) <= b <= hm_to_min(T_END):
            mark = "  <eclipse"
        elif b == (tmax // args.bin) * args.bin:
            mark = "  <max"
        print(f"{b // 60:02d}:{b % 60:02d}      {e:>9.2f}{cm:>10.2f}{cs:>9.2f}"
              f"{d:>8.2f}{pc:>7.1f}%{n:>3}{mark}")

    # depletion summary: deepest dip from first contact to +90 min after last contact
    hunt = [(b, d, pc) for b, e, cm, cs, d, pc, n in table
            if hm_to_min(T_START) <= b <= hm_to_min(T_END) + 90]
    if hunt:
        bmin, dmin, pmin = min(hunt, key=lambda r: r[1])
        lag = bmin - tmax
        pre = [pc for b, e, cm, cs, d, pc, n in table if b < hm_to_min(T_START)]
        pre_spread = statistics.stdev(pre) if len(pre) >= 2 else float("nan")
        print(f"\nDeepest deviation in eclipse+recovery window: {dmin:+.2f} TECU "
              f"({pmin:+.1f}%) at {bmin // 60:02d}:{bmin % 60:02d} UTC")
        print(f"Lag after maximum obscuration ({T_MAX}): {lag:+d} min")
        print(f"Pre-eclipse deviation spread (control agreement): {pre_spread:.1f}%")
        if pmin < -10 and abs(pmin) > 3 * (pre_spread if pre_spread == pre_spread else 3):
            print("=> Depletion well outside control variability: eclipse signature.")
        elif pmin < -5:
            print("=> Modest depletion; compare against pre-eclipse spread and Kp before claiming.")
        else:
            print("=> No clear depletion beyond control-day variability.")

    print("\nGeomagnetic confounder check (max Kp 12:00-21:00 UTC each day):")
    for d in sorted(kp):
        tag = "  <- ECLIPSE DAY" if d == args.eclipse_day else ""
        kv = kp[d]
        print(f"  {d}: Kp {kv if kv is not None else '?'}{tag}")
    stormy = [d for d, v in kp.items() if v is not None and v >= 4]
    if stormy:
        print(f"  NOTE: Kp>=4 on {', '.join(stormy)} -- treat those evenings with caution.")

    if args.csv:
        with open(args.csv, "w") as f:
            f.write("bin_utc,eclipse_tec,control_mean,control_std,delta,pct,n_controls\n")
            for b, e, cm, cs, d, pc, n in table:
                f.write(f"{bin_label(args.eclipse_day, b)},{e:.3f},{cm:.3f},{cs:.3f},"
                        f"{d:.3f},{pc:.2f},{n}\n")
        print(f"\nCSV written: {args.csv}")


if __name__ == "__main__":
    main()
