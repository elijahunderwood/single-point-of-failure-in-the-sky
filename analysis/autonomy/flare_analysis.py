"""Solar-flare angle: SITEC size vs X-ray flux and SZA from this project's flare_logger results,
literature anchors, extrapolation to X1/X10/X20+, conversion to range and RTK differential error,
and 'which flare breaks what'. Writes flare_results.json and figures fig8/fig9."""
from pathlib import Path as _RepoPath
import os as _repo_os
REPO_ROOT = _RepoPath(_repo_os.environ.get('REPO_ROOT', _RepoPath(__file__).resolve().parents[2]))
import sqlite3, json, numpy as np, pandas as pd, matplotlib
matplotlib.use("Agg"); import matplotlib.pyplot as plt
from pathlib import Path
OUT = (REPO_ROOT / 'analysis' / 'autonomy'); FIG = OUT / "figures"; FL = OUT / "flare"
db = sqlite3.connect('file:' + _repo_os.environ.get('FLARE_DB', str(_RepoPath.home() / 'flare_logger' / 'flare.db')) + '?mode=ro', uri=True)
fl = pd.read_sql("select * from flares", db)
fr = pd.read_sql("select * from flare_response where status='ok'", db)
d = fr.merge(fl[["flare_id", "class", "peak_flux", "peak_utc"]], on="flare_id")
d["cos_sza"] = np.cos(np.radians(d.sza_deg))
M_PER_TECU = 0.162; RE_KM = 6371.0
# ---- Add HOME results from the Pi-side logger (figures produced by the logger; DB rows not on this computer)
pi_home = [  # flare_id, class, flux, sza, used, responded, peak, mean_all, noise, detected, ttp
  ("202610060747", "M1.9", 1.9e-5, 78.1, 4, 2, 0.39, None, 0.081, 1, 17.8),
  ("202610081529", "M6.8", 6.8e-5, 75.1, 3, 1, 0.52, None, 0.198, 0, 20.5)]
flares_only = d[d.kind == "flare"].copy()
# per station-flare: responders' median peak (TECU, slant residual); detection flag
g = flares_only
summ = {"n_station_flares_ok": int(len(g)), "n_detected": int(g.detected.sum()),
        "n_flares": int(g.flare_id.nunique()), "stations": sorted(g.station.unique().tolist())}
# detection fraction by class bin
g["cbin"] = pd.cut(g.peak_flux, [1e-5, 2e-5, 5e-5, 1e-4], labels=["M1–M2", "M2–M5", "M5–M9"], right=False)
detfrac = g.groupby("cbin", observed=True).agg(n=("detected", "size"), det=("detected", "sum"),
            med_peak=("median_peak_dtec", "median"), med_noise=("noise_tecu", "median")).reset_index()
summ["detection_by_class"] = detfrac.astype({"cbin": str}).to_dict("records")
big = g[g.peak_flux >= 5e-5].sort_values(["flare_id", "station"])
summ["big_flares"] = big[["flare_id", "class", "station", "sza_deg", "n_sats_used", "n_sats_responded", "peak_dtec",
                          "median_peak_dtec", "mean_peak_dtec_all", "time_to_peak_min", "lag_after_xray_peak_min",
                          "noise_tecu", "detected"]].round(3).to_dict("records")
POLAR = {"NYA1", "THU2", "MCM4"}
g["quality"] = (g.noise_tecu <= 0.2) & (~g.station.isin(POLAR))
qd = g[g.quality]
summ["quality_detection_by_class"] = qd.groupby("cbin", observed=True).agg(n=("detected", "size"), det=("detected", "sum"),
            med_peak=("median_peak_dtec", "median")).reset_index().astype({"cbin": str}).to_dict("records")
