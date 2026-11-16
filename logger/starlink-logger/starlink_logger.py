#!/usr/bin/env python3
"""
Starlink history logger
=======================

Polls the LEO satellite broadband dish's local gRPC endpoint (host from DISH_GRPC_HOST, typical port 9200) and stores
its per-second performance history in a SQLite database, with UTC timestamps
aligned for later correlation against GNSS/ionosphere data and space-weather
indices.

Design notes
------------
* The dish keeps a rolling ring buffer of ~hours of per-second samples. Each
  sample has a monotonic "counter". We resume from the last counter we stored,
  so polling every few minutes captures every second with no gaps and no
  duplicates.
* The counter RESETS TO 0 when the dish reboots. We therefore key the history
  table on the UTC timestamp (which always advances), not the counter, and use
  INSERT OR IGNORE. The resume point is read from the last successful poll's
  end_counter; the underlying library detects the reset and returns the full
  current buffer, which we then re-timestamp to now. Worst case at a reboot is
  one duplicated buffer, which the timestamp key silently absorbs.
* Timestamps: the newest sample in each batch is anchored to the wall-clock
  moment of the poll (UTC, whole seconds); earlier samples step back one second
  each. Accuracy is +/- a few seconds of poll jitter -- far finer than the
  minute-plus scales you correlate at.

This script has no dependencies of its own beyond the `starlink_grpc` module
that ships with sparky8512/starlink-grpc-tools. Point PYTHONPATH at that repo
(the systemd unit does this for you).
"""

import argparse
import signal
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone

try:
    import starlink_grpc as sg
except ImportError:
    sys.stderr.write(
        "ERROR: could not import 'starlink_grpc'.\n"
        "Set PYTHONPATH to your starlink-grpc-tools checkout, e.g.\n"
        "  PYTHONPATH=/home/pi/starlink-grpc-tools python3 starlink_logger.py\n"
    )
    raise

SCHEMA = """
CREATE TABLE IF NOT EXISTS history (
    ts_utc          TEXT PRIMARY KEY,   -- ISO-8601 UTC, one row per second
    counter         INTEGER,            -- dish sample counter (resets on reboot)
    ping_drop_rate  REAL,               -- 0.0 = perfect, 1.0 = full outage that second
    ping_latency_ms REAL,               -- NULL during a full-drop second
    downlink_bps    REAL,
    uplink_bps      REAL,
    power_w         REAL
);
CREATE INDEX IF NOT EXISTS idx_history_counter ON history(counter);

CREATE TABLE IF NOT EXISTS status_snapshot (
    ts_utc               TEXT PRIMARY KEY,  -- one row per poll
    state                TEXT,
    uptime_s             INTEGER,
    fraction_obstructed  REAL,              -- confounder: sky blockage
    currently_obstructed INTEGER,
    downlink_bps         REAL,
    uplink_bps           REAL,
    latency_ms           REAL
);

CREATE TABLE IF NOT EXISTS poll_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc          TEXT,                   -- one row per poll cycle
    samples_fetched INTEGER,
    end_counter     INTEGER,
    status          TEXT                    -- 'ok' or an error message
);
"""

_stop = False


def _handle_signal(signum, frame):
    global _stop
    _stop = True
    sys.stderr.write(f"\n[{_now_iso()}] signal {signum} received, shutting down cleanly...\n")


