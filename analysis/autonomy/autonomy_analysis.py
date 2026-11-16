"""
autonomy_analysis.py  -  first-pass link between measured ionospheric disturbance (ROTI)
and the positioning tolerance of autonomous platforms.

Project: "Space Weather as a Common-Mode Threat to Satellite Navigation and Satellite Broadband"
Author of the analysis: Elijah Underwood (code drafted with AI assistance, see AI declaration).

INPUTS (all read-only)
  data/storm_20261010/global_roti.db   global_logger database: 17 IGS stations + HOME,
                                                 30-s ROT base, 5-min ROTI, 20 deg mask, GFZ Kp
  data/storm_20261010/tec_quiet.csv    home receiver, 2 Oct 2026 (quiet control), 1 Hz
  data/storm_20261010/tec_storm.csv    home receiver, 10-11 Oct 2026 (G3 storm), 1 Hz
  SN_ms_tot_V2.0.csv                             WDC-SILSO 13-month smoothed sunspot number

METHOD (every assumption is stated here and in the report)
  For each station and 5-minute window we have per-satellite ROTI (TECU/min).
  P1  Fix-loss proxy (carrier-phase users: RTK, network RTK, PPP-RTK)
      S02 = fraction of tracked satellites with ROTI > 0.2 TECU/min.
      Zhang et al. (2025, Satellite Navigation, doi:10.1186/s43020-025-00179-4), using the SAME ROTI
      definition (30-s ROT, 5-min window), found the network-RTK ambiguity fixing rate falls to
      ~50-70 % when 40-60 % of satellites exceed 0.2 TECU/min.  We flag "fix at risk" when S02 >= 0.40.
  P2  Network-RTK residual ionosphere (Zhang et al. 2025, eq. 24):
      eps_cm = 0.31 * S02[%] + 0.20  (hourly RMS interpolation error, cm, ~16 km rover distance)
  P3  Gradient proxy for single-base RTK:
      spatial gradient g ~ ROTI / v_eff (frozen-flow assumption).  v_eff is CALIBRATED so that the
      quiet-time (Kp<=2) hourly 95th percentile at Brussels/Herstmonceux equals Wanninger's (2004)
      quiet Central-European I95 of 2 ppm (2 mm per km on L1).  Differential L1 delay over a
      baseline b:  d_mm = g[mm/km] * b[km].  1 TECU = 162.4 mm of L1 delay (40.3e16/f1^2).
  Platform "exceeds tolerance" in a window if (P1 fix-loss AND the float-solution error assumed
  0.3 m exceeds tolerance)  OR  (its relevant residual error > tolerance).
  Exceedance fractions are reported per station as a function of Kp (GFZ, 3-hourly).
  NOTE: the archive is storm-weighted, so fractions are CONDITIONAL ON Kp, not annual averages.
"""
from pathlib import Path as _RepoPath
import os as _repo_os
REPO_ROOT = _RepoPath(_repo_os.environ.get('REPO_ROOT', _RepoPath(__file__).resolve().parents[2]))
import sqlite3, json, sys, math
from pathlib import Path
import numpy as np, pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap

sys.path.insert(0, str(REPO_ROOT / 'analysis' / 'global_logger'))
from global_logger import roti as R

OUT = (REPO_ROOT / 'analysis' / 'autonomy'); FIG = OUT / "figures"; AN = OUT / "analysis"
DB = str(REPO_ROOT / 'data' / 'storm_20261010' / 'global_roti.db')
TEC_Q = str(REPO_ROOT / 'data' / 'storm_20261010' / 'tec_quiet.csv')
TEC_S = str(REPO_ROOT / 'data' / 'storm_20261010' / 'tec_storm.csv')
F1 = 1575.42e6
MM_PER_TECU = 40.3e16 / F1**2 * 1000          # 162.4 mm of L1 delay per TECU
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.grid": True, "grid.alpha": .3,
                     "figure.dpi": 150, "savefig.bbox": "tight"})

