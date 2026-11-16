"""roti.py - the SAME TEC -> ROT -> ROTI pipeline used in the home-station reanalysis.

Settings (defaults in config/settings.yaml, identical to the reanalysis):
  elevation mask 20 deg, 30-s ROT base, 5-min ROTI windows, >= 5 ROT values per window,
  new arc on loss-of-lock flag / time gap / phase-TEC jump, |ROT| > 10 TECU/min rejected,
  'disturbed' threshold 0.5 TECU/min.
"""
import numpy as np, pandas as pd

F1, F2 = 1575.42e6, 1227.60e6
C = 299792458.0
K_TEC = (F1**2 * F2**2) / (40.308 * (F1**2 - F2**2)) / 1e16   # ~9.52 TECU per metre

def phase_tec(L1_cycles, L2_cycles):
    """Geometry-free carrier-phase TEC (TECU, arbitrary offset per arc)."""
    return K_TEC * (L1_cycles * C / F1 - L2_cycles * C / F2)

def compute_rot(df, elev_mask=20.0, base_s=30, gap_s=45.0, jump_tecu=5.0, rot_reject=10.0):
    """df columns: t (UTC datetime), sv, phase_tec, elev_deg, slip (0/1).
    Returns ROT table [sv, t(sec), rot TECU/min, elev] and QC counts."""
    out, qc = [], dict(samples=len(df), arcs=0, rot_total=0, rot_rejected=0)
    epoch = pd.Timestamp(0, tz="UTC")
    for sv, g in df.sort_values(["sv", "t"]).groupby("sv", sort=False):
        t = (g["t"] - epoch).dt.total_seconds().to_numpy()
        tec = g["phase_tec"].to_numpy(float); el = g["elev_deg"].to_numpy(float)
        dt = np.diff(t, prepend=t[0] - 1e9)
        dtec = np.abs(np.diff(tec, prepend=np.nan))
        new = (dt > gap_s) | (dtec > jump_tecu) | np.isnan(tec) | (g["slip"].to_numpy() == 1)
        arc = np.cumsum(new)
        keep = (el >= elev_mask) & ~np.isnan(tec)
        if keep.sum() < 3: continue
        b = pd.DataFrame({"t": t[keep], "tec": tec[keep], "el": el[keep], "arc": arc[keep]})
        b["bin"] = np.floor(b["t"] / base_s).astype(np.int64)
        b = b.groupby(["arc", "bin"], as_index=False).first()
        qc["arcs"] += b["arc"].nunique()
        same = ((b["arc"].diff() == 0) & (b["bin"].diff() == 1)).to_numpy()
        rot = (b["tec"].diff() / b["t"].diff() * 60.0).to_numpy()
        r = pd.DataFrame({"sv": sv, "t": b["t"].to_numpy(), "rot": rot, "elev": b["el"].to_numpy()})[same]
        qc["rot_total"] += len(r)
        bad = r["rot"].abs() > rot_reject
        qc["rot_rejected"] += int(bad.sum())
        out.append(r[~bad])
    rot = pd.concat(out, ignore_index=True) if out else pd.DataFrame(columns=["sv", "t", "rot", "elev"])
    return rot, qc

def compute_roti(rot, win_s=300, base_s=30, min_n=None):
    """ROTI = standard deviation of ROT in each 5-min window per satellite."""
    if min_n is None: min_n = max(3, int(win_s / base_s / 2))
    if rot.empty: return pd.DataFrame(columns=["win", "sv", "roti", "n", "elev"])
    r = rot.copy(); r["win"] = (np.floor(r["t"].astype(float) / win_s) * win_s).astype(np.int64)
    g = r.groupby(["win", "sv"])
    ro = g["rot"].agg(roti=lambda x: np.std(x, ddof=1), n="count").reset_index()
    ro["elev"] = g["elev"].mean().to_numpy()
    return ro[ro["n"] >= min_n].reset_index(drop=True)

def network(ro, thr=0.5, min_sats=3):
    """Per 5-min window: max, 2nd-highest (robust), median, mean, n_sats, fraction > thr."""
    rows = []
    for w, x in ro.groupby("win")["roti"]:
        v = np.sort(x.to_numpy())[::-1]
        if len(v) < min_sats: continue
        rows.append((w, v[0], v[1], float(np.median(v)), float(np.mean(v)), len(v), float(np.mean(v > thr))))
    return pd.DataFrame(rows, columns=["win", "roti_max", "roti_2nd", "roti_med", "roti_mean", "n_sats", "frac_gt"])
