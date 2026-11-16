"""02_home_roti.py - home-station TEC -> ROTI for each storm window and the
quiet controls; storm-vs-quiet effect sizes with block-bootstrap CIs; S4 proxy."""
import os, sys, json
import pandas as pd, numpy as np, matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
sys.path.insert(0, os.path.dirname(__file__)); from swlib import *

E = f"{DATA}/storm_exports"
WIN = {  # label: (files, kind)
 "S1 02 Aug (day)":     ([f"{E}/tec_2026-08-02.csv"], "storm"),
 "S2 08 Aug (eve)":     ([f"{E}/tec_2026-08-08.csv"], "storm"),
 "S3 07-08 Sep (night)": ([f"{DATA}/gnss_storm_0708sep.csv", f"{E}/tec_2026-09-08.csv"], "storm"),
 "S4 04 Oct (eve)":     ([f"{E}/tec_2026-10-04.csv"], "storm"),
 "S5 05 Oct (night)":   ([f"{X}/gnss_storm_05oct.csv"], "storm"),
 "Q 02 Oct day":        ([f"{X}/quiet_ctrl/quiet_02oct_day.csv"], "quiet"),
 "Q 02 Oct night":      ([f"{X}/quiet_ctrl/quiet_02oct_night.csv"], "quiet"),
 "Q 17-18 Sep (dump)":  ([f"{OUT}/home_copy_dump.csv"], "quiet?"),
 "Q 22-23 Sep (dump)":  ([f"{OUT}/home_orig_dump.csv"], "quiet?"),
}
kp = pd.read_csv(f"{E}/kp_index.csv"); kp["t"] = pd.to_datetime(kp.ts_utc, utc=True)
dst = pd.read_csv(f"{E}/dst_index.csv"); dst["t"] = pd.to_datetime(dst.ts_utc, utc=True)

def load(files):
    d = pd.concat([load_home_csv(f) for f in files], ignore_index=True)
    return d.drop_duplicates(["sv", "t"]).sort_values(["sv", "t"]).reset_index(drop=True)

res, nets, s4s, rots = {}, {}, {}, {}
for lab, (files, kind) in WIN.items():
    d = load(files)
    t0, t1 = d.t.min(), d.t.max()
    kpw = kp[(kp.t > t0 - pd.Timedelta("3h")) & (kp.t <= t1)]
    dsw = dst[(dst.t >= t0.floor("h")) & (dst.t <= t1)]
    r = dict(kind=kind, start=str(t0), end=str(t1), hours=round((t1-t0).total_seconds()/3600, 2),
             kp_max=float(kpw.kp.max()) if len(kpw) else None, dst_min=float(dsw.dst.min()) if len(dsw) else None)
    for mask in (20, 30):
        rot, qc = compute_rot(d, elev_mask=mask)
        ro = compute_roti(rot); net = network(ro)
        k = int((ro.roti > 0.5).sum()); p, lo, hi = wilson(k, len(ro))
        r[f"m{mask}"] = dict(qc=qc, rejected_pct=round(100*qc["rot_rejected"]/max(1, qc["rot_total"]), 2),
            sat_windows=len(ro), net_windows=len(net), roti_sat_median=round(ro.roti.median(), 4),
            roti_sat_p95=round(ro.roti.quantile(.95), 4), net_med_median=round(net.roti_med.median(), 4),
            net_2nd_median=round(net.roti_2nd.median(), 4), net_2nd_max=round(net.roti_2nd.max(), 4),
            frac_sat_windows_gt05=[round(p, 4), round(lo, 4), round(hi, 4)],
            frac_net2nd_gt05=round(float((net.roti_2nd > 0.5).mean()), 4))
        if mask == 30: nets[lab] = net; rots[lab] = ro
    s4 = s4_from_cno(d); s4s[lab] = s4
    r["s4"] = dict(n=len(s4), median=round(s4.s4.median(), 4), p99=round(s4.s4.quantile(.99), 4),
                   max=round(s4.s4.max(), 3), n_gt03=int((s4.s4 > 0.3).sum()), n_gt05=int((s4.s4 > 0.5).sum()))
    res[lab] = r
    print(lab, json.dumps(r)[:600])

# ---- Kp of the dump days -> are they really quiet?
for lab in ["Q 17-18 Sep (dump)", "Q 22-23 Sep (dump)"]:
    print(lab, "Kp max", res[lab]["kp_max"], "Dst min", res[lab]["dst_min"])

