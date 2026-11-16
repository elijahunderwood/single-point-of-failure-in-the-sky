"""rinex.py - read RINEX 3 and RINEX 2 observation files (GPS L1/L2 phase + LLI),
read RINEX 2 GPS broadcast navigation, and compute satellite elevation."""
import gzip, math, io
import numpy as np, pandas as pd
import hatanaka

def open_obs(path):
    """Return the observation file as text. Handles .crx.gz / .YYd.gz (Hatanaka),
    .rnx.gz / .YYo.gz (plain) and uncompressed files."""
    raw = open(path, "rb").read()
    if path.endswith(("crx.gz", "d.gz", ".crx", "d.Z")) or path[-3:-1].isdigit() and path.endswith("d"):
        return hatanaka.decompress(raw).decode("ascii", "replace")
    if path.endswith(".gz"): raw = gzip.decompress(raw)
    return raw.decode("ascii", "replace")

def header_info(text):
    """Station metadata from the header: version, marker, receiver, antenna, XYZ, interval."""
    info = dict(version=None, marker=None, receiver=None, antenna=None, xyz=None, interval=None)
    for line in text.splitlines():
        lab = line[60:].strip()
        if lab == "RINEX VERSION / TYPE": info["version"] = float(line[:9])
        elif lab == "MARKER NAME": info["marker"] = line[:60].strip()
        elif lab == "REC # / TYPE / VERS": info["receiver"] = line[20:40].strip()
        elif lab == "ANT # / TYPE": info["antenna"] = line[20:40].strip()
        elif lab == "APPROX POSITION XYZ": info["xyz"] = [float(line[i:i+14]) for i in (0, 14, 28)]
        elif lab == "INTERVAL": info["interval"] = float(line[:10])
        elif lab == "END OF HEADER": break
    return info

def _ts(y, mo, d, h, mi, s):
    return pd.Timestamp(year=y, month=mo, day=d, hour=h, minute=mi, tz="UTC").value / 1e9 + s

def read_obs(text):
    """GPS L1/L2 carrier phase (cycles), LLI flags and S1 from RINEX 2 or 3 text.
    Returns DataFrame [tsec, sv, L1, L2, lli, S1] and header info."""
    info = header_info(text)
    lines = text.splitlines()
    h_end = next(i for i, l in enumerate(lines) if "END OF HEADER" in l)
    if info["version"] >= 3: rows = _read3(lines, h_end)
    else: rows = _read2(lines, h_end)
    return pd.DataFrame(rows, columns=["tsec", "sv", "L1", "L2", "lli", "S1"]), info

def _pick(types, prefs):
    for p in prefs:
        if p in types: return types.index(p)
    return None

def _read3(lines, h_end):
    types, cont = [], False
    for line in lines[:h_end]:
        if line[60:].strip() == "SYS / # / OBS TYPES":
            if line[0] == "G": types = line[7:60].split(); cont = True
            elif line[0] == " " and cont: types += line[7:60].split()
            else: cont = False
    i1 = _pick(types, ["L1C", "L1W", "L1P"]); i2 = _pick(types, ["L2W", "L2P", "L2L", "L2X", "L2S", "L2C"])
    is1 = _pick(types, ["S1C", "S1W"])
    if i1 is None or i2 is None: raise ValueError(f"no GPS L1/L2 phase in {types}")
    rows, tsec = [], None
    def val(line, i):
        f = line[3+16*i:3+16*i+14]
        try: return float(f) if f.strip() else np.nan
        except ValueError: return np.nan
    def lli(line, i):
        c = line[3+16*i+14:3+16*i+15]
        return int(c) if c.strip().isdigit() else 0
    for line in lines[h_end+1:]:
        if not line: continue
        if line[0] == ">":
            p = line[2:29].split()
            tsec = _ts(*map(int, p[:5]), float(p[5])) if len(p) >= 6 and line[31:32] in ("0", "1", " ") else None
            continue
        if line[0] != "G" or tsec is None: continue
        rows.append((tsec, int(line[1:3]), val(line, i1), val(line, i2), lli(line, i1) | lli(line, i2),
                     val(line, is1) if is1 is not None else np.nan))
    return rows

def _read2(lines, h_end):
    types = []
    for line in lines[:h_end]:
        if line[60:].strip() == "# / TYPES OF OBSERV":
            types += line[6:60].split()
    i1 = _pick(types, ["L1"]); i2 = _pick(types, ["L2"]); is1 = _pick(types, ["S1"])
    if i1 is None or i2 is None: raise ValueError(f"no L1/L2 in {types}")
    nt = len(types); nlines = (nt + 4) // 5
    rows, k = [], h_end + 1
    while k < len(lines):
        ep = lines[k].ljust(80)
        try:
            flag = ep[28:29].strip() or "0"; ns = int(ep[29:32])
            y, mo, d, h, mi = (int(ep[i:i+3]) for i in (1, 4, 7, 10, 13)); s = float(ep[15:26])
        except ValueError:
            k += 1; continue                       # not an epoch line: resynchronise
        if flag not in ("0", "1"):
            k += 1 + ns; continue                  # event record: ns special lines follow
        sats = ep[32:68]; k += 1
        while len(sats.rstrip()) < 3*ns and k < len(lines):   # >12 satellites: continuation lines
            sats += lines[k].ljust(80)[32:68]; k += 1
        y += 2000 if y < 80 else 1900
        tsec = _ts(y, mo, d, h, mi, s)
        for j in range(ns):
            sid = sats[3*j:3*j+3]
            obs = "".join(lines[k+m].ljust(80) for m in range(nlines) if k + m < len(lines))
            k += nlines
            if sid[0] not in ("G", " "): continue
            def val(i):
                f = obs[16*i:16*i+14]
                try: return float(f) if f.strip() else np.nan
                except ValueError: return np.nan
            def lli(i):
                c = obs[16*i+14:16*i+15]; return int(c) if c.strip().isdigit() else 0
            rows.append((tsec, int(sid[1:3]), val(i1), val(i2), lli(i1) | lli(i2), val(is1) if is1 is not None else np.nan))
    return rows

