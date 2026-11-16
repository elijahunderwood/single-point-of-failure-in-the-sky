#!/usr/bin/env python3
"""
GNSS / TEC logger
================

The scientific centrepiece. Reads raw dual-frequency measurements from a u-blox
ZED-F9P (simpleRTK2B) and derives ionospheric Total Electron Content (TEC) for
each GPS satellite, storing it to SQLite with UTC timestamps aligned to the other
loggers.

Two TEC estimates are stored per satellite per epoch:
  * code_tec  -- from the pseudorange difference P(L2)-P(L1). Absolute-ish but
                 noisy (metre-level), and biased by receiver/satellite hardware
                 delays (DCBs). Fine for magnitude; poor for rate-of-change.
  * phase_tec -- from the carrier-phase difference. Very smooth, but has an
                 unknown constant offset per continuous phase-lock arc. This is
                 the input for ROTI (rate-of-TEC index) in later analysis --
                 the offset cancels when you differentiate.

The elevation angle of each satellite (from NAV-SAT) is stored too, so analysis
can apply an elevation mask (cut low-elevation multipath) and compute ionospheric
pierce points.

Design choice (matches the other loggers): this logs raw per-epoch observables.
ROT / ROTI, elevation masking and pierce points are computed in a separate
analysis step, not here -- keeping the logger simple and the science transparent.

Requires: pyubx2, pyserial (in the venv). And ModemManager must not grab the
serial port (see README).

20 Hz upgrade (2026-10-22): the receiver now measures at 20 Hz (CFG-RATE-MEAS
50 ms, set in RAM only on every start; flash still holds 1 Hz). Navigation
(PVT/NAV-SAT) stays at 1 Hz via CFG-RATE-NAV=20. This process is the ONLY
owner of /dev/ttyACM0 and:
  * tees every raw UBX message, byte for byte, into hourly files
    ~/gnss_raw/YYYY/MM/DD/raw_YYYYMMDD_HH.ubx (UTC hour) for the scintillation
    processor (S4 / sigma-phi), which also gzips each completed hour;
  * still writes gnss_tec.db exactly as before, using ONLY whole-second RAWX
    epochs (decimation 20 -> 1 Hz). Slip/lock-time state is updated only on
    those epochs, so the slip flag behaves exactly as it did at 1 Hz.
Unused NMEA output on USB is switched off in RAM (nothing reads it).
"""

import argparse
import os
import shutil
import signal
import struct
import sqlite3
import sys
import time
from datetime import datetime, timezone

from serial import Serial
from pyubx2 import (UBXReader, UBXMessage, UBX_PROTOCOL, TXN_NONE,
                    SET_LAYER_RAM, SET_LAYER_BBR, SET_LAYER_FLASH)

# Timing-quality logging (2026-11-01): separate DB, never allowed to stop TEC logging.
try:
    from timing_log import TimingLog, TIMING_IDS
except Exception as _e:          # missing module -> run exactly as before
    TimingLog, TIMING_IDS = None, set()
    sys.stderr.write(f"timing_log not loaded: {_e}\n")

# ---- physical constants (GPS L1 C/A + L2C) ----
F1 = 1575.42e6            # GPS L1 frequency, Hz
F2 = 1227.60e6            # GPS L2 frequency, Hz
C = 299792458.0          # speed of light, m/s
LAMBDA1 = C / F1         # L1 wavelength, m
LAMBDA2 = C / F2         # L2 wavelength, m
# TEC per metre of L1/L2 differential delay, in TECU (1 TECU = 1e16 el/m^2).
# K = f1^2 f2^2 / (40.308 (f1^2 - f2^2)) / 1e16  ~= 9.52
K = (F1**2 * F2**2) / (40.308 * (F1**2 - F2**2)) / 1e16

# GPS signal IDs in RXM-RAWX: 0 = L1 C/A, 3 = L2 CL, 4 = L2 CM
SIG_L1 = {0}
SIG_L2 = {3, 4}
GNSS_GPS = 0

SLIP_LOCK_MS = 2000      # carrier lock shorter than this -> treat as unreliable/new arc

