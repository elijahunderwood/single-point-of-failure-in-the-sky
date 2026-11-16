"""swlib.py - shared functions for the independent space-weather reanalysis.

Everything here is written from scratch (numpy/pandas only) so each step can be
explained:  phase TEC -> arcs -> 30 s ROT -> 5 min ROTI -> network index.
"""
from pathlib import Path as _RepoPath
import os as _repo_os
REPO_ROOT = _RepoPath(_repo_os.environ.get('REPO_ROOT', _RepoPath(__file__).resolve().parents[2]))
import numpy as np, pandas as pd, math

DATA = str(_repo_os.environ.get('SPACE_WEATHER_DATA', REPO_ROOT / 'data' / 'raw'))
X = DATA + "/x"                     # extracted tar files
OUT = str(REPO_ROOT / 'analysis' / 'reanalysis' / 'output')
FIG = str(REPO_ROOT / 'analysis' / 'reanalysis' / 'figures')

F1, F2, F5 = 1575.42e6, 1227.60e6, 1176.45e6
C = 299792458.0
K_TEC = (F1**2 * F2**2) / (40.308 * (F1**2 - F2**2)) / 1e16   # TECU per metre of L1-L2 difference (~9.52)

# ---------------------------------------------------------------- loading
def load_home_csv(path):
    """Load a home-station per-second TEC export. Sorts by satellite & time
    (the raw exports are NOT in time order) and drops exact duplicate rows."""
    df = pd.read_csv(path)
    if df.empty:
        return df
    df["t"] = pd.to_datetime(df["ts_utc"], utc=True, format="ISO8601")
    n0 = len(df)
    df = df.drop_duplicates(subset=["sv", "t"])
    df.attrs["n_dupes"] = n0 - len(df)
    df = df.sort_values(["sv", "t"]).reset_index(drop=True)
    return df

# ---------------------------------------------------------------- ROT / ROTI
def compute_rot(df, elev_mask=20.0, base_s=30, gap_s=None, jump_tecu=None,
                rot_reject=10.0, slip_col="slip"):
    """Per-satellite Rate of TEC (TECU/min) on a `base_s` second base.

    Arc rules (a new arc starts when):
      * the receiver flags a slip (slip==1 / LLI), or
      * the time gap to the previous sample is > gap_s, or
      * the phase TEC jumps by more than jump_tecu between consecutive samples
        (a 1-cycle L1 slip is ~1.8 TECU, far bigger than real 1-s changes).
    Then: keep samples above the elevation mask, take one sample per base_s bin,
    difference consecutive bins in the same arc, convert to TECU/min, and reject
    |ROT| > rot_reject as residual slips.
    Returns a DataFrame [sv, t, rot, elev] and a dict of QC counts."""
    if gap_s is None: gap_s = 2.5        # home station logs at 1 Hz
    if jump_tecu is None: jump_tecu = 1.0
    out, qc = [], dict(samples=len(df), arcs=0, rot_total=0, rot_rejected=0)
    for sv, g in df.groupby("sv", sort=False):
        t = (g["t"] - pd.Timestamp(0, tz="UTC")).dt.total_seconds().to_numpy()
        tec = g["phase_tec"].to_numpy(float)
        el = g["elev_deg"].to_numpy(float)
        dt = np.diff(t, prepend=t[0] - 1e9)
        dtec = np.abs(np.diff(tec, prepend=np.nan))
        new = (dt > gap_s) | (dtec > jump_tecu) | np.isnan(tec)
        if slip_col in g:
            new |= g[slip_col].to_numpy() == 1
        arc = np.cumsum(new)
        keep = (el >= elev_mask) & ~np.isnan(tec)
        if keep.sum() < 3: continue
        b = pd.DataFrame({"t": t[keep], "tec": tec[keep], "el": el[keep], "arc": arc[keep]})
        b["bin"] = np.floor(b["t"] / base_s).astype(np.int64)
        b = b.groupby(["arc", "bin"], as_index=False).first()
        qc["arcs"] += b["arc"].nunique()
        same = (b["arc"].diff() == 0) & (b["bin"].diff() == 1)
        rot = b["tec"].diff() / b["t"].diff() * 60.0
        r = pd.DataFrame({"sv": sv, "t": b["t"], "rot": rot, "elev": b["el"]})[same.to_numpy()]
        qc["rot_total"] += len(r)
        bad = r["rot"].abs() > rot_reject
        qc["rot_rejected"] += int(bad.sum())
        out.append(r[~bad])
    rot = pd.concat(out, ignore_index=True) if out else pd.DataFrame(columns=["sv", "t", "rot", "elev"])
    return rot, qc

