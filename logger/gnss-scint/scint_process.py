#!/usr/bin/env python3
"""
Per-minute scintillation indices (S4, sigma-phi) from the 20 Hz raw UBX files
written by gnss_logger.py (~/gnss_raw/YYYY/MM/DD/raw_YYYYMMDD_HH.ubx[.gz]).

Run hourly (scint-process.timer). For every completed UTC hour H not yet
processed it:
  1. reads RXM-RAWX (20 Hz) + NAV-SAT (1 Hz) from H, plus 3 min either side
     from H-1 / H+1 so filters have no edge effects at hour boundaries;
  2. computes, per satellite + signal + UTC minute:
       S4        from C/N0 (dB-Hz -> linear power), detrended by dividing by a
                 6th-order Butterworth low-pass (0.1 Hz) of itself;
       s4_n0     expected thermal-noise S4 (Van Dierendonck 1993):
                 sqrt(100/SNR * (1 + 500/(19*SNR))), SNR = 10^(C/N0/10);
       s4_nc     sqrt(max(0, S4^2 - s4_n0^2))  (noise-corrected);
       sigma_phi_raw  std (rad) of carrier phase after a 6th-order Butterworth
                 high-pass (0.1 Hz, zero-phase), per continuous lock arc;
       sigma_phi same, after removing the receiver-clock common mode: at each
                 epoch the median high-pass phase (in metres, where receiver
                 clock error is identical for every signal) over all signals
                 with elevation >= 30 deg is subtracted, then converted back
                 to radians;
     plus elevation/azimuth (NAV-SAT), mean C/N0, sample counts, lock flags;
  3. writes rows to ~/gnss-scint/scint.db (table scint), records the file in
     processed_files, then gzips the raw hour (nice/ionice).
All elevations are stored; filter with elev_deg >= 30 for the usual mask.
Run with --hour YYYYMMDD_HH to (re)process one hour.
"""
import argparse, glob, gzip, os, sqlite3, subprocess, sys, time, warnings
from datetime import datetime, timezone
import numpy as np
from scipy.signal import butter, sosfiltfilt

HOME = os.path.expanduser("~")
RAW_ROOT = os.path.join(HOME, "gnss_raw")
DB = os.path.join(HOME, "gnss-scint", "scint.db")
FS = 20.0                       # Hz
DT = 1.0 / FS
FC = 0.1                        # Hz, filter cut-off
EDGE_S = 20.0                   # s discarded at each arc end (filter settling)
MIN_ARC_S = 60.0
MIN_FRAC = 0.9                  # need >=90 % of a minute's samples
ELEV_MASK_CM = 30.0             # signals used for the clock common-mode
PAD_S = 180.0
GPS_UNIX = 315964800            # 1980-01-06 in Unix seconds
GN = {0: "GPS", 1: "SBAS", 2: "GAL", 3: "BDS", 5: "QZSS", 6: "GLO"}
MEAS_DT = np.dtype([("pr", "<f8"), ("cp", "<f8"), ("do", "<f4"), ("gnss", "u1"),
                    ("sv", "u1"), ("sig", "u1"), ("freq", "u1"), ("lock", "<u2"),
                    ("cno", "u1"), ("prstd", "u1"), ("cpstd", "u1"), ("dostd", "u1"),
                    ("trk", "u1"), ("res", "u1")])
SOS_HP = butter(6, FC, btype="highpass", fs=FS, output="sos")
SOS_LP = butter(6, FC, btype="lowpass", fs=FS, output="sos")