SCHEMA = """
CREATE TABLE IF NOT EXISTS tec (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc      TEXT NOT NULL,     -- system UTC at receipt (aligns with other loggers)
    rcv_tow     REAL,              -- receiver GPS time-of-week (s), precise dt for ROT
    gps_week    INTEGER,
    sv          INTEGER NOT NULL,  -- GPS PRN
    elev_deg    REAL,              -- satellite elevation (from NAV-SAT), nullable
    azim_deg    REAL,              -- satellite azimuth (from NAV-SAT), nullable
    code_tec    REAL,              -- 9.52*(P_L2-P_L1), TECU: absolute-ish, noisy
    phase_tec   REAL,              -- relative phase TEC, TECU: smooth, per-arc offset
    cno_l1      INTEGER,           -- carrier-to-noise L1, dB-Hz
    cno_l2      INTEGER,
    locktime_l2 INTEGER,           -- L2 carrier lock time, ms
    slip        INTEGER            -- 1 if new arc / suspected cycle slip
);
CREATE INDEX IF NOT EXISTS idx_tec_sv_tow ON tec(sv, rcv_tow);
CREATE INDEX IF NOT EXISTS idx_tec_ts ON tec(ts_utc);

CREATE TABLE IF NOT EXISTS epoch_log (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc    TEXT,
    rcv_tow   REAL,
    num_meas  INTEGER,             -- total raw measurements in the epoch
    num_pairs INTEGER,             -- GPS L1/L2 pairs stored
    status    TEXT
);
"""

_stop = False


