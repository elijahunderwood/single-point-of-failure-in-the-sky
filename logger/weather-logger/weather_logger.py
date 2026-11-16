#!/usr/bin/env python3
"""
Local weather logger
===================

Fetches local weather (especially precipitation) from the Open-Meteo API and
stores it in SQLite (localweather.db) with UTC timestamps matching the Starlink
and space-weather loggers, so all three join cleanly.

Why this matters: Starlink's Ku-band link suffers rain fade. Without a local
rainfall record you cannot separate a space-weather dip from an ordinary rain
dip. This logger is your confounder control.

Source: Open-Meteo forecast API -- free, no key, CC-BY 4.0. Note that native
15-minute precipitation exists only for Central Europe and North America; for
other regions (e.g. the UK) the real model resolution is HOURLY, so that is what
this logs as the authoritative record, plus a current-conditions snapshot each
poll. No third-party dependencies (standard-library urllib only).
"""

import argparse
import json
import signal
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

# Open-Meteo variable name -> our column name
HOURLY_VARS = [
    ("temperature_2m", "temperature_c"),
    ("relative_humidity_2m", "humidity_pct"),
    ("precipitation", "precipitation_mm"),
    ("rain", "rain_mm"),
    ("cloud_cover", "cloud_cover_pct"),
    ("wind_speed_10m", "wind_speed_kmh"),
    ("wind_gusts_10m", "wind_gusts_kmh"),
]
CURRENT_VARS = HOURLY_VARS + [("weather_code", "weather_code"), ("is_day", "is_day")]

SCHEMA = """
CREATE TABLE IF NOT EXISTS weather_hourly (
    ts_utc           TEXT PRIMARY KEY,   -- top of the hour (UTC); authoritative
    temperature_c    REAL,
    humidity_pct     REAL,
    precipitation_mm REAL,               -- total precip that hour (rain fade driver)
    rain_mm          REAL,
    cloud_cover_pct  REAL,
    wind_speed_kmh   REAL,
    wind_gusts_kmh   REAL
);
CREATE TABLE IF NOT EXISTS weather_current (
    ts_utc           TEXT PRIMARY KEY,   -- Open-Meteo 'current' time (UTC), ~15 min
    temperature_c    REAL,
    humidity_pct     REAL,
    precipitation_mm REAL,
    rain_mm          REAL,
    cloud_cover_pct  REAL,
    wind_speed_kmh   REAL,
    wind_gusts_kmh   REAL,
    weather_code     INTEGER,
    is_day           INTEGER
);
CREATE TABLE IF NOT EXISTS fetch_log (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc   TEXT,
    rows_new INTEGER,
    status   TEXT
);
"""

_stop = False


def _handle_signal(signum, frame):
    global _stop
    _stop = True
    sys.stderr.write(f"\n[{_now_iso()}] signal {signum} received, shutting down...\n")


def _now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def to_iso_utc(s):
    """Normalise Open-Meteo time strings (UTC) to whole-second ISO-8601 +00:00."""
    s = str(s).strip()
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.replace(tzinfo=timezone.utc).isoformat()
        except ValueError:
            continue
    raise ValueError(f"unrecognised time format: {s!r}")


def num(v):
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


def build_url(lat, lon):
    hourly = ",".join(v for v, _ in HOURLY_VARS)
    current = ",".join(v for v, _ in CURRENT_VARS)
    q = urllib.parse.urlencode({
        "latitude": lat, "longitude": lon,
        "hourly": hourly, "current": current,
        "past_days": 2, "forecast_days": 1, "timezone": "UTC",
    })
    return f"https://api.open-meteo.com/v1/forecast?{q}"


def fetch_json(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "science-fair-weather-logger/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def open_db(path):
    conn = sqlite3.connect(path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def store_hourly(conn, data):
    h = data.get("hourly") or {}
    times = h.get("time") or []
    rows = []
    for i, t in enumerate(times):
        row = [to_iso_utc(t)]
        for var, _col in HOURLY_VARS:
            arr = h.get(var)
            row.append(num(arr[i]) if arr is not None and i < len(arr) else None)
        rows.append(tuple(row))
    if not rows:
        return 0
    cols = "ts_utc," + ",".join(c for _, c in HOURLY_VARS)
    ph = ",".join("?" * (1 + len(HOURLY_VARS)))
    before = conn.total_changes
    conn.executemany(f"INSERT OR IGNORE INTO weather_hourly ({cols}) VALUES ({ph})", rows)
    return conn.total_changes - before


def store_current(conn, data):
    c = data.get("current")
    if not c or "time" not in c:
        return 0
    row = [to_iso_utc(c["time"])]
    for var, _col in CURRENT_VARS:
        row.append(num(c.get(var)))
    cols = "ts_utc," + ",".join(col for _, col in CURRENT_VARS)
    ph = ",".join("?" * (1 + len(CURRENT_VARS)))
    before = conn.total_changes
    conn.execute(f"INSERT OR IGNORE INTO weather_current ({cols}) VALUES ({ph})", row)
    return conn.total_changes - before


def poll_once(conn, lat, lon, verbose=False):
    try:
        data = fetch_json(build_url(lat, lon))
        n = store_hourly(conn, data) + store_current(conn, data)
        conn.execute("INSERT INTO fetch_log (ts_utc, rows_new, status) VALUES (?,?,?)",
                     (_now_iso(), n, "ok"))
        conn.commit()
        if verbose:
            sys.stderr.write(f"[{_now_iso()}] +{n} new rows\n")
        return n
    except Exception as e:
        conn.execute("INSERT INTO fetch_log (ts_utc, rows_new, status) VALUES (?,?,?)",
                     (_now_iso(), None, f"error: {e}"[:300]))
        conn.commit()
        sys.stderr.write(f"[{_now_iso()}] FAILED: {e}\n")
        return 0


def main():
    p = argparse.ArgumentParser(description="Log local weather (Open-Meteo) to SQLite.")
    p.add_argument("--lat", type=float, required=True, help="Latitude of your dish (WGS84)")
    p.add_argument("--lon", type=float, required=True, help="Longitude of your dish (WGS84)")
    p.add_argument("--db", default="localweather.db", help="SQLite file path")
    p.add_argument("--interval", type=int, default=900, help="Seconds between polls (loop mode)")
    p.add_argument("--once", action="store_true", help="Run a single poll then exit (cron mode)")
    p.add_argument("--verbose", action="store_true", help="Verbose output")
    args = p.parse_args()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    conn = open_db(args.db)

    if args.once:
        poll_once(conn, args.lat, args.lon, verbose=args.verbose)
        conn.close()
        return

    sys.stderr.write(f"[{_now_iso()}] weather logger started -> {args.db} "
                     f"@ ({args.lat},{args.lon}) every {args.interval}s. Ctrl-C to stop.\n")
    while not _stop:
        poll_once(conn, args.lat, args.lon, verbose=args.verbose)
        for _ in range(args.interval):
            if _stop:
                break
            time.sleep(1)

    conn.close()
    sys.stderr.write(f"[{_now_iso()}] stopped.\n")


if __name__ == "__main__":
    main()
