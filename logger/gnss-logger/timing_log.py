#!/usr/bin/env python3
"""
GNSS timing-quality logger (added 2026-11-01)
=============================================

Runs INSIDE gnss_logger.py (that process is the only owner of the serial port).
Once per navigation epoch (1 Hz) it writes one row to a separate small SQLite
database (gnss_timing.db, table timing_1hz), so gnss_tec.db is never touched.

Messages used (all parsed here with struct, no pyubx2 needed, low CPU):
  UBX-NAV-PVT      iTOW, UTC date/time, validity bits, fixType, gnssFixOK,
                   numSV, tAcc (receiver's own time-accuracy estimate, ns),
                   hAcc / vAcc (mm), pDOP
  UBX-NAV-TIMEUTC  UTC time accuracy, validUTC, which UTC standard
  UBX-NAV-STATUS   spoofing-detection state, time to first fix, ms since start
  UBX-TIM-TP       quantisation error of the next time pulse (qErr, ps)
  UBX-MON-RF       per RF block: jamming indicator (jamInd 0-255), jamming
                   state, antenna status / power, AGC count, noise per ms
The optional messages are enabled one CFG-VALSET each, so if the firmware
rejects one, the others (and the 20 Hz raw set-up) are unaffected. Which ones
the receiver accepted (ACK/NAK) and which actually arrive is written to the
table rx_info, together with the MON-VER firmware strings.

'No valid time' counter: time_ok = validDate AND validTime AND fullyResolved
from NAV-PVT. no_valid_run_s = seconds (Pi monotonic clock) since the last
epoch with time_ok; no_valid_total_s = cumulative seconds without valid time
since the logger started. If NAV-PVT stops arriving altogether, a row with
status 'no_pvt' is written once per second so the gap is visible.

Every public method swallows its own exceptions: a problem here must never
stop the TEC logging.
"""

import os
import sqlite3
import struct
import sys
import time
from datetime import datetime, timezone

ID_NAV_PVT = b"\x01\x07"
ID_NAV_STATUS = b"\x01\x03"
ID_NAV_TIMEUTC = b"\x01\x21"
ID_TIM_TP = b"\x0d\x01"
ID_MON_RF = b"\x0a\x38"
ID_MON_VER = b"\x0a\x04"
ID_ACK_ACK = b"\x05\x01"
ID_ACK_NAK = b"\x05\x00"
TIMING_IDS = {ID_NAV_PVT, ID_NAV_STATUS, ID_NAV_TIMEUTC, ID_TIM_TP, ID_MON_RF,
              ID_MON_VER, ID_ACK_ACK, ID_ACK_NAK}
NAMES = {ID_NAV_PVT: "NAV-PVT", ID_NAV_STATUS: "NAV-STATUS", ID_NAV_TIMEUTC: "NAV-TIMEUTC",
         ID_TIM_TP: "TIM-TP", ID_MON_RF: "MON-RF", ID_MON_VER: "MON-VER"}

# message name -> pyubx2 configdb key (both spellings handled by caller)
OPTIONAL_MSGS = [
    ("NAV-PVT", "CFG_MSGOUT_UBX_NAV_PVT_USB"),
    ("MON-RF", "CFG_MSGOUT_UBX_MON_RF_USB"),
    ("NAV-TIMEUTC", "CFG_MSGOUT_UBX_NAV_TIMEUTC_USB"),
    ("NAV-STATUS", "CFG_MSGOUT_UBX_NAV_STATUS_USB"),
    ("TIM-TP", "CFG_MSGOUT_UBX_TIM_TP_USB"),
]