# ----------------------------------------------------------------------------- platforms
# tolerance = 95 % horizontal accuracy requirement (m); al = alert limit (m) where published
PLATFORMS = [
  # key, label, tolerance_m, alert_limit_m, technique, baseline_km, source
  ("survey_drone", "Survey / mapping drone (RTK)", 0.015, None, "RTK", 5,  "DJI (n.d.): 1 cm + 1 ppm H; 5 km baseline -> 1.5 cm"),
  ("tractor",      "Agricultural auto-steer (RTK)", 0.025, None, "RTK", 10, "John Deere (n.d.): +/-2.5 cm pass-to-pass"),
  ("car_local",    "Self-driving car, local streets", 0.10, 0.29, "NRTK", None, "Reid et al. (2019)"),
  ("docking",      "Automatic ship docking", 0.10, 0.25, "RTK", 20, "IMO A.915(22)"),
  ("car_freeway",  "Self-driving car, motorway", 0.20, 0.57, "NRTK", None, "Reid et al. (2019)"),
  ("drone_land",   "Delivery drone, landing", 1.0, None, "metre", None, "EUSPA (2023): <1 m"),
  ("drone_cruise", "Delivery drone, en route", 2.0, None, "metre", None, "EUSPA (2023): 2-5 m"),
  ("harbour",      "Ship, harbour approach", 10.0, 25.0, "metre", None, "IMO A.1046(27) / A.915(22)"),
  ("lpv200",       "Aircraft LPV-200 approach (benchmark)", 16.0, 40.0, "metre", None, "ICAO Annex 10 (HAL 40 m)"),
]
FLOAT_ERR_M = 0.30          # assumed horizontal error when RTK drops from 'fixed' to 'float' (decimetres; Navipedia)
FIX_LOSS_S02 = 0.40         # Zhang et al. 2025
NOMINAL_RTK_M = 0.01        # quiet RTK noise floor (1 cm)

KP_BINS = [0, 3, 5, 6, 7, 8, 9.01]
KP_LABELS = ["0-2.7", "3-4.7", "5-5.7 (G1)", "6-6.7 (G2)", "7-7.7 (G3)", "8-9 (G4-G5)"]
KP_LABELS = ["Kp 0-3", "Kp 3-5", "Kp 5 (G1)", "Kp 6 (G2)", "Kp 7 (G3)", "Kp 8-9 (G4/G5)"]

def load():
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    st = pd.read_sql("select * from stations", c)
    ro = pd.read_sql("select window_start, station, sv, roti, mean_elev from roti", c)
    net = pd.read_sql("select * from roti_network", c)
    kp = pd.read_sql("select ts_utc, kp, status from kp_index", c)
    return st, ro, net, kp

def home_extra():
    """Run the home receiver's 2 Oct and 10-11 Oct files through the SAME ROTI code (20 and 30 deg masks)."""
    out = {}
    for mask in (20, 30):
        rows = []
        for f in (TEC_Q, TEC_S):
            d = pd.read_csv(f, usecols=["ts_utc", "sv", "elev_deg", "phase_tec", "slip"])
            d["t"] = pd.to_datetime(d.ts_utc, utc=True, format="ISO8601")
            d = d.drop_duplicates(subset=["sv", "t"])
            rot, qc = R.compute_rot(d, elev_mask=mask, base_s=30, gap_s=2.5, jump_tecu=1.0, rot_reject=10.0)
            r = R.compute_roti(rot, win_s=300, base_s=30)
            r["window_start"] = pd.to_datetime(r.win, unit="s", utc=True).dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")
            rows.append(r)
        r = pd.concat(rows)
        out[mask] = pd.DataFrame({"window_start": r.window_start, "station": "HOME", "sv": r.sv,
                                  "roti": r.roti, "mean_elev": r.elev})
    return out