# ---------------------------------------------------------------- orbits
def read_nav2(path):
    raw = open(path, "rb").read()
    if path.endswith(".gz"): raw = gzip.decompress(raw)
    L = raw.decode("ascii", "replace").splitlines()
    i = next(k for k, l in enumerate(L) if "END OF HEADER" in l) + 1
    f = lambda s: float(s.replace("D", "E")) if s.strip() else 0.0
    eph = []
    while i + 7 < len(L):
        blk = L[i:i+8]; i += 8
        try:
            prn = int(blk[0][:2])
            v = [f(blk[0][22+19*k:41+19*k]) for k in range(3)]
            for ln in blk[1:]: v += [f(ln[3+19*k:22+19*k]) for k in range(4)]
        except ValueError: continue
        eph.append(dict(prn=prn, crs=v[4], dn=v[5], m0=v[6], cuc=v[7], e=v[8], cus=v[9], sqa=v[10],
                        toe=v[11], cic=v[12], om0=v[13], cis=v[14], i0=v[15], crc=v[16], w=v[17],
                        omd=v[18], idot=v[19]))
    return pd.DataFrame(eph)

def sat_ecef(e, tow):
    """Satellite position (ECEF metres) from broadcast ephemeris, IS-GPS-200 equations."""
    mu, we = 3.986005e14, 7.2921151467e-5
    a = e["sqa"]**2; n = math.sqrt(mu/a**3) + e["dn"]
    tk = (tow - e["toe"] + 302400) % 604800 - 302400
    M = e["m0"] + n*tk; E = M
    for _ in range(10): E = M + e["e"]*math.sin(E)
    nu = math.atan2(math.sqrt(1-e["e"]**2)*math.sin(E), math.cos(E)-e["e"]); phi = nu + e["w"]
    s2, c2 = math.sin(2*phi), math.cos(2*phi)
    u = phi + e["cus"]*s2 + e["cuc"]*c2; r = a*(1-e["e"]*math.cos(E)) + e["crs"]*s2 + e["crc"]*c2
    inc = e["i0"] + e["cis"]*s2 + e["cic"]*c2 + e["idot"]*tk
    x, y = r*math.cos(u), r*math.sin(u)
    om = e["om0"] + (e["omd"]-we)*tk - we*e["toe"]
    return np.array([x*math.cos(om)-y*math.cos(inc)*math.sin(om), x*math.sin(om)+y*math.cos(inc)*math.cos(om), y*math.sin(inc)])

def ecef_to_geodetic(xyz):
    x, y, z = xyz; a, e2 = 6378137.0, 6.69437999014e-3
    lon = math.atan2(y, x); p = math.hypot(x, y); lat = math.atan2(z, p*(1-e2))
    for _ in range(5):
        N = a/math.sqrt(1-e2*math.sin(lat)**2); h = p/math.cos(lat) - N
        lat = math.atan2(z, p*(1-e2*N/(N+h)))
    return math.degrees(lat), math.degrees(lon), h

def elevation(rx, sat):
    lat, lon, _ = ecef_to_geodetic(rx); lat, lon = math.radians(lat), math.radians(lon)
    d = sat - np.asarray(rx)
    up = np.array([math.cos(lat)*math.cos(lon), math.cos(lat)*math.sin(lon), math.sin(lat)])
    return math.degrees(math.asin(np.dot(d, up)/np.linalg.norm(d)))

def add_elevations(obs, rx, eph, step=300):
    """Elevation for every observation: computed every `step` s and interpolated."""
    gps0 = pd.Timestamp(1980, 1, 6, tz="UTC").value / 1e9
    tow = (obs["tsec"] - gps0 + 18) % 604800          # UTC -> GPS time of week (18 leap s)
    el = np.full(len(obs), np.nan)
    for sv, idx in obs.groupby("sv").groups.items():
        E = eph[eph.prn == sv]
        if E.empty: continue
        toes = E.toe.to_numpy(); tw = tow.loc[idx].to_numpy()
        tg = np.arange(tw.min(), tw.max() + step, step)
        eg = [elevation(rx, sat_ecef(E.iloc[int(np.argmin(np.abs((t - toes + 302400) % 604800 - 302400)))], t)) for t in tg]
        el[obs.index.get_indexer(idx)] = np.interp(tw, tg, eg)
    return el

# ---------------------------------------------------------------- geomagnetic latitude
# IGRF-14 dipole coefficients for epoch 2025.0 (nT)
G10, G11, H11 = -29350.0, -1410.3, 4545.5
def geomag_lat(lat, lon):
    """Centred-dipole geomagnetic latitude (deg). Good to ~1-2 deg; AACGM is more exact."""
    b0 = math.sqrt(G10**2 + G11**2 + H11**2)
    m = np.array([-G11, -H11, -G10]) / b0            # unit vector to the north geomagnetic pole
    la, lo = math.radians(lat), math.radians(lon)
    r = np.array([math.cos(la)*math.cos(lo), math.cos(la)*math.sin(lo), math.sin(la)])
    return math.degrees(math.asin(float(np.dot(r, m))))