g["credible"] = (g.detected == 1) & g.lag_after_xray_peak_min.between(0, 15) & (g.sza_deg < 85)
summ["credible_by_class_quality"] = g[g.quality].groupby("cbin", observed=True).agg(n=("credible", "size"), cred=("credible", "sum"), det=("detected", "sum")).reset_index().astype({"cbin": str}).to_dict("records")
summ["credible_by_class_all"] = g.groupby("cbin", observed=True).agg(n=("credible", "size"), cred=("credible", "sum"), det=("detected", "sum")).reset_index().astype({"cbin": str}).to_dict("records")
det = g[(g.detected == 1) & g.quality].copy()
summ["quality_detections"] = det[["flare_id", "class", "station", "sza_deg", "median_peak_dtec", "peak_dtec", "lag_after_xray_peak_min", "time_to_peak_min", "noise_tecu"]].round(3).to_dict("records")
# Fit on detections: log10(dTEC) = a + b log10(flux) + c cos(sza)   (median responder peak)
X = np.column_stack([np.ones(len(det)), np.log10(det.peak_flux), det.cos_sza]); y = np.log10(det.median_peak_dtec)
coef, *_ = np.linalg.lstsq(X, y, rcond=None); resid = y - X @ coef
summ["own_fit"] = {"a": coef[0], "b_flux": coef[1], "c_cos_sza": coef[2], "n": int(len(det)),
                   "resid_sd_dex": float(resid.std(ddof=3)) if len(det) > 3 else None,
                   "r_flux": float(np.corrcoef(np.log10(det.peak_flux), y)[0, 1]) if len(det) > 2 else None,
                   "r_cos_sza": float(np.corrcoef(det.cos_sza, y)[0, 1]) if len(det) > 2 else None}
# Literature anchors (vertical TEC enhancement, TECU). Pre-2020 GOES classes converted to the
# present science scale by dividing by 0.7 (NOAA removal of the GOES 8–15 XRS scaling factor).
LIT = [  # label, old-scale class flux, dVTEC low, high, note
  ("X2.2, 6 Sep 2017", 2.2e-4, 2, 4, "dayside, Yasyukevich et al. 2018"),
  ("X9.3, 6 Sep 2017 (mid-lat.)", 9.3e-4, 8, 10, "mid-latitudes, Yasyukevich et al. 2018"),
  ("X9.3, 6 Sep 2017 (low lat.)", 9.3e-4, 15, 16, "low latitudes, Yasyukevich et al. 2018"),
  ("X17, 28 Oct 2003 (subsolar)", 17e-4, 25, 25, "subsolar point, Tsurutani et al. 2005"),
  ("X17, 28 Oct 2003 (SZA<60°)", 17e-4, 14, 25, "N. hemisphere SZA<60°, Zhang & Xiao 2005"),
  ("X7, 29 Oct 2003", 7e-4, 5, 7, "Tsurutani et al. 2005 (5–7 TECU group)"),
  ("X28, 4 Nov 2003 (limb)", 28e-4, 5, 7, "limb flare, Tsurutani et al. 2005")]
lit = pd.DataFrame(LIT, columns=["label", "flux_old", "lo", "hi", "note"]); lit["flux"] = lit.flux_old / 0.7
lit["mid"] = np.sqrt(lit.lo * lit.hi)
# Central (disk-centre, moderate SZA) scaling: fit power law through own detections' median at their median flux
# and the non-limb literature mid-latitude anchors.
bigdet = det[det.peak_flux >= 5e-5]
own_pt = (float(np.exp(np.log(bigdet.peak_flux).mean())), float(np.exp(np.log(bigdet.median_peak_dtec).mean())))
summ["own_big_stats"] = {"n": int(len(bigdet)), "median_lo": float(bigdet.median_peak_dtec.min()), "median_hi": float(bigdet.median_peak_dtec.max()),
    "peak_lo": float(bigdet.peak_dtec.min()), "peak_hi": float(bigdet.peak_dtec.max()), "lag_lo": float(bigdet.lag_after_xray_peak_min.min()),
    "lag_hi": float(bigdet.lag_after_xray_peak_min.max()), "lag_med": float(bigdet.lag_after_xray_peak_min.median()),
    "ttp_med": float(bigdet.time_to_peak_min.median()), "r_cos_sza": float(np.corrcoef(bigdet.cos_sza, bigdet.median_peak_dtec)[0, 1])}