def _now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def open_db(path):
    conn = sqlite3.connect(path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL;")       # safe against power loss mid-write
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def last_end_counter(conn):
    """Resume point: end_counter of the most recent successful poll, or None."""
    row = conn.execute(
        "SELECT end_counter FROM poll_log WHERE status='ok' "
        "AND end_counter IS NOT NULL ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return row[0] if row else None


def poll_once(conn, ctx, verbose=False, now=None):
    """Run one fetch-and-store cycle. Returns (samples_stored, end_counter).

    `now` (a tz-aware UTC datetime) can be injected for testing; in normal use
    it defaults to the current time, which anchors the newest sample.
    """
    poll_ts = (now or datetime.now(timezone.utc)).replace(microsecond=0)
    poll_iso = poll_ts.isoformat()

    start = last_end_counter(conn)

    # ---- history (the main payload) ----
    general, bulk = sg.history_bulk_data(-1, start=start, context=ctx, verbose=verbose)
    samples = general["samples"]
    end_counter = general["end_counter"]

    rows = []
    for i in range(samples):
        steps_back = samples - 1 - i           # newest sample -> poll time
        ts = (poll_ts - timedelta(seconds=steps_back)).isoformat()
        counter_i = end_counter - steps_back if end_counter is not None else None
        rows.append((
            ts,
            counter_i,
            bulk["pop_ping_drop_rate"][i],
            bulk["pop_ping_latency_ms"][i],
            bulk["downlink_throughput_bps"][i],
            bulk["uplink_throughput_bps"][i],
            bulk["power_w"][i],
        ))
    if rows:
        conn.executemany(
            "INSERT OR IGNORE INTO history "
            "(ts_utc, counter, ping_drop_rate, ping_latency_ms, downlink_bps, uplink_bps, power_w) "
            "VALUES (?,?,?,?,?,?,?)",
            rows,
        )

    # ---- status snapshot (obstruction confounder + current throughput) ----
    try:
        status, _obstruction_detail, _alert_detail = sg.status_data(context=ctx)
        cobs = status.get("currently_obstructed")
        conn.execute(
            "INSERT OR IGNORE INTO status_snapshot "
            "(ts_utc, state, uptime_s, fraction_obstructed, currently_obstructed, "
            " downlink_bps, uplink_bps, latency_ms) VALUES (?,?,?,?,?,?,?,?)",
            (
                poll_iso,
                status.get("state"),
                status.get("uptime"),
                status.get("fraction_obstructed"),
                None if cobs is None else int(bool(cobs)),
                status.get("downlink_throughput_bps"),
                status.get("uplink_throughput_bps"),
                status.get("pop_ping_latency_ms"),
            ),
        )
    except Exception as e:  # status is a bonus; never let it kill the history log
        if verbose:
            sys.stderr.write(f"[{poll_iso}] status snapshot skipped: {e}\n")

    conn.execute(
        "INSERT INTO poll_log (ts_utc, samples_fetched, end_counter, status) "
        "VALUES (?,?,?,?)",
        (poll_iso, samples, end_counter, "ok"),
    )
    conn.commit()
    return samples, end_counter


def log_failure(conn, message):
    try:
        conn.execute(
            "INSERT INTO poll_log (ts_utc, samples_fetched, end_counter, status) "
            "VALUES (?,?,?,?)",
            (_now_iso(), None, None, message[:300]),
        )
        conn.commit()
    except Exception:
        pass


def main():
    p = argparse.ArgumentParser(description="Log Starlink dish history to SQLite.")
    p.add_argument("--db", default="starlink_history.db", help="SQLite file path")
    p.add_argument("--interval", type=int, default=300, help="Seconds between polls (loop mode)")
    p.add_argument("--once", action="store_true", help="Run a single poll then exit (cron mode)")
    p.add_argument("--verbose", action="store_true", help="Verbose output")
    args = p.parse_args()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    conn = open_db(args.db)
    ctx = sg.ChannelContext()

    def run_cycle():
        try:
            n, end = poll_once(conn, ctx, verbose=args.verbose)
            sys.stderr.write(f"[{_now_iso()}] stored {n} new samples (end_counter={end})\n")
        except sg.GrpcError as e:
            sys.stderr.write(f"[{_now_iso()}] gRPC error: {e}\n")
            log_failure(conn, f"grpc: {e}")
            ctx.close()  # force reconnect next cycle
        except Exception as e:
            sys.stderr.write(f"[{_now_iso()}] unexpected error: {e}\n")
            log_failure(conn, f"error: {e}")
            ctx.close()

    if args.once:
        run_cycle()
        conn.close()
        return

    sys.stderr.write(
        f"[{_now_iso()}] logger started -> {args.db} (every {args.interval}s). Ctrl-C to stop.\n"
    )
    while not _stop:
        run_cycle()
        # responsive sleep so SIGTERM stops us promptly
        for _ in range(args.interval):
            if _stop:
                break
            time.sleep(1)

    ctx.close()
    conn.close()
    sys.stderr.write(f"[{_now_iso()}] stopped.\n")


if __name__ == "__main__":
    main()
