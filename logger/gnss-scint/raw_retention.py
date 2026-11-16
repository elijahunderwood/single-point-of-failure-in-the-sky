#!/usr/bin/env python3
"""
Daily retention for the 20 Hz raw UBX hours in ~/gnss_raw.

A UTC day D older than KEEP_DAYS (7) is either
  * MOVED to ~/gnss_raw/keep/YYYY/MM/DD (with KEEP_REASON.txt) if
      - max Kp that day >= 4.67 (Kp 5-, i.e. G1 or stronger; spaceweather.db), or
      - an M or X class flare peaked that day (flare_logger/flare.db), or
      - it is the quiet control day of its ISO week (lowest daily max Kp in
        that Mon-Sun week, no M/X flare; one per week), or
      - Kp data for the day is missing (kept to be safe);
  * otherwise DELETED.
A day is only deleted/moved once all its hours are processed in scint.db
(or it is older than 14 days). Use --dry-run to see what would happen.
"""
import argparse, os, shutil, sqlite3, sys
from datetime import date, datetime, timedelta, timezone

HOME = os.path.expanduser("~")
RAW = os.path.join(HOME, "gnss_raw")
KEEP = os.path.join(RAW, "keep")
KP_DB = os.path.join(HOME, "spaceweather-logger", "spaceweather.db")
FL_DB = os.path.join(HOME, "flare_logger", "flare.db")
SC_DB = os.path.join(HOME, "gnss-scint", "scint.db")
KEEP_DAYS = 7
FORCE_DAYS = 14
KP_STORM = 4.67
START = date(2026, 10, 22)          # first day of 20 Hz raw data


def ro(path):
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)


def kp_max(d):
    with ro(KP_DB) as c:
        r = c.execute("SELECT MAX(kp), COUNT(*) FROM kp_index WHERE substr(ts_utc,1,10)=?",
                      (d.isoformat(),)).fetchone()
    return (r[0] if r and r[1] else None)


def mx_flares(d):
    with ro(FL_DB) as c:
        return [r[0] for r in c.execute(
            "SELECT class FROM flares WHERE substr(peak_utc,1,10)=? AND (class LIKE 'M%' OR class LIKE 'X%')",
            (d.isoformat(),))]


def control_day(d):
    mon = d - timedelta(days=d.weekday())
    best = None
    for i in range(7):
        x = mon + timedelta(days=i)
        if x < START or x >= datetime.now(timezone.utc).date():
            continue
        k = kp_max(x)
        if k is None or mx_flares(x):
            continue
        if best is None or k < best[1]:
            best = (x, k)
    return best[0] if best else None


def all_processed(d, ddir):
    hours = sorted(f[4:15] for f in os.listdir(ddir) if f.startswith("raw_"))
    if not hours:
        return True
    try:
        with ro(SC_DB) as c:
            ok = {r[0] for r in c.execute(
                "SELECT hour_utc FROM processed_files WHERE status IN ('ok','empty') AND hour_utc LIKE ?",
                (d.strftime("%Y%m%d") + "_%",))}
    except Exception:
        return False
    return all(h in ok for h in hours)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    today = datetime.now(timezone.utc).date()
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    tag = "DRY " if a.dry_run else ""
    for ydir in sorted(os.listdir(RAW)) if os.path.isdir(RAW) else []:
        if not ydir.isdigit():
            continue
        for mdir in sorted(os.listdir(os.path.join(RAW, ydir))):
            for ddir in sorted(os.listdir(os.path.join(RAW, ydir, mdir))):
                try:
                    d = date(int(ydir), int(mdir), int(ddir))
                except ValueError:
                    continue
                path = os.path.join(RAW, ydir, mdir, ddir)
                age = (today - d).days
                if age <= KEEP_DAYS:
                    continue
                if not all_processed(d, path) and age <= FORCE_DAYS:
                    print(f"[{stamp}] {tag}WAIT {d}: not all hours processed yet")
                    continue
                reasons = []
                k = kp_max(d)
                if k is None:
                    reasons.append("no Kp data (kept to be safe)")
                elif k >= KP_STORM:
                    reasons.append(f"max Kp {k}")
                fl = mx_flares(d)
                if fl:
                    reasons.append("flares " + ",".join(fl))
                if not reasons and control_day(d) == d:
                    reasons.append(f"quiet control day for ISO week {d.isocalendar()[1]} (max Kp {k})")
                size = sum(os.path.getsize(os.path.join(path, f)) for f in os.listdir(path)) / 1e9
                if reasons:
                    dest = os.path.join(KEEP, ydir, mdir, ddir)
                    print(f"[{stamp}] {tag}KEEP {d} ({size:.2f} GB): {'; '.join(reasons)}")
                    if not a.dry_run:
                        os.makedirs(os.path.dirname(dest), exist_ok=True)
                        shutil.move(path, dest)
                        with open(os.path.join(dest, "KEEP_REASON.txt"), "w") as fh:
                            fh.write(f"{stamp}: {'; '.join(reasons)}\n")
                else:
                    print(f"[{stamp}] {tag}DELETE {d} ({size:.2f} GB): max Kp {k}, no M/X flare")
                    if not a.dry_run:
                        shutil.rmtree(path)
            # tidy empty month/year dirs
            mp = os.path.join(RAW, ydir, mdir)
            if not a.dry_run and os.path.isdir(mp) and not os.listdir(mp):
                os.rmdir(mp)
    du = shutil.disk_usage(RAW) if os.path.isdir(RAW) else None
    if du:
        print(f"[{stamp}] {tag}done; disk free {du.free/1e9:.0f} GB")


if __name__ == "__main__":
    main()