anch = lit[~lit.label.str.contains("limb|low lat|subsolar")]
xs = np.log10(np.r_[own_pt[0], anch.flux]); ys = np.log10(np.r_[own_pt[1], anch.mid])
b, a = np.polyfit(xs, ys, 1)
summ["scaling"] = {"a": a, "b": b, "own_point": own_pt, "anchors_used": anch.label.tolist(),
                   "note": "log10(dTEC) = a + b log10(flux W m^-2); central case for a disk-centre flare at moderate SZA; "
                           "band factor 3 either way (limb flares give 0.3–0.5 of disk-centre response, Le et al. 2013; X28 limb gave only 5–7 TECU)."}
def dtec(flux, f=1.0): return f * 10 ** (a + b * np.log10(flux))
CASES = {"M1": 1e-5, "M5": 5e-5, "X1": 1e-4, "X10": 1e-3, "X20": 2e-3, "X40 (2003 'X28' on present scale)": 4e-3}
TAU_MIN = (2.5, 10.0)       # e-folding rise time range, min (2.5 min: Tsurutani et al. 2005; ~6–10 min from X9.3 rate)
AGE_S = (1.0, 5.0)          # RTK correction age range, s
MAP = 1.8                   # slant factor at ~30° elevation (thin shell 350 km)
DMAP = 0.8                  # difference in slant factor between two satellites in a double difference
rows = []
for k, F in CASES.items():
    c, lo, hi = dtec(F), dtec(F, 1 / 3), dtec(F, 3)
    rng_c = c * MAP * M_PER_TECU                          # single-frequency extra range error at 30° elev (m)
    grad_ppm = c / RE_KM * M_PER_TECU * 1000 * MAP        # mm per km, cos(SZA) model max gradient, slant
    rate_tecu_min = (c / TAU_MIN[1], c / TAU_MIN[0])      # initial rate range
    lat_mm = tuple(r / 60 * age * M_PER_TECU * 1000 * DMAP for r, age in zip(rate_tecu_min, AGE_S[::-1][::-1]))
    lat_lo = rate_tecu_min[0] / 60 * AGE_S[0] * M_PER_TECU * 1000 * DMAP
    lat_hi = rate_tecu_min[1] / 60 * AGE_S[1] * M_PER_TECU * 1000 * DMAP
    rows.append({"case": k, "flux": F, "dVTEC": c, "dVTEC_lo": lo, "dVTEC_hi": hi,
                 "range_err_zenith_m": c * M_PER_TECU, "range_err_30deg_m": rng_c, "range_err_30deg_hi_m": hi * MAP * M_PER_TECU,
                 "grad_ppm": grad_ppm, "rtk_spatial_10km_mm": grad_ppm * 10, "rtk_spatial_50km_mm": grad_ppm * 50,
                 "rtk_spatial_50km_hi_mm": grad_ppm * 50 * 3,
                 "rate_tecu_min_lo": rate_tecu_min[0], "rate_tecu_min_hi": rate_tecu_min[1],
                 "rtk_latency_mm_lo": lat_lo, "rtk_latency_mm_hi": lat_hi})
ext = pd.DataFrame(rows); summ["extrapolation"] = ext.round(4).to_dict("records")
# own range conversions
summ["own_conversions"] = {"0.4_TECU_cm": 0.4 * 16.2, "1.1_TECU_cm": 1.1 * 16.2,
                           "M8.2_detected_range_TECU": [float(big[(big.detected == 1) & (big["class"] == "M8.2")].median_peak_dtec.min()) if len(big) else None,
                                                        float(big[(big.detected == 1) & (big["class"] == "M8.2")].median_peak_dtec.max()) if len(big) else None]}
# ---------------- Figure 8: dTEC vs flux with SZA colour, anchors, scaling band
fig, ax = plt.subplots(figsize=(9, 5.6))
nd = g[(g.detected == 0) & g.quality]
ax.scatter(nd.peak_flux, nd.peak_dtec.fillna(nd.noise_tecu * 3), s=14, facecolors="none", edgecolors="0.6", lw=0.8,
           label="not detected (largest residual, or 3× noise)")