def compute_roti(rot, win_s=300, min_n=None, base_s=30):
    """ROTI = standard deviation of ROT inside each 5-minute window, per satellite.
    A window needs at least half its possible ROT samples."""
    if min_n is None: min_n = max(3, int(win_s / base_s / 2))
    r = rot.copy()
    r["win"] = (np.floor(r["t"] / win_s) * win_s).astype(np.int64)
    g = r.groupby(["win", "sv"])
    roti = g["rot"].agg(roti=lambda x: np.std(x, ddof=1), n="count").reset_index()
    roti["elev"] = g["elev"].mean().to_numpy()
    roti = roti[roti["n"] >= min_n]
    roti["t"] = pd.to_datetime(roti["win"], unit="s", utc=True)
    return roti

def network(roti, thr=0.5, min_sats=3):
    """Network index per window: median, 2nd-highest (needs 2 satellites to
    agree), max, number of satellites, fraction of satellites above thr."""
    def agg(x):
        v = np.sort(x.to_numpy())[::-1]
        return pd.Series(dict(roti_med=np.median(v), roti_2nd=v[1] if len(v) > 1 else np.nan,
                              roti_max=v[0], n_sats=len(v), frac_gt=np.mean(v > thr)))
    n = pd.DataFrame({t: agg(g) for t, g in roti.groupby("t")["roti"]}).T
    n.index = pd.to_datetime(n.index, utc=True)
    return n[n["n_sats"] >= min_sats]