COLS = [
    "ts_utc", "status", "itow_ms", "year", "month", "day", "hour", "minute", "sec", "nano_ns",
    "valid_date", "valid_time", "fully_resolved", "confirmed_time", "time_ok",
    "fix_type", "gnss_fix_ok", "carr_soln", "num_sv", "t_acc_ns", "h_acc_mm", "v_acc_mm", "p_dop",
    "utc_t_acc_ns", "utc_valid", "utc_standard",
    "st_spoof_det", "st_ttff_ms", "st_msss_ms",
    "tp_qerr_ps", "tp_qerr_invalid", "tp_tow_ms",
    "rf0_jam_ind", "rf0_jam_state", "rf0_ant_status", "rf0_ant_power", "rf0_agc_cnt", "rf0_noise",
    "rf1_jam_ind", "rf1_jam_state", "rf1_ant_status", "rf1_ant_power", "rf1_agc_cnt", "rf1_noise",
    "no_valid_run_s", "no_valid_total_s",
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS timing_1hz (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc TEXT NOT NULL,        -- Pi system UTC when the epoch was written
    status TEXT,                 -- 'ok' or 'no_pvt' (no NAV-PVT for >1.5 s)
    itow_ms INTEGER,             -- GPS time of week of the nav epoch, ms
    year INTEGER, month INTEGER, day INTEGER, hour INTEGER, minute INTEGER, sec INTEGER,
    nano_ns INTEGER,             -- fraction of second, ns (NAV-PVT)
    valid_date INTEGER, valid_time INTEGER, fully_resolved INTEGER, confirmed_time INTEGER,
    time_ok INTEGER,             -- valid_date AND valid_time AND fully_resolved
    fix_type INTEGER,            -- 0 none, 2 2D, 3 3D, 5 time-only
    gnss_fix_ok INTEGER,
    carr_soln INTEGER,           -- 0 none, 1 RTK float, 2 RTK fixed
    num_sv INTEGER,              -- satellites used in the solution
    t_acc_ns INTEGER,            -- receiver's time-accuracy estimate, ns
    h_acc_mm INTEGER, v_acc_mm INTEGER,
    p_dop REAL,
    utc_t_acc_ns INTEGER,        -- NAV-TIMEUTC tAcc, ns
    utc_valid INTEGER,           -- NAV-TIMEUTC validUTC
    utc_standard INTEGER,        -- 3 = USNO (GPS) ... see interface description
    st_spoof_det INTEGER,        -- NAV-STATUS spoofDetState 0 unknown,1 none,2 indicated,3 multiple
    st_ttff_ms INTEGER, st_msss_ms INTEGER,
    tp_qerr_ps INTEGER,          -- TIM-TP quantisation error of next pulse, ps
    tp_qerr_invalid INTEGER,
    tp_tow_ms INTEGER,
    rf0_jam_ind INTEGER, rf0_jam_state INTEGER, rf0_ant_status INTEGER, rf0_ant_power INTEGER,
    rf0_agc_cnt INTEGER, rf0_noise INTEGER,
    rf1_jam_ind INTEGER, rf1_jam_state INTEGER, rf1_ant_status INTEGER, rf1_ant_power INTEGER,
    rf1_agc_cnt INTEGER, rf1_noise INTEGER,
    no_valid_run_s REAL,         -- seconds since last epoch with time_ok
    no_valid_total_s REAL        -- cumulative seconds without valid time since logger start
);
CREATE INDEX IF NOT EXISTS idx_timing_ts ON timing_1hz(ts_utc);
CREATE TABLE IF NOT EXISTS rx_info (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc TEXT, item TEXT, value TEXT
);
"""


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _payload(raw):
    n = struct.unpack_from("<H", raw, 4)[0]
    return raw[6:6 + n]


# ---- pure parsers (payload bytes -> dict); unit-tested against pyubx2 ----

def parse_nav_pvt(p):
    if len(p) < 92:
        return None
    (itow, year, month, day, hour, minute, sec, valid, tacc, nano,
     fix, flags, flags2, numsv) = struct.unpack_from("<IHBBBBBBIiBBBB", p, 0)
    hacc, vacc = struct.unpack_from("<II", p, 40)
    pdop = struct.unpack_from("<H", p, 76)[0]
    return {
        "itow_ms": itow, "year": year, "month": month, "day": day, "hour": hour,
        "minute": minute, "sec": sec, "nano_ns": nano,
        "valid_date": valid & 1, "valid_time": (valid >> 1) & 1,
        "fully_resolved": (valid >> 2) & 1, "confirmed_time": (flags2 >> 7) & 1,
        "fix_type": fix, "gnss_fix_ok": flags & 1, "carr_soln": (flags >> 6) & 3,
        "num_sv": numsv, "t_acc_ns": tacc, "h_acc_mm": hacc, "v_acc_mm": vacc,
        "p_dop": pdop * 0.01,
    }


def parse_nav_timeutc(p):
    if len(p) < 20:
        return None
    itow, tacc = struct.unpack_from("<II", p, 0)
    valid = p[19]
    return {"itow_ms": itow, "utc_t_acc_ns": tacc, "utc_valid": (valid >> 2) & 1,
            "utc_standard": (valid >> 4) & 0x0F}


def parse_nav_status(p):
    if len(p) < 16:
        return None
    itow, gpsfix, flags, fixstat, flags2, ttff, msss = struct.unpack_from("<IBBBBII", p, 0)
    return {"itow_ms": itow, "st_spoof_det": (flags2 >> 3) & 3, "st_ttff_ms": ttff,
            "st_msss_ms": msss}


def parse_tim_tp(p):
    if len(p) < 16:
        return None
    towms, towsub, qerr, week, flags, refinfo = struct.unpack_from("<IIiHBB", p, 0)
    return {"tp_qerr_ps": qerr, "tp_qerr_invalid": (flags >> 4) & 1, "tp_tow_ms": towms}


def parse_mon_rf(p):
    if len(p) < 4:
        return None
    nb = p[1]
    out = {}
    for i in range(min(nb, 2)):
        o = 4 + 24 * i
        if len(p) < o + 24:
            break
        blk, flags, ant_st, ant_pw = struct.unpack_from("<BBBB", p, o)
        noise, agc, jam = struct.unpack_from("<HHB", p, o + 12)
        k = f"rf{i}_"
        out.update({k + "jam_ind": jam, k + "jam_state": flags & 3, k + "ant_status": ant_st,
                    k + "ant_power": ant_pw, k + "agc_cnt": agc, k + "noise": noise})
    return out


def parse_mon_ver(p):
    def s(b):
        return b.split(b"\x00", 1)[0].decode("ascii", "replace").strip()
    if len(p) < 40:
        return None
    sw, hw = s(p[0:30]), s(p[30:40])
    ext = [s(p[o:o + 30]) for o in range(40, len(p) - 29, 30)]
    return {"sw": sw, "hw": hw, "ext": [e for e in ext if e]}


class TimingLog:
    def __init__(self, path):
        self.conn = sqlite3.connect(path, timeout=30)
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA synchronous=NORMAL;")
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        self._sql = (f"INSERT INTO timing_1hz ({','.join(COLS)}) "
                     f"VALUES ({','.join('?' * len(COLS))})")
        self.reset()

    def reset(self):
        """Called at each (re)open of the serial port."""
        t = time.monotonic()
        self.pending = {}            # itow -> dict of fields, plus '_t' monotonic
        self.rf = (None, 0.0)        # (dict, monotonic)
        self.tp = (None, 0.0)
        self.last_pvt = t
        self.last_valid = t
        self.last_gap_row = t
        self.last_row_t = None
        self.no_valid_total = getattr(self, "no_valid_total", 0.0)
        self.last_commit = t
        self.uncommitted = 0
        self.cfg_order = []          # names of VALSETs in send order, for ACK mapping
        self.ack_idx = 0
        self.seen = set()

    # -- configuration (called by gnss_logger.run after its own VALSET) --
    def configure(self, stream, UBXMessage, layers, txn):
        self.cfg_order = ["main"]    # the logger's own VALSET was sent just before
        for name, key in OPTIONAL_MSGS:
            try:
                try:
                    msg = UBXMessage.config_set(layers, txn, [(key, 1)])
                except Exception:
                    msg = UBXMessage.config_set(layers, txn, [(key.replace("_", "-", 2), 1)])
                stream.write(msg.serialize())
                self.cfg_order.append(name)
                time.sleep(0.1)
            except Exception as e:
                self.info("valset " + name, f"not sent: {e}")
        try:
            stream.write(b"\xb5\x62\x0a\x04\x00\x00\x0e\x34")   # poll UBX-MON-VER
        except Exception as e:
            self.info("mon-ver", f"poll not sent: {e}")
        self._commit(force=True)

    def info(self, item, value):
        try:
            self.conn.execute("INSERT INTO rx_info (ts_utc, item, value) VALUES (?,?,?)",
                              (_now_iso(), item, str(value)[:500]))
            self.uncommitted += 1
        except Exception as e:
            sys.stderr.write(f"[{_now_iso()}] timing info error: {e}\n")

    # -- per message --
    def handle(self, cid, raw):
        try:
            self._handle(cid, raw)
        except Exception as e:
            sys.stderr.write(f"[{_now_iso()}] timing handle error (skipped): {e}\n")

    def _handle(self, cid, raw):
        now = time.monotonic()
        p = _payload(raw)
        if cid in (ID_ACK_ACK, ID_ACK_NAK):
            if len(p) >= 2 and p[0] == 0x06 and p[1] == 0x8A:     # reply to CFG-VALSET
                name = (self.cfg_order[self.ack_idx] if self.ack_idx < len(self.cfg_order)
                        else f"extra#{self.ack_idx}")
                self.ack_idx += 1
                self.info("valset " + name, "ACK" if cid == ID_ACK_ACK else "NAK")
            return
        if cid not in self.seen and cid in NAMES:
            self.seen.add(cid)
            self.info("first seen", NAMES[cid])
        if cid == ID_MON_VER:
            v = parse_mon_ver(p)
            if v:
                self.info("MON-VER sw", v["sw"])
                self.info("MON-VER hw", v["hw"])
                self.info("MON-VER ext", " | ".join(v["ext"]))
            return
        if cid == ID_MON_RF:
            self.rf = (parse_mon_rf(p), now)
            return
        if cid == ID_TIM_TP:
            self.tp = (parse_tim_tp(p), now)
            return
        parser = {ID_NAV_PVT: parse_nav_pvt, ID_NAV_TIMEUTC: parse_nav_timeutc,
                  ID_NAV_STATUS: parse_nav_status}.get(cid)
        if parser is None:
            return
        d = parser(p)
        if not d:
            return
        itow = d["itow_ms"]
        # a new nav epoch -> flush older ones
        for old in [k for k in self.pending if k != itow]:
            self._flush(old)
        ep = self.pending.setdefault(itow, {"_t": now})
        ep.update(d)
        if cid == ID_NAV_PVT:
            ep["_pvt"] = True
            self.last_pvt = now

    def tick(self):
        """Cheap; called for every message read. Flushes stale epochs, writes
        'no_pvt' rows when NAV-PVT has stopped, and commits every ~10 s."""
        try:
            now = time.monotonic()
            for k in [k for k, v in self.pending.items() if now - v["_t"] > 1.2]:
                self._flush(k)
            if now - self.last_pvt > 1.5 and now - self.last_gap_row >= 1.0:
                self.last_gap_row = now
                self._write({"_t": now}, status="no_pvt")
            if now - self.last_commit >= 10:
                self._commit()
        except Exception as e:
            sys.stderr.write(f"[{_now_iso()}] timing tick error: {e}\n")

    def _flush(self, itow):
        ep = self.pending.pop(itow, None)
        if ep is not None:
            self._write(ep, status="ok" if ep.get("_pvt") else "no_pvt")

    def _write(self, ep, status):
        now = ep["_t"]
        row = dict(ep)
        ok = bool(row.get("_pvt") and row.get("valid_date") and row.get("valid_time")
                  and row.get("fully_resolved"))
        row["time_ok"] = 1 if ok else 0
        # accumulate time without valid time (wall time between written rows)
        if self.last_row_t is not None and not ok:
            self.no_valid_total += max(0.0, min(now - self.last_row_t, 5.0))
        self.last_row_t = now
        if ok:
            self.last_valid = now
        row["no_valid_run_s"] = round(now - self.last_valid, 2)
        row["no_valid_total_s"] = round(self.no_valid_total, 2)
        for src, t in (self.rf, self.tp):
            if src and now - t < 2.5:
                row.update(src)
        row["ts_utc"] = _now_iso()
        row["status"] = status
        self.conn.execute(self._sql, [row.get(c) for c in COLS])
        self.uncommitted += 1

    def _commit(self, force=False):
        if self.uncommitted or force:
            self.conn.commit()
            self.uncommitted = 0
        self.last_commit = time.monotonic()

    def close(self):
        try:
            for k in list(self.pending):
                self._flush(k)
            self._commit(force=True)
            self.conn.close()
        except Exception:
            pass