sc = ax.scatter(det.peak_flux, det.median_peak_dtec, c=det.sza_deg, cmap="viridis_r", vmin=20, vmax=90, s=36, edgecolors="k", lw=0.4,
                label="detected, low-noise station: median responding satellite (this study)")
for fid, cl, F, sza, u, r_, pk, _, nz, dt, ttp in pi_home:
    ax.scatter(F, pk, marker="*", s=160, c=[sza], cmap="viridis_r", vmin=20, vmax=90, edgecolors="r", lw=0.9, zorder=5)
ax.scatter([], [], marker="*", s=120, c="w", edgecolors="r", label="Belfast home receiver (1 Hz)")
ax.plot([], [], color="tab:blue", lw=3, label="published, disk/mid-latitude (vertical TEC)")
ax.plot([], [], color="tab:orange", lw=3, label="published, low latitude or subsolar")
ax.plot([], [], color="tab:red", lw=3, label="published, limb flare")
for _, r_ in lit.iterrows():
    col = "tab:red" if "limb" in r_.label else ("tab:orange" if ("low lat" in r_.label or "subsolar" in r_.label) else "tab:blue")
    ax.plot([r_.flux] * 2, [r_.lo, r_.hi], color=col, lw=3, solid_capstyle="butt")
    off = {"X17, 28 Oct 2003 (SZA<60°)": (-150, -4), "X17, 28 Oct 2003 (subsolar)": (5, 2), "X28, 4 Nov 2003 (limb)": (-115, -12),
           "X9.3, 6 Sep 2017 (low lat.)": (-150, 0), "X9.3, 6 Sep 2017 (mid-lat.)": (5, -6), "X7, 29 Oct 2003": (-80, -6)}.get(r_.label, (4, 2))
    ax.annotate(r_.label, (r_.flux, r_.hi), xytext=off, textcoords="offset points", fontsize=7, color=col)
xx = np.logspace(-5, np.log10(5e-3), 50)
ax.plot(xx, dtec(xx), "k--", lw=1.2, label=f"central scaling (dTEC ∝ flux^{b:.2f})")
ax.fill_between(xx, dtec(xx, 1/3), dtec(xx, 3), color="0.85", alpha=0.6, label="×3 band (flare position, spectrum)")
for name, F in [("M1", 1e-5), ("X1", 1e-4), ("X10", 1e-3)]:
    ax.axvline(F, color="0.8", lw=0.6); ax.text(F, 0.03, name, fontsize=8, ha="center", color="0.4")
ax.set_xscale("log"); ax.set_yscale("log"); ax.set_ylim(0.03, 100); ax.set_xlim(8e-6, 6e-3)
ax.set_xlabel("Flare peak soft X-ray flux, 0.1–0.8 nm (W m⁻²; literature classes converted to present scale)")
ax.set_ylabel("Flare TEC increase (TECU)")
ax2 = ax.secondary_yaxis("right", functions=(lambda t: t * 16.2, lambda c: c / 16.2)); ax2.set_ylabel("Extra L1 range delay at zenith (cm)")
cb = fig.colorbar(sc, ax=ax, pad=0.12); cb.set_label("Solar zenith angle at the station (°)")
ax.set_title("Sudden increase in TEC versus flare size: this project's M-class flares and published X-class events", fontsize=10)
ax.legend(fontsize=6.5, loc="lower right", framealpha=0.9)
fig.tight_layout(); fig.savefig(FIG / "fig8_flare_tec_vs_flux.png", dpi=200); plt.close(fig)
# ---------------- Figure 9: which flare breaks what
PLAT = [("RTK auto-steer tractor (10 km)", 0.025), ("Survey drone RTK (10 km)", 0.02), ("Docking ship (RTK)", 0.10),
        ("Motorway car (NRTK/PPP)", 0.20), ("Delivery drone landing (single point)", 1.0), ("Delivery drone en route", 2.0),
        ("LPV-200 approach (SBAS)", 16.0)]
