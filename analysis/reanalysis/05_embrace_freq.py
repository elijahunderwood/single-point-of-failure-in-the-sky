"""05_embrace_freq.py - equatorial scintillation (EMBRACE S4) on the storm days,
and a quantitative test of how scintillation scales with radio frequency."""
import os, sys, json, sqlite3
import pandas as pd, numpy as np, matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
sys.path.insert(0, os.path.dirname(__file__)); from swlib import *

c = sqlite3.connect(f"file:{DATA}/embrace_scint.db?mode=ro", uri=True)
d = pd.read_sql("select * from scint", c); d["t"] = pd.to_datetime(d.ts_utc, utc=True)
n_all = len(d)
d = d[d.el >= 30]                       # 30 deg mask removes most multipath
d["hour"] = d.t.dt.hour; d["day"] = d.t.dt.strftime("%m-%d")
d["night"] = d.hour.between(0, 5) | (d.hour >= 22)   # ~18-02 local time (UTC-4) post-sunset window
res = {"rows_total": n_all, "rows_el30": len(d), "per_station_day": {}}
for (st, day), g in d.groupby(["station", "day"]):
    gn = g[g.night]
    res["per_station_day"][f"{st} {day}"] = dict(
        s4_max=round(g.s4.max(), 3), s4_max_time=str(g.loc[g.s4.idxmax(), "t"]),
        night_s4_p99=round(gn.s4.quantile(.99), 3), night_minutes_s4_gt05=int((gn.s4 > .5).sum()),
        night_frac_s4_gt03=round(float((gn.s4 > .3).mean()), 4), day_frac_s4_gt03=round(float((g[~g.night].s4 > .3).mean()), 4))
for k, v in res["per_station_day"].items(): print(k, v)

# ---- frequency scaling of S4 (weak-scatter theory predicts S4 ~ f^-1.5)
fit = {}
for band, fb, col in [("L2", F2, "s4_l2"), ("L5", F5, "s4_l5")]:
    m = d[(d.s4 >= 0.3) & (d.s4 <= 0.7) & d[col].notna() & (d[col] > 0)]
    ratio = m[col] / m.s4
    n_exp = np.log(ratio) / np.log(F1 / fb)
    bs = [np.median(np.random.default_rng(i).choice(n_exp.values, len(n_exp))) for i in range(1000)]
    fit[band] = dict(points=len(m), median_ratio=round(ratio.median(), 3), expected_ratio_f15=round((F1/fb)**1.5, 3),
                     expected_ratio_f2=round((F1/fb)**2, 3), exponent_median=round(n_exp.median(), 3),
                     exponent_ci95=[round(np.percentile(bs, 2.5), 3), round(np.percentile(bs, 97.5), 3)])
res["frequency_scaling"] = fit
nexp = fit["L2"]["exponent_median"]
FKU = 11.7e9
res["ku_extrapolation"] = dict(
    exponent_used=nexp,
    s4_reduction_factor_L1_to_Ku=round((F1/FKU)**nexp, 4),
    worst_equatorial_s4_L1=round(d.s4.max(), 3),
    implied_s4_Ku=round(d.s4.max()*(F1/FKU)**nexp, 3),
    delay_ratio_L1_to_Ku_1_over_f2=round((FKU/F1)**2, 1),
    s4_ratio_L1_to_Ku=round((FKU/F1)**nexp, 1),
    note="ionospheric DELAY scales as 1/f^2 (~55x less at Ku); SCINTILLATION (S4) scales as f^-n with n measured here")
print(json.dumps(fit, indent=1), res["ku_extrapolation"])
json.dump(res, open(f"{OUT}/embrace.json", "w"), indent=1)

# ---- figures
fig, axs = plt.subplots(1, 3, figsize=(14, 4), sharey=True)
for ax, st in zip(axs, ["BAVC", "GOUR", "MTSR"]):
    for day, g in d[d.station == st].groupby("day"):
        h = g.groupby(g.t.dt.floor("10min")).s4.quantile(.95)
        ax.plot((h.index - h.index.normalize()).total_seconds()/3600, h.values, label=day, lw=1)
    ax.axhline(.5, ls="--", c="k", lw=.7); ax.set_title(f"{st}: 95th-pct S4 (el≥30°) per 10 min"); ax.set_xlabel("UTC hour"); ax.legend(fontsize=7)
axs[0].set_ylabel("S4 (L1)")
plt.tight_layout(); plt.savefig(f"{FIG}/07_embrace_s4_by_hour.png", dpi=130); plt.close()

fig, ax = plt.subplots(figsize=(6, 5))
m = d[d.s4_l2.notna() & (d.s4 > .15)]
ax.scatter(m.s4, m.s4_l2, s=2, alpha=.2, label="L2 (1227.6 MHz)")
m5 = d[d.s4_l5.notna() & (d.s4 > .15)]
ax.scatter(m5.s4, m5.s4_l5, s=2, alpha=.2, label="L5 (1176.45 MHz)")
x = np.linspace(0, 1.2, 10)
ax.plot(x, x*(F1/F2)**1.5, "k--", label="theory f^-1.5 (L2)"); ax.plot(x, x*(F1/F2)**2, "k:", label="f^-2 (L2)"); ax.plot(x, x, "grey", lw=.7)
ax.set_xlim(0, 1.2); ax.set_ylim(0, 1.6); ax.set_xlabel("S4 on L1 (1575.42 MHz)"); ax.set_ylabel("S4 on lower frequency")
ax.set_title(f"Scintillation vs frequency: measured exponent n≈{nexp}"); ax.legend(fontsize=7, markerscale=5)
plt.tight_layout(); plt.savefig(f"{FIG}/08_frequency_scaling.png", dpi=130); plt.close()
