"""Minimal IONEX reader for UQRG 15-minute maps (TEC maps only), with an .npz cache, plus helpers."""
import gzip, subprocess, numpy as np, pandas as pd
from pathlib import Path
U = Path(__file__).resolve().parents[1] / 'catalogues' / 'uqrg'; CACHE = U / 'npz'; CACHE.mkdir(exist_ok=True)
LATS = np.arange(87.5, -87.6, -2.5); LONS = np.arange(-180, 180.1, 5.0)
def fname(day):
    d = pd.Timestamp(day); return U / f"uqrg{d.dayofyear:03d}0.{d.year % 100:02d}i.Z"
def load_day(day):
    d = pd.Timestamp(day).floor('D'); c = CACHE / f"{d:%Y%m%d}.npz"
    if c.exists():
        z = np.load(c); return z['tec'].astype(np.float32)
    f = fname(d)
    if not f.exists(): return None
    txt = subprocess.run(['gzip', '-dc', str(f)], capture_output=True).stdout.decode('latin-1').splitlines()
    exp = -1; maps = {}; i = 0; cur = None; inmap = False
    while i < len(txt):
        l = txt[i]; lab = l[60:].strip()
        if lab == 'EXPONENT': exp = int(l[:6])
        elif lab == 'START OF TEC MAP': inmap = True; grid = np.full((len(LATS), len(LONS)), np.nan, np.float32)
        elif lab == 'END OF TEC MAP':
            inmap = False
            if cur is not None: maps[cur] = grid
        elif inmap and lab == 'EPOCH OF CURRENT MAP':
            p = l[:36].split(); cur = pd.Timestamp(int(p[0]), int(p[1]), int(p[2])) + pd.Timedelta(hours=int(p[3]), minutes=int(p[4]), seconds=int(p[5]))
        elif inmap and lab == 'LAT/LON1/LON2/DLON/H':
            lat = float(l[2:8]); vals = []
            while len(vals) < len(LONS):
                i += 1; vals += [int(v) for v in txt[i].split()]
            row = np.array(vals[:len(LONS)], np.float32); row[row == 9999] = np.nan
            k = int(round((87.5 - lat) / 2.5)); grid[k] = row * 10.0 ** exp
        elif lab == 'START OF RMS MAP': break
        i += 1
    tec = np.full((96, len(LATS), len(LONS)), np.nan, np.float32)
    for t, g in maps.items():
        s = int(round((t - d).total_seconds() / 900))
        if 0 <= s < 96: tec[s] = g
    np.savez_compressed(c, tec=tec.astype(np.float16)); return tec
def series(t0, t1, cache={}):
    """Return (times, maps) for 15-min slots in [t0, t1]."""
    days = pd.date_range(pd.Timestamp(t0).floor('D'), pd.Timestamp(t1).floor('D'))
    T, M = [], []
    for d in days:
        if d not in cache: cache[d] = load_day(d)
        x = cache[d]
        if x is None: continue
        for s in range(96):
            t = d + pd.Timedelta(minutes=15 * s)
            if t0 <= t <= t1: T.append(t); M.append(x[s])
    return T, (np.array(M) if M else None)
def sza_grid(t):
    t = pd.Timestamp(t); doy = t.dayofyear; hr = t.hour + t.minute / 60
    g = 2 * np.pi / 365 * (doy - 1 + (hr - 12) / 24)
    decl = 0.006918 - 0.399912 * np.cos(g) + 0.070257 * np.sin(g) - 0.006758 * np.cos(2 * g) + 0.000907 * np.sin(2 * g) - 0.002697 * np.cos(3 * g) + 0.00148 * np.sin(3 * g)
    eqt = 229.18 * (0.000075 + 0.001868 * np.cos(g) - 0.032077 * np.sin(g) - 0.014615 * np.cos(2 * g) - 0.040849 * np.sin(2 * g))
    LA, LO = np.meshgrid(np.radians(LATS), LONS, indexing='ij')
    ha = np.radians(((hr * 60 + eqt + 4 * LO) / 4 - 180))
    c = np.sin(LA) * np.sin(decl) + np.cos(LA) * np.cos(decl) * np.cos(ha); return np.degrees(np.arccos(np.clip(c, -1, 1)))
def maglat_grid(plat=80.7, plon=-72.7):
    LA, LO = np.meshgrid(np.radians(LATS), np.radians(LONS), indexing='ij'); p, q = np.radians(plat), np.radians(plon)
    return np.degrees(np.arcsin(np.sin(LA) * np.sin(p) + np.cos(LA) * np.cos(p) * np.cos(LO - q)))
MAG = maglat_grid(); W = np.cos(np.radians(LATS))[:, None] * np.ones((1, len(LONS)))   # area weights
BANDS = {'low (<20°)': (0, 20), 'mid (20-45°)': (20, 45), 'sub-auroral (45-60°)': (45, 60), 'high (>60°)': (60, 91)}