fig, ax = plt.subplots(figsize=(9, 5.2))
xx = np.logspace(-5, np.log10(5e-3), 80)
ax.plot(xx, dtec(xx) * MAP * M_PER_TECU, color="tab:purple", lw=2, label="Single-frequency, uncorrected flare delay (30° elevation)")
ax.fill_between(xx, dtec(xx, 1/3) * MAP * M_PER_TECU, dtec(xx, 3) * MAP * M_PER_TECU, color="tab:purple", alpha=0.15)
gr = dtec(xx) / RE_KM * M_PER_TECU * MAP
ax.plot(xx, gr * 10, color="tab:green", lw=2, label="RTK spatial differential, 10 km baseline")
ax.plot(xx, gr * 50, color="tab:green", lw=2, ls="--", label="RTK spatial differential, 50 km baseline")
latc = dtec(xx) / TAU_MIN[0] / 60 * AGE_S[1] * M_PER_TECU * DMAP
ax.plot(xx, latc, color="tab:olive", lw=1.5, ls=":", label="RTK correction-age term (fast rise, 5 s age; upper bound)")
for n_, tol in PLAT:
    ax.axhline(tol, color="0.6", lw=0.7); ax.text(5.5e-3, tol, n_, fontsize=7, va=("top" if "Survey" in n_ else ("bottom" if "tractor" in n_ else "center")), ha="left")
for name, F in [("M1", 1e-5), ("X1", 1e-4), ("X10", 1e-3), ("X40", 4e-3)]:
    ax.axvline(F, color="0.85", lw=0.6); ax.text(F, 1.2e-4, name, fontsize=8, ha="center", color="0.4")
ax.set_xscale("log"); ax.set_yscale("log"); ax.set_xlim(8e-6, 5e-3); ax.set_ylim(1e-4, 40)
ax.set_xlabel("Flare peak soft X-ray flux (W m⁻²)"); ax.set_ylabel("Error (m)")
ax.set_title("How big a flare breaks each platform through the TEC increase alone (central estimate, ×3 band)", fontsize=10)
ax.legend(fontsize=7, loc="upper left"); fig.subplots_adjust(right=0.72)
fig.savefig(FIG / "fig9_flare_breaks_platforms.png", dpi=200); plt.close(fig)
def flux_for(err_m, kind):
    if kind == "sf": k = MAP * M_PER_TECU
    elif kind == "rtk10": k = M_PER_TECU * MAP / RE_KM * 10
    elif kind == "rtk50": k = M_PER_TECU * MAP / RE_KM * 50
    elif kind == "lat": k = M_PER_TECU * DMAP * AGE_S[1] / (TAU_MIN[0] * 60)
    return 10 ** ((np.log10(err_m / k) - a) / b)
summ["threshold_flux"] = {n_: {"single_freq": flux_for(t, "sf"), "rtk10": flux_for(t, "rtk10"), "rtk50": flux_for(t, "rtk50"),
                               "latency_upper": flux_for(t, "lat")} for n_, t in PLAT}
json.dump(summ, open(FL / "flare_results.json", "w"), indent=1, default=float)
ext.round(4).to_csv(FL / "flare_extrapolation.csv", index=False)
g.to_csv(FL / "flare_station_results.csv", index=False)
print(json.dumps({k: summ[k] for k in ["n_station_flares_ok", "n_detected", "n_flares", "detection_by_class", "own_fit", "scaling"]}, indent=1, default=float))
print(ext[["case", "dVTEC", "dVTEC_lo", "dVTEC_hi", "range_err_30deg_m", "rtk_spatial_10km_mm", "rtk_spatial_50km_mm", "rtk_latency_mm_lo", "rtk_latency_mm_hi"]].round(3).to_string())
for n_, v in summ["threshold_flux"].items(): print(n_, {k: f"{x:.1e}" for k, x in v.items()})