SCHEMA = """
CREATE TABLE IF NOT EXISTS scint (
  minute_utc    TEXT NOT NULL,    -- start of the UTC minute
  gnss          TEXT NOT NULL,    -- GPS/GAL/BDS/GLO/QZSS/SBAS
  sv            INTEGER NOT NULL,
  sig_id        INTEGER NOT NULL, -- u-blox sigId (GPS 0=L1CA 3/4=L2C, GAL 0/1=E1 5/6=E5b, BDS 0/1=B1I 2/3=B2I, GLO 0=L1 2=L2)
  freq_mhz      REAL,
  elev_deg      REAL,
  azim_deg      REAL,
  n_samples     INTEGER,          -- C/N0 samples used for S4
  n_phase       INTEGER,          -- phase samples used for sigma-phi
  cno_mean      REAL,             -- dB-Hz
  s4            REAL,             -- detrended, uncorrected
  s4_n0         REAL,             -- thermal-noise S4 estimate
  s4_nc         REAL,             -- noise-corrected
  sigma_phi_raw REAL,             -- rad, high-pass only (contains receiver clock)
  sigma_phi     REAL,             -- rad, after common-mode (clock) removal
  cm_nsig       REAL,             -- mean no. of signals in the common-mode median
  lock_full     INTEGER,          -- 1 = one continuous lock arc covered the whole minute
  n_arcs        INTEGER,
  halfcyc_ok    REAL,             -- fraction of samples with half-cycle resolved
  src_hour      TEXT,
  ts_utc        TEXT NOT NULL,    -- when this row was written (used by backup/watchdog)
  PRIMARY KEY (minute_utc, gnss, sv, sig_id)
);
CREATE INDEX IF NOT EXISTS idx_scint_ts ON scint(ts_utc);
CREATE TABLE IF NOT EXISTS processed_files (
  hour_utc   TEXT PRIMARY KEY,   -- YYYYMMDD_HH
  path       TEXT,
  status     TEXT,
  epochs     INTEGER,
  missed     INTEGER,            -- missed 20 Hz epochs inside the hour
  rows       INTEGER,
  secs       REAL,
  ts_utc     TEXT                -- processing time
);
"""


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def wavelength(gnss, sig, freq):
    c = 299792458.0
    if gnss == 6:
        k = int(freq) - 7
        f = (1602.0 + k * 0.5625) if sig == 0 else (1246.0 + k * 0.4375)
    elif gnss in (0, 5, 1):
        f = 1575.42 if sig in (0, 1) else 1227.60
    elif gnss == 2:
        f = 1575.42 if sig in (0, 1) else 1207.14
    elif gnss == 3:
        f = 1561.098 if sig in (0, 1) else 1207.14
    else:
        return None, None
    return c / (f * 1e6), f


def read_file(path):
    op = gzip.open if path.endswith(".gz") else open
    with op(path, "rb") as fh:
        return fh.read()


def parse_ubx(buf, t_lo=None, t_hi=None):
    """Return (epochs, meas, navsat). epochs: list of (tgps, leap, n);
    meas: structured array + per-row epoch index; navsat: list of arrays."""
    mv = memoryview(buf)
    i, n = 0, len(buf)
    ep_t, ep_leap, blocks, ep_idx = [], [], [], []
    nav = []
    bad = 0
    while True:
        i = buf.find(b"\xb5\x62", i)
        if i < 0 or i + 8 > n:
            break
        ln = buf[i + 4] | (buf[i + 5] << 8)
        end = i + 6 + ln + 2
        if end > n:
            break
        body = np.frombuffer(mv[i + 2:i + 6 + ln], dtype=np.uint8)
        ck_a = int(body.sum()) & 0xFF
        ck_b = int((np.arange(len(body), 0, -1, dtype=np.int64) * body).sum()) & 0xFF
        if ck_a != buf[end - 2] or ck_b != buf[end - 1]:
            bad += 1
            i += 2
            continue
        cls, mid = buf[i + 2], buf[i + 3]
        p = i + 6
        if cls == 0x02 and mid == 0x15 and ln >= 16:
            tow = np.frombuffer(mv[p:p + 8], "<f8")[0]
            week = buf[p + 8] | (buf[p + 9] << 8)
            leap = np.frombuffer(mv[p + 10:p + 11], "i1")[0]
            nm = buf[p + 11]
            tg = week * 604800.0 + float(tow)
            utc = tg - leap + GPS_UNIX
            if (t_lo is None or utc >= t_lo) and (t_hi is None or utc < t_hi) and ln >= 16 + 32 * nm:
                k = len(ep_t)
                ep_t.append(tg); ep_leap.append(int(leap))
                blocks.append(np.frombuffer(mv[p + 16:p + 16 + 32 * nm], MEAS_DT))
                ep_idx.append(np.full(nm, k, dtype=np.int32))
        elif cls == 0x01 and mid == 0x35 and ln >= 8:
            itow = (buf[p] | buf[p + 1] << 8 | buf[p + 2] << 16 | buf[p + 3] << 24) / 1000.0
            ns = buf[p + 5]
            arr = np.frombuffer(mv[p + 8:p + 8 + 12 * ns],
                                np.dtype([("gnss", "u1"), ("sv", "u1"), ("cno", "u1"), ("elev", "i1"),
                                          ("azim", "<i2"), ("prres", "<i2"), ("flags", "<u4")]))
            nav.append((itow, arr.copy()))
        i = end
    meas = np.concatenate(blocks) if blocks else np.zeros(0, MEAS_DT)
    idx = np.concatenate(ep_idx) if ep_idx else np.zeros(0, np.int32)
    return np.array(ep_t), np.array(ep_leap), meas, idx, nav, bad


