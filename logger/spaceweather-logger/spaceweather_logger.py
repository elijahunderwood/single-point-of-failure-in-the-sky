#!/usr/bin/env python3
"""
Space weather logger
====================

Fetches geomagnetic and solar-wind data from NOAA SWPC's public JSON feeds and
stores them in a SQLite database (spaceweather.db) with UTC timestamps in the
same ISO-8601 format the Starlink logger uses, so the two datasets join cleanly.

Sources (all free, no key):
  * Planetary Kp index  -- storm indicator; defines storm onsets        (3-hourly)
  * Kyoto Dst index     -- ring-current / storm main-phase intensity    (hourly)
  * Solar wind plasma   -- speed, density, temperature                  (~1 min)
  * Solar wind mag      -- IMF Bt and Bz (the coupling driver)          (~1 min)

Each feed returns a rolling window that overlaps previous fetches; every table is
keyed on the UTC timestamp with INSERT OR IGNORE, so repeated polls never
duplicate rows. Feeds are fetched independently -- one failing does not stop the
others. No third-party dependencies (standard-library urllib only).
"""

import argparse
import json
import signal
import sqlite3
import sys
import time
import urllib.request
from datetime import datetime, timezone

BASE = "https://services.swpc.noaa.gov"
FEEDS = {
    "kp":     f"{BASE}/products/noaa-planetary-k-index.json",
    "dst":    f"{BASE}/products/kyoto-dst.json",
    # NOTE: the old /products/solar-wind/ files were retired by NOAA (SWPC
    # service change, 2026). These RTSW endpoints are the replacements. They
    # return one record per spacecraft (ACE + DSCOVR) per minute, with an
    # "active" flag marking the operational one -- we keep only active rows.
    "plasma": f"{BASE}/json/rtsw/rtsw_wind_1m.json",
    "mag":    f"{BASE}/json/rtsw/rtsw_mag_1m.json",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS kp_index (
    ts_utc        TEXT PRIMARY KEY,   -- start of the 3-hour window (UTC)
    kp            REAL,               -- planetary Kp (0-9, fractional)
    a_running     REAL,
    station_count INTEGER
);
CREATE TABLE IF NOT EXISTS dst_index (
    ts_utc TEXT PRIMARY KEY,          -- hourly (UTC)
    dst    REAL                       -- nT (negative during storms)
);
CREATE TABLE IF NOT EXISTS solar_wind_plasma (
    ts_utc      TEXT PRIMARY KEY,     -- ~1 min (UTC)
    density     REAL,                 -- protons / cm^3
    speed_kms   REAL,                 -- bulk speed, km/s
    temperature REAL                  -- K
);
CREATE TABLE IF NOT EXISTS solar_wind_mag (
    ts_utc TEXT PRIMARY KEY,          -- ~1 min (UTC)
    bt     REAL,                      -- total IMF magnitude, nT
    bx_gsm REAL,
    by_gsm REAL,
    bz_gsm REAL                       -- north-south IMF (drives coupling), nT
);
CREATE TABLE IF NOT EXISTS fetch_log (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc   TEXT,
    source   TEXT,
    rows_new INTEGER,
    status   TEXT                     -- 'ok' or an error message
);
"""

_stop = False


def _handle_signal(signum, frame):
    global _stop
    _stop = True
    sys.stderr.write(f"\n[{_now_iso()}] signal {signum} received, shutting down...\n")


def _now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# ---------- parsing helpers ----------

def to_iso_utc(s):
    """Normalise SWPC time strings to whole-second ISO-8601 UTC (+00:00)."""
    s = str(s).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S.%f",
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.replace(tzinfo=timezone.utc, microsecond=0).isoformat()
        except ValueError:
            continue
    raise ValueError(f"unrecognised time format: {s!r}")


def num(v):
    """String/None -> float or None (handles 'null', '', already-numeric)."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    v = str(v).strip()
    if v == "" or v.lower() == "null":
        return None
    try:
        return float(v)
    except ValueError:
        return None


def records(data):
    """Yield dict rows from either shape SWPC uses:
       array-of-objects  -> yield each object
       array-of-arrays   -> first row is the header; zip it onto each data row.
    """
    if not data:
        return
    if isinstance(data[0], dict):
        yield from data
    else:
        header = data[0]
        for row in data[1:]:
            yield dict(zip(header, row))


def ci(d, *names):
    """Case-insensitive key lookup across candidate names."""
    lower = {k.lower(): v for k, v in d.items()}
    for n in names:
        if n.lower() in lower:
            return lower[n.lower()]
    return None


# ---------- per-feed extractors: dict -> column tuple (ts first) or None ----------

def extract_kp(r):
    t = ci(r, "time_tag")
    if t is None:
        return None
    return (to_iso_utc(t), num(ci(r, "Kp", "kp_index", "kp")),
            num(ci(r, "a_running")), num(ci(r, "station_count")))


def extract_dst(r):
    t = ci(r, "time_tag")
    if t is None:
        return None
    return (to_iso_utc(t), num(ci(r, "dst")))


def extract_plasma(r):
    if r.get("active") is not True:      # keep only the operational spacecraft
        return None
    t = ci(r, "time_tag")
    if t is None:
        return None
    return (to_iso_utc(t), num(ci(r, "proton_density", "density")),
            num(ci(r, "proton_speed", "speed")),
            num(ci(r, "proton_temperature", "temperature")))


def extract_mag(r):
    if r.get("active") is not True:      # keep only the operational spacecraft
        return None
    t = ci(r, "time_tag")
    if t is None:
        return None
    return (to_iso_utc(t), num(ci(r, "bt", "b")), num(ci(r, "bx_gsm")),
            num(ci(r, "by_gsm")), num(ci(r, "bz_gsm")))


SOURCES = [
    {"name": "kp",     "table": "kp_index",
     "columns": ["ts_utc", "kp", "a_running", "station_count"], "extract": extract_kp},
    {"name": "dst",    "table": "dst_index",
     "columns": ["ts_utc", "dst"], "extract": extract_dst},
    {"name": "plasma", "table": "solar_wind_plasma",
     "columns": ["ts_utc", "density", "speed_kms", "temperature"], "extract": extract_plasma},
    {"name": "mag",    "table": "solar_wind_mag",
     "columns": ["ts_utc", "bt", "bx_gsm", "by_gsm", "bz_gsm"], "extract": extract_mag},
]


# ---------- fetch + store ----------

def fetch_json(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "science-fair-spaceweather-logger/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def open_db(path):
    conn = sqlite3.connect(path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def store_source(conn, src, data):
    """Parse one feed's payload and insert new rows. Returns count of new rows."""
    rows = []
    for r in records(data):
        try:
            tup = src["extract"](r)
        except ValueError:
            continue                       # skip a row with an unparseable time
        if tup and tup[0] is not None:
            rows.append(tup)
    if not rows:
        return 0
    cols = ",".join(src["columns"])
    ph = ",".join("?" * len(src["columns"]))
    before = conn.total_changes
    conn.executemany(
        f"INSERT OR IGNORE INTO {src['table']} ({cols}) VALUES ({ph})", rows)
    conn.commit()
    return conn.total_changes - before      # rows actually inserted (dedup-aware)


def poll_once(conn, verbose=False):
    total_new = 0
    for src in SOURCES:
        try:
            data = fetch_json(FEEDS[src["name"]])
            n = store_source(conn, src, data)
            total_new += n
            conn.execute(
                "INSERT INTO fetch_log (ts_utc, source, rows_new, status) VALUES (?,?,?,?)",
                (_now_iso(), src["name"], n, "ok"))
            conn.commit()
            if verbose:
                sys.stderr.write(f"[{_now_iso()}] {src['name']}: +{n} new\n")
        except Exception as e:               # isolate each feed
            conn.execute(
                "INSERT INTO fetch_log (ts_utc, source, rows_new, status) VALUES (?,?,?,?)",
                (_now_iso(), src["name"], None, f"error: {e}"[:300]))
            conn.commit()
            sys.stderr.write(f"[{_now_iso()}] {src['name']} FAILED: {e}\n")
    return total_new


def main():
    p = argparse.ArgumentParser(description="Log NOAA SWPC space weather to SQLite.")
    p.add_argument("--db", default="spaceweather.db", help="SQLite file path")
    p.add_argument("--interval", type=int, default=900, help="Seconds between polls (loop mode)")
    p.add_argument("--once", action="store_true", help="Run a single poll then exit (cron mode)")
    p.add_argument("--verbose", action="store_true", help="Verbose output")
    args = p.parse_args()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    conn = open_db(args.db)

    def cycle():
        n = poll_once(conn, verbose=args.verbose)
        sys.stderr.write(f"[{_now_iso()}] cycle done: {n} new rows total\n")

    if args.once:
        cycle()
        conn.close()
        return

    sys.stderr.write(f"[{_now_iso()}] space weather logger started -> {args.db} "
                     f"(every {args.interval}s). Ctrl-C to stop.\n")
    while not _stop:
        cycle()
        for _ in range(args.interval):
            if _stop:
                break
            time.sleep(1)

    conn.close()
    sys.stderr.write(f"[{_now_iso()}] stopped.\n")


if __name__ == "__main__":
    main()