def denoise_home(rh, kp, quiet_kp=2.0):
    """Quadrature removal of the home receiver's own quiet-time ROTI floor, per 5-degree elevation bin.
    floor(elev) = median per-satellite ROTI over Kp<=quiet_kp windows; roti_c = sqrt(max(roti^2 - floor^2, 0)).
    Median (not mean) is used so that the floor estimates receiver/multipath noise rather than removing
    genuine quiet-time irregularity entirely. Returned as pseudo-station 'HOMEc'."""
    r = rh.copy()
    r = attach_kp(r, kp)
    r["eb"] = (r.mean_elev // 5) * 5
    fl = r[r.kp <= quiet_kp].groupby("eb").roti.median()
    f = r.eb.map(fl).fillna(fl.median())
    r["roti"] = np.sqrt(np.clip(r.roti ** 2 - f ** 2, 0, None))
    r["station"] = "HOMEc"
    return r[["window_start", "station", "sv", "roti", "mean_elev"]], fl

def per_window(ro, min_sats=3):
    g = ro.groupby(["station", "window_start"])["roti"]
    w = pd.DataFrame({"n": g.size(), "s02": g.apply(lambda x: np.mean(x > 0.2)),
                      "s05": g.apply(lambda x: np.mean(x > 0.5)), "s10": g.apply(lambda x: np.mean(x > 1.0)),
                      "r2nd": g.apply(lambda x: np.sort(x.values)[-2] if len(x) > 1 else np.nan),
                      "p95": g.quantile(0.95)}).reset_index()
    return w[w.n >= min_sats]

def attach_kp(w, kp):
    kp = kp.copy(); kp["t"] = pd.to_datetime(kp.ts_utc, utc=True); kp = kp.set_index("t")["kp"].sort_index()
    t = pd.to_datetime(w.window_start, utc=True)
    blk = t.dt.floor("3h")
    w["t"] = t; w["kp"] = blk.map(kp).values
    w["kpbin"] = pd.cut(w.kp, KP_BINS, right=False, labels=KP_LABELS)
    return w

def calibrate_v(w):
    """v_eff (m/s) such that quiet (Kp<=2) hourly P95 of per-satellite ROTI at BRUX+HERS -> 2 ppm (Wanninger 2004)."""
    q = w[(w.station.isin(["BRUX", "HERS"])) & (w.kp <= 2)].copy()
    q["hour"] = q.t.dt.floor("1h")
    hourly_p95 = q.groupby(["station", "hour"])["p95"].max()     # 95th pct of satellites, max over the hour
    r_quiet = float(np.median(hourly_p95))
    # g[mm/km] = MM_PER_TECU * ROTI[TECU/min] / (v[m/s]*0.06 km/min) = 2  ->  v = MM_PER_TECU*r/(0.12)
    v = MM_PER_TECU * r_quiet / (2.0 * 0.06)
    return v, r_quiet, len(hourly_p95)

def errors(w, v_eff):
    w = w.copy()
    w["g_ppm"] = MM_PER_TECU * w.p95 / (v_eff * 0.06)          # mm per km (=ppm) on L1, 95th pct satellite
    w["eps_nrtk_m"] = (0.31 * 100 * w.s02 + 0.20) / 100.0         # Zhang et al. 2025 eq. 24
    w["fixloss"] = w.s02 >= FIX_LOSS_S02
    for key, lab, tol, al, tech, b, src in PLATFORMS:
        if tech == "RTK":
            e = np.sqrt(NOMINAL_RTK_M**2 + (w.g_ppm * b / 1000.0)**2)
            e = np.where(w.fixloss, np.maximum(e, FLOAT_ERR_M), e)
        elif tech == "NRTK":
            e = np.sqrt(NOMINAL_RTK_M**2 + w.eps_nrtk_m**2)
            e = np.where(w.fixloss, np.maximum(e, FLOAT_ERR_M), e)
        else:   # metre-level users: these ROTI proxies cannot predict metre errors -> not modelled
            e = np.full(len(w), np.nan)
        w["err_" + key] = e
        w["exc_" + key] = (e > tol) if tech != "metre" else np.nan
    return w

def exceed_table(w, keys, stations):
    rows = []
    for s in stations:
        ws = w[w.station == s]
        for b in KP_LABELS:
            x = ws[ws.kpbin == b]
            r = {"station": s, "kpbin": b, "n_windows": len(x), "hours": len(x) * 5 / 60}
            for k in keys:
                r[k] = float(x["exc_" + k].mean()) if len(x) else np.nan
            r["fixloss"] = float(x.fixloss.mean()) if len(x) else np.nan
            rows.append(r)
    return pd.DataFrame(rows)

def logit_fit(x, y, iters=60):
    X = np.c_[np.ones_like(x), x]; b = np.zeros(2)
    for _ in range(iters):
        p = 1 / (1 + np.exp(-X @ b)); W = p * (1 - p) + 1e-9
        b = b + np.linalg.solve(X.T @ (X * W[:, None]) + 1e-6 * np.eye(2), X.T @ (y - p))
    return b

def kp50(w, station, key, nboot=1000, seed=1):
    """Kp at which P(exceed) = 0.5, from a logistic fit on 3-hour blocks (fraction exceeding > 0.5 = 'block exceeds')."""
    x = w[w.station == station].copy(); x["blk"] = x.t.dt.floor("3h")
    b = x.groupby("blk").agg(kp=("kp", "first"), f=("exc_" + key, "mean")).dropna()
    xs, ys = b.kp.values, (b.f.values > 0.5).astype(float)
    if ys.sum() < 2: return None
    beta = logit_fit(xs, ys); k50 = -beta[0] / beta[1]
    rng = np.random.default_rng(seed); bs = []
    for _ in range(nboot):
        i = rng.integers(0, len(xs), len(xs))
        if ys[i].sum() < 1 or ys[i].sum() == len(i): continue
        bb = logit_fit(xs[i], ys[i])
        if bb[1] > 0: bs.append(-bb[0] / bb[1])
    lo, hi = np.percentile(bs, [2.5, 97.5])
    return {"kp50": float(k50), "ci95": [float(lo), float(hi)], "n_blocks": int(len(xs)), "n_exceed_blocks": int(ys.sum())}

# ============================================================================== main
def main():
    st, ro, net, kp = load()
    hx = home_extra()
    # HOME: keep the reanalysis windows already in the db (Aug-5 Oct) and add 2 Oct + 10-11 Oct
    ro_h20 = pd.concat([ro[ro.station == "HOME"], hx[20]]).drop_duplicates(["window_start", "sv"], keep="last")
    ro_hc, home_floor = denoise_home(ro_h20, kp)
    ro_all = pd.concat([ro[ro.station != "HOME"], ro_h20, ro_hc])
    w = per_window(ro_all)
    w = attach_kp(w, kp)
    w = w.dropna(subset=["kp"])
    v_eff, r_quiet, nq = calibrate_v(w)
    w = errors(w, v_eff)
    # HOME self-calibration: the low-cost receiver's p95 tail is noise-dominated, so the IGS-based v_eff
    # cannot be applied to it.  Map ITS OWN quiet (Kp<=2) hourly P95 to the same 2 ppm, i.e. measure the
    # home disturbance RELATIVE to home quiet conditions.  Pseudo-station 'HOMEs'.
    hc = w[w.station == "HOMEc"].copy(); q = hc[hc.kp <= 2].copy(); q["hour"] = q.t.dt.floor("1h")
    r_home = float(np.median(q.groupby("hour")["p95"].max())); v_home = MM_PER_TECU * r_home / 0.12
    hs = errors(hc, v_home); hs["station"] = "HOMEs"
    w = pd.concat([w, hs], ignore_index=True)

    # home 30-degree-mask sensitivity (10-11 Oct + 2 Oct only)
    w30 = errors(attach_kp(per_window(hx[30]), kp).dropna(subset=["kp"]), v_eff)
    w20h = w[(w.station == "HOME") & (w.window_start >= "2026-10-02")]

    order = ["THU2", "NYA1", "TRO1", "KIRU", "YELL", "REYK", "HOME", "HOMEc", "HOMEs", "MORP", "HERS", "BRUX", "PIE1", "MAS1",
             "KOUR", "BOGT", "NKLG", "DARW", "HOB2", "MCM4"]
    keys = [p[0] for p in PLATFORMS if p[4] != "metre"]
    tab = exceed_table(w, keys, order)
    tab.to_csv(AN / "exceedance_by_station_kp.csv", index=False)

    # sensitivity of the tractor result to baseline length and to the v_eff calibration
    sens = []
    for stn in ["MORP", "HERS", "TRO1"]:
        ws = w[w.station == stn]
        for b in (2, 5, 10, 20):
            for vf in (0.5, 1.0, 2.0):
                g = MM_PER_TECU * ws.p95 / (v_eff * vf * 0.06)
                e = np.sqrt(NOMINAL_RTK_M**2 + (g * b / 1000.0)**2)
                e = np.where(ws.fixloss, np.maximum(e, FLOAT_ERR_M), e)
                ex = pd.Series(e > 0.025, index=ws.index)
                for kb in KP_LABELS:
                    m = (ws.kpbin == kb).values
                    if m.sum() >= 12:
                        sens.append({"station": stn, "baseline_km": b, "v_factor": vf, "kpbin": kb,
                                     "tractor_exceed": float(ex[m].mean()), "n": int(m.sum())})
    sens = pd.DataFrame(sens); sens.to_csv(AN / "sensitivity_tractor.csv", index=False)

    # quiet-noise check for HOME vs MORP (Kp<=2 windows)
    noise = w[w.kp <= 2].groupby("station").agg(median_p95=("p95", "median"), s02=("s02", "mean"),
                                                 n=("n", "size")).round(3)

    # Kp50 thresholds
    k50 = {}
    for s in ["MORP", "HERS", "BRUX", "TRO1", "KIRU", "PIE1", "HOMEs"]:
        k50[s] = {k: kp50(w, s, k) for k in ["tractor", "car_freeway"]}

    # common-mode: simultaneity across the three NW-European stations
    eu = w[w.station.isin(["MORP", "HERS", "BRUX"])].pivot_table(index="window_start", columns="station",
                                                                  values="exc_tractor", aggfunc="first").dropna().astype(float)
    cm = {"n_windows": int(len(eu)),
          "p_MORP": float(eu.MORP.mean()), "p_HERS": float(eu.HERS.mean()), "p_BRUX": float(eu.BRUX.mean()),
          "p_HERS_given_MORP": float(eu.HERS[eu.MORP == 1].mean()) if eu.MORP.sum() else None,
          "p_BRUX_given_MORP": float(eu.BRUX[eu.MORP == 1].mean()) if eu.MORP.sum() else None,
          "p_all3": float((eu.sum(axis=1) == 3).mean()),
          "p_all3_if_independent": float(eu.MORP.mean() * eu.HERS.mean() * eu.BRUX.mean()),
          "phi_MORP_HERS": float(np.corrcoef(eu.MORP.astype(float).values, eu.HERS.astype(float).values)[0, 1])}
    # same for 'auroral' Scandinavia
    sc = w[w.station.isin(["TRO1", "KIRU"])].pivot_table(index="window_start", columns="station",
                                                         values="exc_tractor", aggfunc="first").dropna().astype(float)
    cm["scandinavia"] = {"n": int(len(sc)), "p_TRO1": float(sc.TRO1.mean()), "p_KIRU": float(sc.KIRU.mean()),
                         "p_both": float((sc.sum(axis=1) == 2).mean()),
                         "p_both_if_independent": float(sc.TRO1.mean() * sc.KIRU.mean()),
                         "p_KIRU_given_TRO1": float(sc.KIRU[sc.TRO1 == 1].mean())}

    # event summaries
    def ev(day0, day1, stations):
        x = w[(w.window_start >= day0) & (w.window_start < day1) & w.station.isin(stations)]
        return x.groupby("station").agg(kp_max=("kp", "max"), hours=("n", lambda v: len(v) * 5 / 60),
                    tractor=("exc_tractor", "mean"), survey_drone=("exc_survey_drone", "mean"),
                    car_local=("exc_car_local", "mean"), car_freeway=("exc_car_freeway", "mean"),
                    docking=("exc_docking", "mean"), fixloss=("fixloss", "mean"),
                    g_ppm_p95=("g_ppm", lambda v: float(np.percentile(v, 95)))).round(3)
    evs = {"oct2026_G3_10-11Oct": ev("2026-10-10T12", "2026-10-11T18", ["HOME", "HOMEc", "HOMEs", "MORP", "HERS", "BRUX", "TRO1", "KIRU"]),
           "quiet_2Oct2026": ev("2026-10-02", "2026-10-03", ["HOME", "HOMEc", "HOMEs", "MORP", "HERS", "BRUX", "TRO1", "KIRU"]),
           "may2024_G5_10-11May": ev("2024-05-10T12", "2024-05-11T12", ["MORP", "HERS", "BRUX", "TRO1", "KIRU", "PIE1", "YELL"]),
           "quiet_22May2024": ev("2024-05-22", "2024-05-23", ["MORP", "HERS", "BRUX", "TRO1", "KIRU", "PIE1", "YELL"])}

    home_sens = {"mask20": {"tractor": float(w20h.exc_tractor.mean()), "s02": float(w20h.s02.mean()),
                            "car_freeway": float(w20h.exc_car_freeway.mean()), "n": int(len(w20h)),
                            "median_sats": float(w20h.n.median())},
                 "mask30": {"tractor": float(w30.exc_tractor.mean()), "s02": float(w30.s02.mean()),
                            "car_freeway": float(w30.exc_car_freeway.mean()), "n": int(len(w30)),
                            "median_sats": float(w30.n.median())}}
    res = {"v_eff_m_s": v_eff, "v_home_selfcal_m_s": v_home, "home_quiet_r95": r_home, "quiet_r95_TECU_min": r_quiet, "n_quiet_hours": nq, "mm_per_tecu": MM_PER_TECU,
           "kp50": k50, "home_floor_by_elev": {str(k): float(v) for k, v in home_floor.items()}, "common_mode": cm, "home_mask_sensitivity": home_sens,
           "noise_floor_kp_le2": noise.to_dict(orient="index"),
           "events": {k: v.to_dict(orient="index") for k, v in evs.items()},
           "n_windows_total": int(len(w)), "stations": order,
           "assumptions": {"float_err_m": FLOAT_ERR_M, "fixloss_s02": FIX_LOSS_S02, "nominal_rtk_m": NOMINAL_RTK_M,
                           "platforms": [dict(zip(["key", "label", "tol_m", "al_m", "tech", "baseline_km", "source"], p)) for p in PLATFORMS]}}
    with open(AN / "results_autonomy.json", "w") as f: json.dump(res, f, indent=1, default=str)
    w.to_csv(AN / "windows_with_errors.csv.gz", index=False, compression="gzip")
    make_figures(w, tab, st, v_eff, res)
    print(json.dumps({k: res[k] for k in ["v_eff_m_s", "quiet_r95_TECU_min", "n_quiet_hours", "kp50", "common_mode", "home_mask_sensitivity"]}, indent=1, default=str))
    print(noise)
    for k, v in evs.items(): print("\n==", k); print(v)
    return w, tab, res

# ============================================================================== figures
def make_figures(w, tab, st, v_eff, res):
    # ---- Fig A: tolerance ladder
    fig, ax = plt.subplots(figsize=(8, 4.6))
    labs = [p[1] for p in PLATFORMS]; tol = [p[2] for p in PLATFORMS]; al = [p[3] for p in PLATFORMS]
    y = np.arange(len(PLATFORMS))
    cols = ["#1b7837" if p[4] == "RTK" else "#5aae61" if p[4] == "NRTK" else "#9970ab" for p in PLATFORMS]
    ax.barh(y, tol, color=cols, alpha=.85, label="95 % accuracy requirement")
    for yi, a in zip(y, al):
        if a: ax.plot(a, yi, "k|", ms=14, mew=2)
    ax.plot([], [], "k|", ms=10, mew=2, label="Alert limit (integrity)")
    ax.set_xscale("log"); ax.set_yticks(y); ax.set_yticklabels(labs); ax.invert_yaxis()
    ax.set_xlabel("Horizontal position error that can be tolerated (m, log scale)")
    for v, t in [(0.162, "1 TECU of unmodelled\nL1 delay = 16 cm"), (5, "Typical stand-alone\nGPS (~5 m)")]:
        ax.axvline(v, color="0.4", ls="--", lw=1); ax.text(v * 1.08, -0.55, t, fontsize=8, color="0.3", va="bottom")
    ax.set_title("How much error can each autonomous platform tolerate?")
    ax.set_ylim(len(PLATFORMS) - .5, -1.6)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.13), ncol=2, fontsize=8)
    fig.savefig(FIG / "fig1_tolerance_ladder.png"); plt.close(fig)

    # ---- Fig B: exceedance vs Kp, tractor and freeway car, selected stations
    sel = [("TRO1", "Tromsø 67.5°"), ("KIRU", "Kiruna 65.6°"), ("MORP", "Morpeth 57.2° (Belfast-latitude proxy)"),
           ("HOMEs", "Belfast home station 57.3° (self-calibrated)"), ("HERS", "Herstmonceux 52.7°"), ("BRUX", "Brussels 52.0°"),
           ("PIE1", "Pie Town, USA 41.6°"), ("KOUR", "Kourou 13.9°")]
    colors = ["#762a83", "#c2a5cf", "#1b7837", "#e08214", "#4393c3", "#92c5de", "#8c510a", "#bababa"]
    fig, axs = plt.subplots(1, 2, figsize=(11, 4.4), sharey=True)
    for ax, key, title in [(axs[0], "tractor", "RTK auto-steer tractor (tolerance 2.5 cm)"),
                           (axs[1], "car_freeway", "Self-driving car, motorway (0.20 m, 95 %)")]:
        for (s, lab), c in zip(sel, colors):
            t = tab[(tab.station == s) & (tab.n_windows >= 12)]
            ax.plot([KP_LABELS.index(b) for b in t.kpbin], 100 * t[key], "o-", color=c, label=lab, lw=2 if s in ("MORP", "HOMEs") else 1.2,
                    ms=5, ls="--" if s == "HOMEs" else "-")
            # map index to label positions
        ax.set_xticks(range(len(KP_LABELS))); ax.set_xticklabels(KP_LABELS, rotation=30, ha="right")
        ax.set_title(title, fontsize=10); ax.set_ylim(-3, 103)
    axs[0].set_ylabel("Share of 5-min windows beyond tolerance (%)")
    h, l = axs[0].get_legend_handles_labels()
    fig.legend(h, l, fontsize=8, loc="lower center", ncol=4, bbox_to_anchor=(0.5, -0.13))
    fig.suptitle("Estimated time out of tolerance versus geomagnetic activity (geomagnetic latitude in legend)", fontsize=11)
    fig.text(0.5, -0.18, "Bins with fewer than 1 hour of data omitted. Home station only reaches Kp 7 (10 Oct 2026 G3). "
             "Proxy model: Zhang et al. (2025) fix-loss rule + calibrated gradient model; see Methods.", ha="center", fontsize=7.5)
    fig.savefig(FIG / "fig2_exceedance_vs_kp.png"); plt.close(fig)

    # ---- Fig C: heat map station x Kp for tractor
    piv = tab.pivot(index="station", columns="kpbin", values="tractor").reindex(res["stations"])[KP_LABELS]
    nw = tab.pivot(index="station", columns="kpbin", values="n_windows").reindex(res["stations"])[KP_LABELS]
    piv = piv.where(nw >= 12)
    mlat = st.set_index("station").geomag_lat.to_dict(); mlat["HOME"] = 57.3; mlat["HOMEc"] = 57.3; mlat["HOMEs"] = 57.3
    fig, ax = plt.subplots(figsize=(7.6, 7))
    cmap = LinearSegmentedColormap.from_list("r", ["#f7fcf5", "#fee08b", "#f46d43", "#a50026"])
    im = ax.imshow(100 * piv.values, cmap=cmap, vmin=0, vmax=100, aspect="auto")
    for i in range(piv.shape[0]):
        for j in range(piv.shape[1]):
            v = piv.values[i, j]
            ax.text(j, i, "–" if np.isnan(v) else f"{100*v:.0f}", ha="center", va="center", fontsize=8,
                    color="white" if (not np.isnan(v) and v > .6) else "black")
    ax.set_xticks(range(len(KP_LABELS))); ax.set_xticklabels(KP_LABELS, rotation=30, ha="right")
    ax.set_yticks(range(len(piv))); ax.set_yticklabels([({"HOME": "HOME raw", "HOMEc": "HOME noise-corr.", "HOMEs": "HOME self-cal."}.get(s, s)) + f" ({mlat.get(s, np.nan):+.0f}°)" for s in piv.index])
    ax.grid(False); plt.colorbar(im, ax=ax, label="% of time beyond 2.5 cm tolerance")
    ax.set_title("RTK tractor out-of-tolerance time by station and Kp\n(geomagnetic latitude in brackets; – = <1 h of data)", fontsize=10)
    fig.savefig(FIG / "fig3_heatmap_tractor.png"); plt.close(fig)

    # ---- Fig D: 10-11 Oct 2026 time series (home, Morpeth, Tromsø)
    fig, axs = plt.subplots(3, 1, figsize=(10, 7.5), sharex=True)
    x = w[(w.window_start >= "2026-10-10T12") & (w.window_start < "2026-10-11T18")]
    for s, c, lab in [("TRO1", "#762a83", "Tromsø"), ("MORP", "#1b7837", "Morpeth"), ("HOMEs", "#e08214", "Belfast home (self-calibrated)")]:
        xs = x[x.station == s].sort_values("t")
        axs[0].plot(xs.t, xs.p95, color=c, lw=1, label=lab)
        axs[1].plot(xs.t, 100 * xs.s02, color=c, lw=1, label=lab)
        axs[2].plot(xs.t, 100 * xs.err_tractor, color=c, lw=1, label=lab)
    axs[0].set_ylabel("ROTI, 95th pct\nsatellite (TECU/min)\n(home: raw, noise-dominated)"); axs[0].legend(fontsize=8, ncol=3)
    axs[1].axhline(40, color="r", ls="--", lw=1); axs[1].text(x.t.min(), 42, "fix-loss threshold (40 % of satellites)", color="r", fontsize=8)
    axs[1].set_ylabel("Satellites with\nROTI > 0.2 (%)")
    axs[2].axhline(2.5, color="k", ls="--", lw=1); axs[2].text(x.t.min(), 3, "tractor tolerance 2.5 cm", fontsize=8)
    axs[2].set_yscale("log"); axs[2].set_ylabel("Estimated RTK\nerror (cm, log)")
    kpx = x[x.station == "HOMEs"].sort_values("t")
    ax2 = axs[0].twinx(); ax2.step(kpx.t, kpx.kp, color="0.5", where="post", lw=1); ax2.set_ylabel("Kp", color="0.5"); ax2.set_ylim(0, 9); ax2.grid(False)
    axs[2].set_xlabel("Time (UTC), 10-11 October 2026")
    fig.suptitle("10-11 October 2026 G3 storm: measured disturbance mapped to RTK tractor error", fontsize=11)
    fig.savefig(FIG / "fig4_oct2026_timeseries.png"); plt.close(fig)

    # ---- Fig E: May 2024 common-mode across stations
    fig, ax = plt.subplots(figsize=(10, 4.2))
    x = w[(w.window_start >= "2024-05-10T12") & (w.window_start < "2024-05-11T12")]
    ss = [("KIRU", "Kiruna"), ("TRO1", "Tromsø"), ("MORP", "Morpeth"), ("HERS", "Herstmonceux"), ("BRUX", "Brussels"), ("PIE1", "Pie Town (USA)")]
    for i, (s, lab) in enumerate(ss):
        xs = x[x.station == s].sort_values("t")
        ax.scatter(xs.t, np.full(len(xs), i), c=np.where(xs.exc_tractor == 1, "#d73027", "#1a9850"), s=9, marker="s")
    ax.set_yticks(range(len(ss))); ax.set_yticklabels([l for _, l in ss]); ax.grid(False)
    kpx = x[x.station == "MORP"].sort_values("t")
    ax2 = ax.twinx(); ax2.step(kpx.t, kpx.kp, color="k", where="post", lw=1.2); ax2.set_ylim(0, 9.5); ax2.set_ylabel("Kp"); ax2.grid(False)
    ax.scatter([], [], c="#d73027", marker="s", label="beyond 2.5 cm tolerance"); ax.scatter([], [], c="#1a9850", marker="s", label="within tolerance")
    ax.legend(loc="lower left", fontsize=8, ncol=2)
    ax.set_xlabel("Time (UTC), 10-11 May 2024")
    ax.set_title("May 2024 G5 storm: RTK tractor tolerance at six stations at once (each square = 5 min)", fontsize=10.5)
    fig.savefig(FIG / "fig5_may2024_commonmode.png"); plt.close(fig)

    # ---- Fig F: fleet - independent vs common-mode failure
    from scipy.stats import binom
    p = res["common_mode"]["p_MORP"]; N = 200
    k = np.arange(N + 1)
    fig, ax = plt.subplots(figsize=(8, 4))
    pind = 1 - binom.cdf(k - 1, N, p)
    ax.semilogy(100 * k / N, np.clip(pind, 1e-300, 1), label=f"Independent faults (each machine p = {p:.2f})", lw=2)
    from scipy.stats import betabinom
    rho = max(res["common_mode"]["phi_MORP_HERS"], 1e-3)
    a_, b_ = p * (1 - rho) / rho, (1 - p) * (1 - rho) / rho
    ax.semilogy(100 * k / N, np.clip(1 - betabinom.cdf(k - 1, N, a_, b_), 1e-300, 1), lw=2, ls="--",
                label=f"Partly correlated (correlation {rho:.2f}, measured Morpeth vs Herstmonceux)")
    ax.semilogy(100 * k / N, np.full_like(k, p, dtype=float), label=f"Common-mode (shared sky): whole fleet fails together, P = {p:.2f}", lw=2)
    ax.set_ylim(1e-30, 1.5); ax.set_xlabel(f"Share of a {N}-machine regional fleet out of tolerance at the same time (%)")
    ax.set_ylabel("Probability (log scale)"); ax.legend(fontsize=8)
    ax.set_title("Why fleet density matters: correlated versus independent failures", fontsize=10.5)
    fig.text(0.5, -0.05, "p = Morpeth share of storm-archive windows beyond 2.5 cm (this study). Dashed curve: beta-binomial with the measured station-to-station correlation. Illustrative only.", ha="center", fontsize=7.5)
    fig.savefig(FIG / "fig6_fleet_commonmode.png"); plt.close(fig)

    # ---- Fig G: solar cycle outlook
    sn = pd.read_csv(AN / "SN_ms_tot_V2.0.csv", sep=";", header=None, names=["y", "m", "dec", "sn", "sd", "n", "prov"])
    sn = sn[(sn.sn >= 0) & (sn.dec > 1975)]
    fig, ax = plt.subplots(figsize=(9, 3.8))
    ax.plot(sn.dec, sn.sn, color="k", lw=1.5, label="Observed, 13-month smoothed (WDC-SILSO)")
    ax.errorbar(2034.7, 121.2, yerr=10, fmt="s", color="#2166ac", capsize=4, label="Cycle 26: Rodríguez et al. (2024), Sep 2034")
    ax.errorbar(2035.3, 109.1, xerr=2.3, yerr=32.9, fmt="o", color="#b2182b", capsize=4, label="Cycle 26: Zermane et al. (2025), MSODA")
    ax.errorbar(2035.5, 160.7, xerr=2.3, yerr=47.8, fmt="^", color="#ef8a62", capsize=4, label="Cycle 26: Zermane et al. (2025), MXSODA")
    for yr, lab in [(1989.2, "Mar 1989"), (2003.8, "Oct 2003"), (2024.36, "May 2024")]:
        ax.axvline(yr, color="0.6", ls=":", lw=1); ax.text(yr + .2, 250, lab, rotation=90, fontsize=7.5, color="0.35", va="top")
    ax.set_xlabel("Year"); ax.set_ylabel("Sunspot number"); ax.set_xlim(1975, 2041); ax.set_ylim(0, 260)
    ax.legend(fontsize=7.5, loc="upper center", bbox_to_anchor=(0.5, -0.17), ncol=2); ax.set_title("Solar cycles 21-25 and published forecasts for Cycle 26", fontsize=10.5)
    fig.savefig(FIG / "fig7_solar_cycle26.png"); plt.close(fig)

if __name__ == "__main__":
    main()