def hour_files():
    out = {}
    for pth in glob.glob(os.path.join(RAW_ROOT, "[0-9]" * 4, "*", "*", "raw_*.ubx*")):
        b = os.path.basename(pth)
        key = b[4:15]                         # YYYYMMDD_HH
        if pth.endswith(".ubx") or pth.endswith(".ubx.gz"):
            # prefer the .gz if both exist momentarily
            if key not in out or pth.endswith(".gz"):
                out[key] = pth
    return out


def hour_start(key):
    return datetime.strptime(key, "%Y%m%d_%H").replace(tzinfo=timezone.utc).timestamp()


def key_of(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y%m%d_%H")


def arcs_for(t, lock, trk, gap=1.5 * DT):
    """Split indices of one signal into continuous arcs (no missing epoch,
    lock time not reset, carrier phase valid)."""
    cpv = (trk & 0x02) > 0
    brk = np.ones(len(t), bool)
    if len(t) > 1:
        brk[1:] = (np.diff(t) > gap) | (lock[1:] < lock[:-1]) | (cpv[1:] != cpv[:-1]) | \
                  (((trk[1:] >> 3) & 1) != ((trk[:-1] >> 3) & 1))
    starts = np.flatnonzero(brk)
    ends = np.append(starts[1:], len(t))
    return [(s, e) for s, e in zip(starts, ends)]


def process_hour(key, files, conn, verbose=False):
    t0 = time.time()
    h0 = hour_start(key)
    h1 = h0 + 3600
    parts = []
    for k, lo, hi in ((key_of(h0 - 3600), h0 - PAD_S, h0), (key, h0, h1), (key_of(h1), h1, h1 + PAD_S)):
        if k in files:
            parts.append(parse_ubx(read_file(files[k]), lo, hi))
    ep_t = np.concatenate([p[0] for p in parts])
    ep_leap = np.concatenate([p[1] for p in parts])
    offs = np.cumsum([0] + [len(p[0]) for p in parts[:-1]])
    meas = np.concatenate([p[2] for p in parts])
    idx = np.concatenate([p[3] + o for p, o in zip(parts, offs)])
    nav = [x for p in parts for x in p[4]]
    bad = sum(p[5] for p in parts)
    if len(ep_t) == 0:
        return dict(status="empty", epochs=0, missed=0, rows=0)
    order = np.argsort(ep_t, kind="stable")
    # epoch stats inside the hour proper
    leap = int(np.median(ep_leap))
    utc_ep = ep_t - leap + GPS_UNIX
    inh = np.sort(ep_t[(utc_ep >= h0) & (utc_ep < h1)])
    d = np.diff(inh)
    missed = int(np.sum(np.maximum(0, np.round(d / DT) - 1))) if len(d) else 0
    n_epochs = len(inh)

    # elevation/azimuth per (gnss, sv) per minute from NAV-SAT (1 Hz)
    week0 = int(ep_t[order[0]] // 604800)
    elev = {}
    for itow, arr in nav:
        tg = week0 * 604800.0 + itow
        if tg < ep_t.min() - 302400:          # week rollover
            tg += 604800
        m = int((tg - leap + GPS_UNIX) // 60) * 60
        for r in arr:
            elev.setdefault((int(r["gnss"]), int(r["sv"]), m), []).append((r["elev"], r["azim"]))

    def elaz(g, s, m):
        v = elev.get((g, s, m))
        if not v:
            return None, None
        a = np.array(v, float)
        return float(np.median(a[:, 0])), float(np.median(a[:, 1]))

    # epoch grid for common-mode
    t_first = ep_t.min()
    grid_n = int(round((ep_t.max() - t_first) * FS)) + 1
    tm = ep_t[idx]
    keys = np.stack([meas["gnss"], meas["sv"], meas["sig"]], axis=1)
    uk = np.unique(keys, axis=0)

    sig_data = []                              # per signal: dict
    hp_cols = []                               # (grid_index_array, hp_metres) for CM
    for g, s, sg in uk:
        sel = np.flatnonzero((meas["gnss"] == g) & (meas["sv"] == s) & (meas["sig"] == sg))
        sel = sel[np.argsort(tm[sel], kind="stable")]
        t = tm[sel]
        keep = np.ones(len(t), bool)
        keep[1:] = np.diff(t) > 1e-6           # drop duplicate epochs (overlap)
        sel, t = sel[keep], t[keep]
        if len(t) < MIN_ARC_S * FS:
            continue
        m = meas[sel]
        lam, fmhz = wavelength(int(g), int(sg), int(m["freq"][0]))
        if lam is None:
            continue
        gi = np.round((t - t_first) * FS).astype(np.int64)
        idet = np.full(len(t), np.nan)
        hpm = np.full(len(t), np.nan)
        arc_id = np.full(len(t), -1)
        for a, (s0, e0) in enumerate(arcs_for(t, m["lock"].astype(np.int64), m["trk"])):
            if (t[e0 - 1] - t[s0]) < MIN_ARC_S:
                continue
            arc_id[s0:e0] = a
            edge = int(EDGE_S * FS)
            core = slice(s0 + edge, e0 - edge)
            cno = m["cno"][s0:e0].astype(float)
            pw = 10.0 ** (cno / 10.0)
            lp = sosfiltfilt(SOS_LP, pw)
            with np.errstate(divide="ignore", invalid="ignore"):
                idet[s0:e0] = pw / lp
            if (m["trk"][s0] & 0x02):
                ph = m["cp"][s0:e0] * lam                       # metres
                tt = t[s0:e0] - t[s0]
                ph = ph - np.polyval(np.polyfit(tt, ph, 3), tt)
                hpm[s0:e0] = sosfiltfilt(SOS_HP, ph)
            # discard filter edges
            idet[s0:s0 + edge] = np.nan; idet[e0 - edge:e0] = np.nan
            hpm[s0:s0 + edge] = np.nan; hpm[e0 - edge:e0] = np.nan
        sig_data.append(dict(g=int(g), s=int(s), sg=int(sg), lam=lam, f=fmhz, t=t, gi=gi,
                             cno=m["cno"].astype(float), trk=m["trk"], idet=idet, hpm=hpm,
                             arc=arc_id))

    # common mode: per-epoch median of HP phase (metres) over high-elevation signals
    stack_sum = []
    for sd in sig_data:
        mins = (np.floor((sd["t"] - leap + GPS_UNIX) / 60) * 60).astype(np.int64)
        sd["min"] = mins
        el = np.array([elaz(sd["g"], sd["s"], mm)[0] or -90 for mm in np.unique(mins)])
        elmap = dict(zip(np.unique(mins), el))
        sd["el_ok"] = np.array([elmap[mm] >= ELEV_MASK_CM for mm in mins])
    cm_vals = [[] for _ in range(1)]
    # build a dense matrix (signals x grid) only for CM-eligible samples
    elig = [sd for sd in sig_data if sd["g"] != 1]      # exclude SBAS (GEO, different clocks)
    M = np.full((len(elig), grid_n), np.nan, dtype=np.float32)
    for r, sd in enumerate(elig):
        ok = sd["el_ok"] & np.isfinite(sd["hpm"])
        M[r, sd["gi"][ok]] = sd["hpm"][ok]
    cnt = np.sum(np.isfinite(M), axis=0)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        cm = np.nanmedian(M, axis=0)
    cm[cnt < 4] = np.nan
    del M

    rows = []
    wts = now_iso()
    need = int(MIN_FRAC * 60 * FS)
    for sd in sig_data:
        for mm in np.unique(sd["min"]):
            if mm < h0 or mm >= h1:
                continue
            w = sd["min"] == mm
            iv = sd["idet"][w]
            iv = iv[np.isfinite(iv)]
            hp = sd["hpm"][w]
            cmv = cm[sd["gi"][w]]
            okp = np.isfinite(hp)
            okc = okp & np.isfinite(cmv)
            if len(iv) < need and okp.sum() < need:
                continue
            cno_mean = float(np.mean(sd["cno"][w]))
            s4 = s4n0 = s4nc = None
            if len(iv) >= need:
                s4 = float(np.sqrt(np.var(iv)) / np.mean(iv))
                snr = 10 ** (cno_mean / 10)
                s4n0 = float(np.sqrt(100.0 / snr * (1 + 500.0 / (19 * snr))))
                s4nc = float(np.sqrt(max(0.0, s4 * s4 - s4n0 * s4n0)))
            k2r = 2 * np.pi / sd["lam"]
            spr = float(np.std(hp[okp]) * k2r) if okp.sum() >= need else None
            sp = float(np.std((hp - cmv)[okc]) * k2r) if okc.sum() >= need else None
            ncm = None
            arcs = np.unique(sd["arc"][w])
            lock_full = int(len(arcs) == 1 and arcs[0] >= 0 and w.sum() >= need)
            hc = float(np.mean((sd["trk"][w] & 0x04) > 0))
            el, az = elaz(sd["g"], sd["s"], int(mm))
            # mean CM signal count over this minute
            ncm = float(np.mean(cnt[sd["gi"][w]]))
            rows.append((datetime.fromtimestamp(int(mm), timezone.utc).strftime("%Y-%m-%dT%H:%M:00+00:00"),
                         GN.get(sd["g"], str(sd["g"])), sd["s"], sd["sg"], sd["f"], el, az,
                         int(len(iv)), int(okc.sum() if sp is not None else okp.sum()), round(cno_mean, 2),
                         s4, s4n0, s4nc, spr, sp, round(ncm, 1), lock_full, int(np.sum(arcs >= 0)),
                         round(hc, 3), key, wts))
    conn.executemany("INSERT OR REPLACE INTO scint VALUES (" + ",".join("?" * 21) + ")", rows)
    if verbose:
        print(f"{key}: epochs {n_epochs}, missed {missed}, bad ck {bad}, signals {len(sig_data)}, rows {len(rows)}, "
              f"{time.time()-t0:.1f}s", flush=True)
    return dict(status="ok", epochs=n_epochs, missed=missed, rows=len(rows))


def compress(path):
    if path.endswith(".ubx") and os.path.exists(path):
        subprocess.run(["nice", "-n", "10", "ionice", "-c3", "gzip", "-6", "-f", path], check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hour", help="process just this hour YYYYMMDD_HH (reprocess)")
    ap.add_argument("--max", type=int, default=12, help="max hours per run")
    ap.add_argument("--no-compress", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    conn = sqlite3.connect(DB, timeout=60)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.executescript(SCHEMA)
    files = hour_files()
    done = {r[0] for r in conn.execute("SELECT hour_utc FROM processed_files WHERE status IN ('ok','empty')")}
    now = time.time()
    cur_key = key_of(now)
    if a.hour:
        todo = [a.hour]
    else:
        todo = []
        for k in sorted(files):
            if k in done or k >= cur_key:
                continue
            nxt = key_of(hour_start(k) + 3600)
            # wait for the first minutes of H+1 (filter padding) unless the gap is old
            if nxt in files or now > hour_start(k) + 3 * 3600:
                if nxt == cur_key and now < hour_start(nxt) + PAD_S + 60:
                    continue
                todo.append(k)
        todo = todo[:a.max]
    for k in todo:
        t0 = time.time()
        try:
            r = process_hour(k, files, conn, a.verbose)
            conn.execute("INSERT OR REPLACE INTO processed_files VALUES (?,?,?,?,?,?,?,?)",
                         (k, files.get(k), r["status"], r["epochs"], r["missed"], r["rows"],
                          round(time.time() - t0, 1), now_iso()))
            conn.commit()
            print(f"[{now_iso()}] {k} {r['status']} epochs={r['epochs']} missed={r['missed']} "
                  f"rows={r['rows']} {time.time()-t0:.0f}s", flush=True)
        except Exception as e:
            conn.rollback()
            conn.execute("INSERT OR REPLACE INTO processed_files VALUES (?,?,?,?,?,?,?,?)",
                         (k, files.get(k), f"error: {e}"[:200], None, None, None,
                          round(time.time() - t0, 1), now_iso()))
            conn.commit()
            print(f"[{now_iso()}] {k} ERROR {e}", file=sys.stderr, flush=True)
            continue
        # compress completed hours (but never the hour being written)
        if not a.no_compress:
            for kk in (key_of(hour_start(k) - 3600), k):
                p = files.get(kk)
                if p and kk < cur_key and p.endswith(".ubx") and kk in (done | {k}):
                    try:
                        compress(p)
                        files[kk] = p + ".gz"
                    except Exception as e:
                        print(f"[{now_iso()}] gzip {p} failed: {e}", file=sys.stderr, flush=True)
            done.add(k)
    # safety net: gzip any raw hour older than 6 h that is still uncompressed
    if not a.no_compress:
        for kk, p in hour_files().items():
            if p.endswith(".ubx") and now > hour_start(kk) + 6 * 3600:
                try:
                    compress(p)
                except Exception:
                    pass
    conn.close()


if __name__ == "__main__":
    main()