def _handle_signal(signum, frame):
    global _stop
    _stop = True
    sys.stderr.write(f"\n[{_now_iso()}] signal {signum} received, shutting down...\n")


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def open_db(path):
    conn = sqlite3.connect(path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def configure_receiver(stream, persist=False, meas_ms=1000, nav_ratio=1, nmea_usb=None):
    """Enable RXM-RAWX and NAV-SAT on the USB port.
    Defaults (used by gnss_configure.py) = 1 Hz, exactly as before.
    The logger passes meas_ms=50, nav_ratio=20 (20 Hz raw, 1 Hz nav) and
    nmea_usb=0, always with persist=False so nothing is written to BBR/flash.
    persist=False -> RAM only (applied fresh each start; no flash wear).
    persist=True  -> RAM+BBR+Flash (survives power cycles).
    """
    layers = SET_LAYER_RAM
    if persist:
        layers = SET_LAYER_RAM | SET_LAYER_BBR | SET_LAYER_FLASH
    cfg = [
        ("CFG-MSGOUT-UBX_RXM_RAWX_USB", 1),
        ("CFG-MSGOUT-UBX_NAV_SAT_USB", 1),
        ("CFG-RATE-MEAS", int(meas_ms)),   # measurement period (1000 = 1 Hz, 50 = 20 Hz)
        ("CFG-RATE-NAV", int(nav_ratio)),  # measurements per nav solution -> nav stays 1 Hz
    ]
    if nmea_usb is not None:
        cfg.append(("CFG-USBOUTPROT-NMEA", int(nmea_usb)))
    msg = UBXMessage.config_set(layers, TXN_NONE, cfg)
    stream.write(msg.serialize())
    time.sleep(0.3)


# ---- 20 Hz support: raw tee + whole-second decimation ----

RAWX_ID = b"\x02\x15"     # class/id bytes of UBX-RXM-RAWX
NAVSAT_ID = b"\x01\x35"   # class/id bytes of UBX-NAV-SAT


def rawx_tow(raw):
    """rcvTow (s) straight from the RAWX bytes (payload offset 0, R8)."""
    return struct.unpack_from("<d", raw, 6)[0]


def is_whole_second(tow, tol=0.0245):
    """True for the RAWX epoch on a whole receiver second (decimate to 1 Hz)."""
    return tow is not None and abs(tow - round(tow)) < tol


class RawTee:
    """Append raw UBX bytes to hourly files (UTC). Never raises: a problem
    here must not stop the TEC database logging."""

    def __init__(self, root, min_free_gb=5.0):
        self.root = root
        self.min_free = min_free_gb * 1e9
        self.fh = None
        self.hour = None
        self.paused = False
        self.next_check = 0.0
        self.next_retry = 0.0
        try:
            os.makedirs(root, exist_ok=True)
        except Exception as e:
            sys.stderr.write(f"[{_now_iso()}] raw tee: cannot create {root}: {e}\n")

    def _open(self, now):
        t = time.gmtime(now)
        d = os.path.join(self.root, time.strftime("%Y/%m/%d", t))
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, time.strftime("raw_%Y%m%d_%H.ubx", t))
        self.fh = open(path, "ab", buffering=65536)

    def write(self, data):
        now = time.time()
        try:
            if now >= self.next_check:
                self.next_check = now + 60
                free = shutil.disk_usage(self.root).free
                if not self.paused and free < self.min_free:
                    self.paused = True
                    sys.stderr.write(f"[{_now_iso()}] raw tee PAUSED: only {free/1e9:.1f} GB free\n")
                elif self.paused and free > self.min_free + 1e9:
                    self.paused = False
                    sys.stderr.write(f"[{_now_iso()}] raw tee resumed\n")
            if self.paused:
                self.close()
                return
            hour = int(now // 3600)
            if hour != self.hour or self.fh is None:
                if now < self.next_retry:
                    return
                self.close()
                self.hour = hour
                self._open(now)
            self.fh.write(data)
        except Exception as e:
            sys.stderr.write(f"[{_now_iso()}] raw tee error: {e}\n")
            self.close()
            self.next_retry = now + 60

    def close(self):
        if self.fh is not None:
            try:
                self.fh.close()
            except Exception:
                pass
            self.fh = None


# ---- pure processing functions (unit-tested offline) ----

def process_navsat(parsed):
    """Return {sv: (elev_deg, azim_deg, cno)} for GPS satellites."""
    out = {}
    n = getattr(parsed, "numSvs", 0)
    for i in range(1, n + 1):
        k = f"{i:02d}"
        if getattr(parsed, f"gnssId_{k}") != GNSS_GPS:
            continue
        sv = getattr(parsed, f"svId_{k}")
        out[sv] = (getattr(parsed, f"elev_{k}"),
                   getattr(parsed, f"azim_{k}"),
                   getattr(parsed, f"cno_{k}"))
    return out


def process_rawx(parsed, nav_elev, slip_state, now_iso):
    """Turn one RXM-RAWX epoch into TEC rows for each GPS L1/L2 pair.
    Returns (rows, num_meas). Pure function -- no I/O.
    """
    week = getattr(parsed, "week", None)
    tow = getattr(parsed, "rcvTow", None)
    n = getattr(parsed, "numMeas", 0)

    per_sv = {}   # sv -> {'L1': meas, 'L2': meas}
    for i in range(1, n + 1):
        k = f"{i:02d}"
        if getattr(parsed, f"gnssId_{k}") != GNSS_GPS:
            continue
        sig = getattr(parsed, f"sigId_{k}")
        band = "L1" if sig in SIG_L1 else ("L2" if sig in SIG_L2 else None)
        if band is None:
            continue
        sv = getattr(parsed, f"svId_{k}")
        per_sv.setdefault(sv, {})[band] = {
            "pr": getattr(parsed, f"prMes_{k}"),
            "cp": getattr(parsed, f"cpMes_{k}"),
            "lock": getattr(parsed, f"locktime_{k}"),
            "cno": getattr(parsed, f"cno_{k}"),
            "prValid": getattr(parsed, f"prValid_{k}"),
            "cpValid": getattr(parsed, f"cpValid_{k}"),
        }

    rows = []
    for sv, m in per_sv.items():
        if "L1" not in m or "L2" not in m:
            continue                                   # need both frequencies
        l1, l2 = m["L1"], m["L2"]
        if not (l1["prValid"] and l1["cpValid"] and l2["prValid"] and l2["cpValid"]):
            continue                                   # need valid code + phase on both

        code_tec = K * (l2["pr"] - l1["pr"])
        phase_tec = K * (l1["cp"] * LAMBDA1 - l2["cp"] * LAMBDA2)  # relative (per-arc offset)

        lock = l2["lock"]
        prev = slip_state.get(sv)
        slip = 1 if (prev is None or lock < prev or lock < SLIP_LOCK_MS) else 0
        slip_state[sv] = lock

        nav = nav_elev.get(sv)
        elev, azim = (nav[0], nav[1]) if nav else (None, None)

        rows.append((now_iso, tow, week, sv, elev, azim,
                     code_tec, phase_tec, l1["cno"], l2["cno"], lock, slip))
    return rows, n


def store_epoch(conn, rows, tow, num_meas):
    if rows:
        conn.executemany(
            "INSERT INTO tec (ts_utc, rcv_tow, gps_week, sv, elev_deg, azim_deg, "
            "code_tec, phase_tec, cno_l1, cno_l2, locktime_l2, slip) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    conn.execute(
        "INSERT INTO epoch_log (ts_utc, rcv_tow, num_meas, num_pairs, status) VALUES (?,?,?,?,?)",
        (rows[0][0] if rows else _now_iso(), tow, num_meas, len(rows), "ok"))
    conn.commit()


def _parse(raw):
    try:
        return UBXReader.parse(raw)
    except Exception as e:
        sys.stderr.write(f"[{_now_iso()}] parse error (skipped): {e}\n")
        return None


def run(conn, port, baud, verbose, meas_ms=1000, raw_tee=None, nmea_off=False, timing=None):
    stream = Serial(port, baud, timeout=3)
    nav_ratio = max(1, int(round(1000 / meas_ms)))
    configure_receiver(stream, persist=False, meas_ms=meas_ms, nav_ratio=nav_ratio,
                       nmea_usb=(0 if nmea_off else None))
    if timing is not None:
        try:
            timing.reset()
            timing.configure(stream, UBXMessage, SET_LAYER_RAM, TXN_NONE)
        except Exception as e:
            sys.stderr.write(f"[{_now_iso()}] timing configure error: {e}\n")
    # parsing=0: return raw bytes only; we parse just NAV-SAT and the
    # whole-second RAWX epochs (keeps CPU near the old 1 Hz level).
    ubr = UBXReader(stream, protfilter=UBX_PROTOCOL, parsing=0)
    nav_elev = {}
    slip_state = {}
    sys.stderr.write(f"[{_now_iso()}] reading {port} (meas {meas_ms} ms, nav ratio {nav_ratio}, "
                     f"raw tee {'on' if raw_tee else 'off'}) ...\n")
    try:
        for (raw, _unused) in ubr:
            if _stop:
                break
            if not raw or len(raw) < 8:
                continue
            if raw_tee is not None:
                raw_tee.write(raw)
            cid = raw[2:4]
            if timing is not None:
                if cid in TIMING_IDS:
                    timing.handle(cid, raw)
                timing.tick()
            if cid == NAVSAT_ID:
                parsed = _parse(raw)
                if parsed is not None:
                    nav_elev = process_navsat(parsed)
            elif cid == RAWX_ID and len(raw) >= 24:
                if not is_whole_second(rawx_tow(raw)):
                    continue                     # 20 Hz sub-second epoch: raw file only
                parsed = _parse(raw)
                if parsed is None:
                    continue
                rows, n = process_rawx(parsed, nav_elev, slip_state, _now_iso())
                store_epoch(conn, rows, getattr(parsed, "rcvTow", None), n)
                if verbose:
                    sys.stderr.write(f"[{_now_iso()}] epoch: {n} meas, {len(rows)} GPS L1/L2 pairs\n")
    finally:
        if raw_tee is not None:
            raw_tee.close()
        stream.close()


def main():
    p = argparse.ArgumentParser(description="Log GNSS dual-frequency TEC to SQLite.")
    p.add_argument("--port", default="/dev/ttyACM0", help="Serial port of the F9P")
    p.add_argument("--baud", type=int, default=38400, help="Baud (ignored over USB CDC)")
    p.add_argument("--db", default="gnss_tec.db", help="SQLite file path")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--meas-ms", type=int, default=50,
                   help="Measurement period in ms, RAM only (50 = 20 Hz; 1000 = old 1 Hz)")
    p.add_argument("--raw-dir", default=os.path.expanduser("~/gnss_raw"),
                   help="Hourly raw UBX files go here ('' to disable the tee)")
    p.add_argument("--keep-nmea", action="store_true",
                   help="Leave NMEA output on USB (default: switch it off in RAM)")
    p.add_argument("--timing-db", default=None,
                   help="Timing-quality SQLite file (default: gnss_timing.db next to --db; '' disables)")
    args = p.parse_args()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    conn = open_db(args.db)
    timing = None
    tpath = args.timing_db
    if tpath is None:
        tpath = os.path.join(os.path.dirname(os.path.abspath(args.db)), "gnss_timing.db")
    if tpath and TimingLog is not None:
        try:
            timing = TimingLog(tpath)
        except Exception as e:
            sys.stderr.write(f"[{_now_iso()}] timing db not opened ({e}); continuing without it\n")

    while not _stop:
        try:
            tee = RawTee(args.raw_dir) if args.raw_dir else None
            run(conn, args.port, args.baud, args.verbose, meas_ms=args.meas_ms,
                raw_tee=tee, nmea_off=not args.keep_nmea, timing=timing)
        except Exception as e:
            sys.stderr.write(f"[{_now_iso()}] error: {e} -- retrying in 10s\n")
            try:
                conn.execute("INSERT INTO epoch_log (ts_utc, status) VALUES (?,?)",
                             (_now_iso(), f"error: {e}"[:200]))
                conn.commit()
            except Exception:
                pass
            for _ in range(10):
                if _stop:
                    break
                time.sleep(1)

    if timing is not None:
        timing.close()
    conn.close()
    sys.stderr.write(f"[{_now_iso()}] stopped.\n")


if __name__ == "__main__":
    main()