# ---------------------------------------------------------------- S4 proxy from C/N0
def s4_from_cno(df, win_s=60, elev_mask=30.0, min_n=45, col="cno_l1"):
    """Amplitude-scintillation proxy from 1 Hz C/N0 (dB-Hz):
    intensity I = 10^(C/N0 / 10);  S4 = std(I)/mean(I) over 60 s.
    (Real S4 receivers use 50 Hz raw amplitude; 1 Hz integer-dB C/N0 is coarse.)"""
    d = df[df["elev_deg"] >= elev_mask].copy()
    d["I"] = 10 ** (d[col] / 10.0)
    d["win"] = ((d["t"] - pd.Timestamp(0, tz="UTC")).dt.total_seconds() // win_s * win_s).astype(np.int64)
    g = d.groupby(["win", "sv"])["I"]
    s = pd.DataFrame({"mean": g.mean(), "std": g.std(ddof=0), "n": g.count()}).reset_index()
    s = s[s["n"] >= min_n]
    s["s4"] = s["std"] / s["mean"]
    s["t"] = pd.to_datetime(s["win"], unit="s", utc=True)
    return s

# ---------------------------------------------------------------- statistics
def block_bootstrap_diff(a, b, stat=np.median, block=6, n=4000, seed=1):
    """Difference stat(a)-stat(b) with a 95% CI from a moving-block bootstrap.
    Blocks of `block` consecutive values keep the time-correlation (autocorrelation)
    so the CI is not falsely narrow.  a, b are time-ordered 1-D arrays."""
    rng = np.random.default_rng(seed)
    a, b = np.asarray(a, float), np.asarray(b, float)
    a, b = a[~np.isnan(a)], b[~np.isnan(b)]
    def resample(x):
        if len(x) <= block: return rng.choice(x, len(x))
        nb = int(np.ceil(len(x) / block))
        st = rng.integers(0, len(x) - block + 1, nb)
        return np.concatenate([x[s:s + block] for s in st])[:len(x)]
    d = np.array([stat(resample(a)) - stat(resample(b)) for _ in range(n)])
    return stat(a) - stat(b), np.percentile(d, 2.5), np.percentile(d, 97.5)

def wilson(k, n, z=1.96):
    """95% Wilson confidence interval for a proportion k/n (works for k=0)."""
    if n == 0: return (np.nan, np.nan, np.nan)
    p = k / n; d = 1 + z*z/n
    c = (p + z*z/(2*n)) / d; h = z*math.sqrt(p*(1-p)/n + z*z/(4*n*n)) / d
    return p, max(0, c - h), min(1, c + h)

def spearman_block_perm(x, y, block=12, n=4000, seed=2):
    """Spearman rho with a p-value from a block permutation (shifting y in blocks
    keeps its autocorrelation, so the test is honest for time series)."""
    from scipy.stats import spearmanr
    x, y = np.asarray(x, float), np.asarray(y, float)
    m = ~(np.isnan(x) | np.isnan(y)); x, y = x[m], y[m]
    rho = spearmanr(x, y).statistic
    rng = np.random.default_rng(seed)
    nb = int(np.ceil(len(y) / block)); blocks = [y[i*block:(i+1)*block] for i in range(nb)]
    null = []
    for _ in range(n):
        idx = rng.permutation(nb)
        null.append(spearmanr(x, np.concatenate([blocks[i] for i in idx])[:len(x)]).statistic)
    p = (np.sum(np.abs(null) >= abs(rho)) + 1) / (n + 1)
    return rho, p, len(x)

# ---------------------------------------------------------------- RINEX + orbits
def read_nav2(path):
    """Parse a RINEX-2 GPS broadcast navigation file into a list of ephemeris dicts."""
    L = open(path).read().splitlines()
    i = next(k for k, l in enumerate(L) if "END OF HEADER" in l) + 1
    f = lambda s: float(s.replace("D", "E")) if s.strip() else 0.0
    eph = []
    while i + 7 < len(L):
        blk = L[i:i+8]; i += 8
        prn = int(blk[0][:2])
        v = [f(blk[0][22+19*k:41+19*k]) for k in range(3)]
        for ln in blk[1:]:
            v += [f(ln[3+19*k:22+19*k]) for k in range(4)]
        eph.append(dict(prn=prn, crs=v[4], dn=v[5], m0=v[6], cuc=v[7], e=v[8], cus=v[9],
                        sqa=v[10], toe=v[11], cic=v[12], om0=v[13], cis=v[14], i0=v[15],
                        crc=v[16], w=v[17], omd=v[18], idot=v[19], week=v[21]))
    return eph

def sat_ecef(e, tow):
    """GPS satellite ECEF position (m) from broadcast ephemeris (IS-GPS-200)."""
    mu, we = 3.986005e14, 7.2921151467e-5
    a = e["sqa"]**2; n = math.sqrt(mu/a**3) + e["dn"]
    tk = tow - e["toe"]
    tk = (tk + 302400) % 604800 - 302400
    M = e["m0"] + n*tk; E = M
    for _ in range(10): E = M + e["e"]*math.sin(E)
    nu = math.atan2(math.sqrt(1-e["e"]**2)*math.sin(E), math.cos(E)-e["e"])
    phi = nu + e["w"]
    du = e["cus"]*math.sin(2*phi) + e["cuc"]*math.cos(2*phi)
    dr = e["crs"]*math.sin(2*phi) + e["crc"]*math.cos(2*phi)
    di = e["cis"]*math.sin(2*phi) + e["cic"]*math.cos(2*phi)
    u = phi+du; r = a*(1-e["e"]*math.cos(E))+dr; inc = e["i0"]+di+e["idot"]*tk
    x, y = r*math.cos(u), r*math.sin(u)
    om = e["om0"] + (e["omd"]-we)*tk - we*e["toe"]
    return np.array([x*math.cos(om)-y*math.cos(inc)*math.sin(om),
                     x*math.sin(om)+y*math.cos(inc)*math.cos(om), y*math.sin(inc)])

def elevation(rx, sat):
    x, y, z = rx
    lon = math.atan2(y, x); lat = math.atan2(z, math.hypot(x, y) * (1 - 0.00669438))
    d = sat - rx
    up = np.array([math.cos(lat)*math.cos(lon), math.cos(lat)*math.sin(lon), math.sin(lat)])
    return math.degrees(math.asin(np.dot(d, up)/np.linalg.norm(d)))

def read_rinex3_gps(path):
    """Minimal RINEX-3 observation reader: GPS L1 & L2 carrier phase (cycles),
    their LLI (loss-of-lock) flags and S1 signal strength, every epoch."""
    types, rx, rows = [], None, []
    with open(path) as fh:
        cont = False
        for line in fh:
            lab = line[60:].strip()
            if lab == "APPROX POSITION XYZ":
                rx = np.array([float(line[i:i+14]) for i in (0, 14, 28)])
            elif lab == "SYS / # / OBS TYPES":
                if line[0] == "G": types = line[7:60].split(); cont = True
                elif line[0] == " " and cont: types += line[7:60].split()
                else: cont = False
            elif lab == "END OF HEADER": break
        def pick(pref):
            for p in pref:
                if p in types: return types.index(p), p
            return None, None
        i1, n1 = pick(["L1C", "L1W"]); i2, n2 = pick(["L2W", "L2L", "L2X", "L2S"]); is1, _ = pick(["S1C", "S1W"])
        tsec = None
        for line in fh:
            if line[0] == ">":
                p = line[2:29].split()
                y, mo, d, h, mi = map(int, p[:5]); s = float(p[5])
                tsec = pd.Timestamp(year=y, month=mo, day=d, hour=h, minute=mi, tz="UTC").value/1e9 + s
                continue
            if line[0] != "G" or tsec is None: continue
            def val(i):
                f = line[3+16*i:3+16*i+14]
                return float(f) if f.strip() else np.nan
            def lli(i):
                c = line[3+16*i+14:3+16*i+15]
                return int(c) if c.strip().isdigit() else 0
            rows.append((tsec, int(line[1:3]), val(i1), val(i2), lli(i1) | lli(i2), val(is1) if is1 is not None else np.nan))
    df = pd.DataFrame(rows, columns=["tsec", "sv", "L1", "L2", "lli", "S1"])
    df.attrs.update(rx=rx, l1=n1, l2=n2)
    return df