# ---- storm vs UTC-hour-matched quiet pool (30 deg mask, network median ROTI)
quiet = pd.concat([nets[l] for l in WIN if WIN[l][1].startswith("quiet") and (res[l]["kp_max"] or 0) < 4])
quiet["h"] = quiet.index.hour
eff = {}
for lab in [l for l in WIN if WIN[l][1] == "storm"]:
    s = nets[lab]; hrs = set(s.index.hour)
    q = quiet[quiet.h.isin(hrs)].sort_index()
    out = {}
    for col in ["roti_med", "roti_2nd"]:
        dmed, lo, hi = block_bootstrap_diff(s[col].values, q[col].values, block=6)
        out[col] = dict(storm=round(s[col].median(), 4), quiet=round(q[col].median(), 4),
                        diff=round(dmed, 4), ci95=[round(lo, 4), round(hi, 4)],
                        ratio=round(s[col].median()/q[col].median(), 2))
    # fraction of satellite windows > 0.5: storm minus quiet, 95% upper limit
    rs = rots[lab]; rq = pd.concat([rots[l] for l in WIN if WIN[l][1].startswith("quiet") and (res[l]["kp_max"] or 0) < 4])
    rq = rq[rq.t.dt.hour.isin(hrs)]
    ps, _, hs = wilson(int((rs.roti > .5).sum()), len(rs)); pq, _, _ = wilson(int((rq.roti > .5).sum()), len(rq))
    out["frac_gt05"] = dict(storm=round(ps, 4), storm_upper95=round(hs, 4), quiet=round(pq, 4), quiet_n=len(rq))
    out["quiet_windows_used"] = len(q)
    eff[lab] = out
    print(lab, out)
json.dump(dict(windows=res, effects=eff), open(f"{OUT}/home_roti.json", "w"), indent=1, default=str)

# ---- figures
fig, axs = plt.subplots(len(WIN), 1, figsize=(10, 2.0*len(WIN)), sharey=True)
for ax, lab in zip(axs, WIN):
    n = nets[lab]; ro = rots[lab]
    ax.scatter(ro.t, ro.roti, s=2, c="lightgrey", label="each satellite")
    ax.plot(n.index, n.roti_2nd, color="tab:red", lw=1, label="network 2nd-highest")
    ax.plot(n.index, n.roti_med, color="tab:blue", lw=1, label="network median")
    ax.axhline(0.5, ls="--", c="k", lw=.7)
    ax.set_title(f"{lab}   Kp max {res[lab]['kp_max']}, Dst min {res[lab]['dst_min']} nT", fontsize=9, loc="left")
    ax.set_ylim(0, 1.2); ax.set_ylabel("ROTI\nTECU/min", fontsize=8)
axs[0].legend(fontsize=7, ncol=3, loc="upper right")
plt.tight_layout(); plt.savefig(f"{FIG}/02_home_roti_timeseries.png", dpi=130); plt.close()

labs = [l for l in WIN if WIN[l][1] == "storm"]
fig, ax = plt.subplots(1, 2, figsize=(11, 4))
for i, col in enumerate(["roti_med", "roti_2nd"]):
    y = [eff[l][col]["diff"] for l in labs]; lo = [eff[l][col]["ci95"][0] for l in labs]; hi = [eff[l][col]["ci95"][1] for l in labs]
    ax[i].errorbar(range(len(labs)), y, yerr=[np.array(y)-lo, np.array(hi)-y], fmt="o", capsize=4)
    ax[i].axhline(0, c="k", lw=.7); ax[i].set_xticks(range(len(labs))); ax[i].set_xticklabels([l.split(" (")[0] for l in labs], fontsize=8)
    ax[i].set_title(f"Storm minus quiet ({col}), 95% CI", fontsize=10); ax[i].set_ylabel("TECU/min")
plt.tight_layout(); plt.savefig(f"{FIG}/03_home_storm_minus_quiet.png", dpi=130); plt.close()

fig, ax = plt.subplots(figsize=(10, 4))
data = [s4s[l].s4.values for l in WIN]
ax.boxplot(data, whis=(1, 99), showfliers=False); ax.set_xticks(range(1, len(WIN)+1)); ax.set_xticklabels([l.replace(" (", "\n(") for l in WIN], fontsize=7)
for i, l in enumerate(WIN): ax.plot(i+1, s4s[l].s4.max(), "rx")
ax.set_ylabel("S4 proxy from 1 Hz C/N0 (el>30°)"); ax.set_title("Amplitude-scintillation proxy: boxes 1-99%, red x = maximum")
plt.tight_layout(); plt.savefig(f"{FIG}/04_home_s4_proxy.png", dpi=130); plt.close()

# save network series for later scripts
allnet = pd.concat([n.assign(window=l) for l, n in nets.items()])
allnet.to_csv(f"{OUT}/home_network_roti_m30.csv")
