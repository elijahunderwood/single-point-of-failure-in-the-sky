"""Rebuild missing 1 Hz TEC rows from the 20 Hz raw UBX files into a SEPARATE db
(gnss_tec_backfill.db). Does not touch gnss_tec.db. Uses the logger own functions."""
import sys, gzip, glob, os, sqlite3, datetime as dt
sys.path.insert(0, os.path.expanduser("~/gnss-logger"))
import gnss_logger as g
from pyubx2 import UBXReader, UBX_PROTOCOL
GPS0 = dt.datetime(1980,1,6,tzinfo=dt.timezone.utc); LEAP = dt.timedelta(seconds=18)
files = sorted(glob.glob(os.path.expanduser("~/gnss_raw/2026/*/*/raw_*.ubx*")))
start, end = sys.argv[1], sys.argv[2]            # e.g. 20261023_23 20261027_16 (inclusive hours)
files = [f for f in files if start <= os.path.basename(f)[4:15] <= end]
out = g.open_db(os.path.expanduser("~/gnss-logger/gnss_tec_backfill.db"))
nav_elev, slip = {}, {}
for fn in files:
    fh = gzip.open(fn,"rb") if fn.endswith(".gz") else open(fn,"rb")
    last_sec = None; n_ep = 0
    for raw, _ in UBXReader(fh, protfilter=UBX_PROTOCOL, parsing=0):
        if not raw or len(raw) < 8: continue
        cid = raw[2:4]
        if cid == g.NAVSAT_ID:
            p = g._parse(raw)
            if p is not None: nav_elev = g.process_navsat(p)
        elif cid == g.RAWX_ID and len(raw) >= 24:
            tow = g.rawx_tow(raw)
            if not g.is_whole_second(tow): continue
            p = g._parse(raw)
            if p is None: continue
            t = GPS0 + dt.timedelta(weeks=int(p.week), seconds=float(p.rcvTow)) - LEAP
            iso = t.isoformat(timespec="milliseconds")
            rows, n = g.process_rawx(p, nav_elev, slip, iso)
            g.store_epoch(out, rows, p.rcvTow, n); n_ep += 1
    fh.close()
    print(os.path.basename(fn), n_ep, flush=True)
