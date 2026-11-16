#!/usr/bin/env python3
"""
METAR logger
===========

Fetches observed airport weather (METAR + SPECI) from the NOAA Aviation Weather
Center API and stores it in SQLite (metar.db) with UTC timestamps matching the
other loggers.

Why, alongside the Open-Meteo logger: METAR is a real *observation* (not a model)
and includes SPECI -- unscheduled reports issued when weather changes, e.g. rain
starting or stopping -- so it pins down rain *timing* better than hourly model
data. The trade-off: UK/ICAO METARs report rain qualitatively (present-weather
codes with an intensity flag), not a millimetre amount, and the station is some
miles from the dish. So this is a timing/observed cross-check to Open-Meteo's
quantitative record, not a replacement.

The full raw report is stored verbatim, so nothing is lost even if the light
parser below misses an exotic code -- you can always re-parse `raw` later.
No third-party dependencies (standard-library urllib only).
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

# Present-weather precipitation codes (after stripping intensity/descriptor).
PRECIP = {"RA", "DZ", "SN", "SG", "IC", "PL", "GR", "GS", "UP"}
LIQUID = {"RA", "DZ"}   # rain / drizzle (incl. SHRA, TSRA, FZRA via substring)

SCHEMA = """
CREATE TABLE IF NOT EXISTS metar (
    ts_utc        TEXT PRIMARY KEY,   -- observation time (UTC)
    icao          TEXT,
    report_type   TEXT,               -- METAR or SPECI
    raw           TEXT,               -- full raw report, verbatim
    wx_string     TEXT,               -- present-weather codes (e.g. '-RA BR')
    is_precip     INTEGER,            -- 1 if any precipitation present
    is_rain       INTEGER,            -- 1 if rain/drizzle (liquid)
    intensity     TEXT,               -- 'light' / 'moderate' / 'heavy' / NULL
    temp_c        REAL,
    dewpoint_c    REAL,
    wind_speed_kt REAL,
    wind_gust_kt  REAL,
    visibility    TEXT
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


_RANK = {"light": 1, "moderate": 2, "heavy": 3}


def parse_wx(wx):
    """Return (is_precip, is_rain, intensity) from a present-weather string."""
    if not wx:
        return (0, 0, None)
    is_precip = is_rain = 0
    best = None
    for tok in str(wx).split():
        t = tok
        inten = "moderate"
        if t.startswith("-"):
            inten, t = "light", t[1:]
        elif t.startswith("+"):
            inten, t = "heavy", t[1:]
        # t may still carry descriptors (SH, TS, FZ, MI...) plus the code, e.g. SHRA
        hit = None
        for code in PRECIP:
            if code in t:
                hit = code
                break
        if hit:
            is_precip = 1
            if hit in LIQUID:
                is_rain = 1
            if best is None or _RANK[inten] > _RANK[best]:
                best = inten
    return (is_precip, is_rain, best)


def to_iso_from_epoch(sec):
    return datetime.fromtimestamp(int(sec), tz=timezone.utc).replace(microsecond=0).isoformat()


def to_iso_generic(s):
    s = str(s).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc).isoformat()
        except ValueError:
            continue
    raise ValueError(f"unrecognised time: {s!r}")


def row_time(rec):
    """Prefer epoch obsTime; fall back to reportTime string."""
    if rec.get("obsTime") is not None:
        return to_iso_from_epoch(rec["obsTime"])
    for k in ("reportTime", "receiptTime"):
        if rec.get(k):
            return to_iso_generic(rec[k])
    raise ValueError("no usable timestamp")


def fetch_json(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "science-fair-metar-logger/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def build_url(icao, hours):
    q = urllib.parse.urlencode({"ids": icao, "format": "json", "hours": hours})
    return f"https://aviationweather.gov/api/data/metar?{q}"


def open_db(path):
    conn = sqlite3.connect(path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def report_type(rec):
    raw = (rec.get("rawOb") or "")
    return "SPECI" if raw.startswith("SPECI") or " SPECI " in raw[:12] else "METAR"


def store(conn, data):
    if not isinstance(data, list):
        return 0
    rows = []
    for rec in data:
        try:
            ts = row_time(rec)
        except ValueError:
            continue
        wx = rec.get("wxString")
        is_p, is_r, inten = parse_wx(wx)
        rows.append((
            ts, rec.get("icaoId"), report_type(rec), rec.get("rawOb"), wx,
            is_p, is_r, inten,
            num(rec.get("temp")), num(rec.get("dewp")),
            num(rec.get("wspd")), num(rec.get("wgst")),
            (str(rec["visib"]) if rec.get("visib") is not None else None),
        ))
    if not rows:
        return 0
    before = conn.total_changes
    conn.executemany(
        "INSERT OR IGNORE INTO metar "
        "(ts_utc, icao, report_type, raw, wx_string, is_precip, is_rain, intensity, "
        " temp_c, dewpoint_c, wind_speed_kt, wind_gust_kt, visibility) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    return conn.total_changes - before


def poll_once(conn, icao, hours, verbose=False):
    try:
        data = fetch_json(build_url(icao, hours))
        n = store(conn, data)
        conn.execute("INSERT INTO fetch_log (ts_utc, rows_new, status) VALUES (?,?,?)",
                     (_now_iso(), n, "ok"))
        conn.commit()
        if verbose:
            sys.stderr.write(f"[{_now_iso()}] {icao}: +{n} new\n")
        return n
    except Exception as e:
        conn.execute("INSERT INTO fetch_log (ts_utc, rows_new, status) VALUES (?,?,?)",
                     (_now_iso(), None, f"error: {e}"[:300]))
        conn.commit()
        sys.stderr.write(f"[{_now_iso()}] FAILED: {e}\n")
        return 0


def main():
    p = argparse.ArgumentParser(description="Log airport METAR/SPECI to SQLite.")
    p.add_argument("--icao", default="EGAA", help="Airport ICAO code (default EGAA, Belfast Intl)")
    p.add_argument("--db", default="metar.db", help="SQLite file path")
    p.add_argument("--hours", type=float, default=6, help="Hours of history to fetch each poll")
    p.add_argument("--interval", type=int, default=900, help="Seconds between polls (loop mode)")
    p.add_argument("--once", action="store_true", help="Run a single poll then exit")
    p.add_argument("--verbose", action="store_true", help="Verbose output")
    args = p.parse_args()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    conn = open_db(args.db)

    if args.once:
        poll_once(conn, args.icao, args.hours, verbose=args.verbose)
        conn.close()
        return

    sys.stderr.write(f"[{_now_iso()}] METAR logger started -> {args.db} "
                     f"({args.icao}) every {args.interval}s. Ctrl-C to stop.\n")
    while not _stop:
        poll_once(conn, args.icao, args.hours, verbose=args.verbose)
        for _ in range(args.interval):
            if _stop:
                break
            time.sleep(1)

    conn.close()
    sys.stderr.write(f"[{_now_iso()}] stopped.\n")


if __name__ == "__main__":
    main()
