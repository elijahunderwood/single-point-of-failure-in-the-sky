"""07_validation.py - check the ROTI code itself: (1) synthetic data with a known
answer, (2) why a 30-s base is used (1-s differencing inflates the noise floor),
(3) robustness to the slip-detection threshold."""
import os, sys, json
import pandas as pd, numpy as np, matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
sys.path.insert(0, os.path.dirname(__file__)); from swlib import *
res = {}
# (1) synthetic: 2 h, 1 Hz, sat 1 quiet, sat 2 with 45-min irregularity burst + one cycle slip
rng = np.random.default_rng(0); n = 7200
t = pd.date_range("2026-01-01", periods=n, freq="1s", tz="UTC")
base = 20 + 5*np.sin(np.arange(n)/7200*np.pi)                      # slow diurnal-like change
quiet = base + rng.normal(0, 0.02, n)                               # 0.02 TECU phase noise
dist = base + rng.normal(0, 0.02, n)
burst = (np.arange(n) >= 1800) & (np.arange(n) < 4500)
walk = np.cumsum(rng.normal(0, 0.06, n)); walk -= pd.Series(walk).rolling(300, center=True, min_periods=1).mean().to_numpy()
dist[burst] += 3*walk[burst]
dist[6000:] += 1.8                                                  # a 1-cycle L1 slip (~1.8 TECU step)
df = pd.concat([pd.DataFrame(dict(t=t, sv=1, phase_tec=quiet, elev_deg=60.0, slip=0)),
                pd.DataFrame(dict(t=t, sv=2, phase_tec=dist, elev_deg=60.0, slip=0))])
rot, qc = compute_rot(df); ro = compute_roti(rot)
for sv in (1, 2):
    r = ro[ro.sv == sv]; inb = r.t.between(t[1800], t[4499])
    res[f"synthetic_sv{sv}"] = dict(roti_in_burst=round(r[inb].roti.median(), 3), roti_outside=round(r[~inb].roti.median(), 3),
                                    max_outside=round(r[~inb].roti.max(), 3))
res["synthetic_qc"] = qc
fig, ax = plt.subplots(2, 1, figsize=(9, 5), sharex=True)
ax[0].plot(t, quiet, c="g", lw=.7, label="quiet satellite"); ax[0].plot(t, dist, c="r", lw=.7, label="disturbed + cycle slip at 01:40")
ax[0].set_ylabel("phase TEC"); ax[0].legend(fontsize=7)
for sv, col in ((1, "g"), (2, "r")):
    r = ro[ro.sv == sv]; ax[1].step(r.t, r.roti, c=col, where="post")
ax[1].axhline(.5, ls="--", c="k"); ax[1].axvspan(t[1800], t[4499], alpha=.15); ax[1].set_ylabel("ROTI TECU/min")
ax[0].set_title("Synthetic test: irregularity detected only in the burst; the slip is not mistaken for activity")
plt.tight_layout(); plt.savefig(f"{FIG}/01_synthetic_validation.png", dpi=130); plt.close()

# (2)+(3) on the quiet 22-23 Sep day
d = load_home_csv(f"{OUT}/home_orig_dump.csv")
for b in (1, 10, 30, 60):
    rot, _ = compute_rot(d, elev_mask=30, base_s=b); ro = compute_roti(rot, base_s=b)
    res[f"base_{b}s_quiet_median_roti"] = round(ro.roti.median(), 4)
for j in (0.5, 1.0, 2.0, 1e9):
    rot, qc = compute_rot(d, elev_mask=30, jump_tecu=j); ro = compute_roti(rot)
    res[f"jump_{j}_quiet"] = dict(median=round(ro.roti.median(), 4), frac_gt05=round(float((ro.roti > .5).mean()), 4), arcs=qc["arcs"])
# (4) code TEC vs phase TEC: phase TEC levelled to code TEC per arc (a standard check)
g = d[d.elev_deg >= 30].copy()
g["arc"] = ((g.sv.diff() != 0) | (g.slip == 1) | (g.t.diff().dt.total_seconds() > 2.5)).cumsum()
off = g.groupby("arc").apply(lambda x: (x.code_tec - x.phase_tec).median())
g["lev"] = g.phase_tec + g.arc.map(off)
res["code_minus_levelled_phase_TECU_std"] = round(float((g.code_tec - g.lev).std()), 3)
res["code_tec_negative_fraction"] = round(float((g.code_tec < 0).mean()), 3)
json.dump(res, open(f"{OUT}/validation.json", "w"), indent=1)
print(json.dumps(res, indent=1))
