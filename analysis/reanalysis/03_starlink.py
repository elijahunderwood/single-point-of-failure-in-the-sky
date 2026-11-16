"""03_starlink.py - Starlink latency / drops versus Kp, ionosphere (ROTI) and rain.
Only two 6-hour Starlink windows were supplied (7-8 Sep 21-03 UTC, 5 Oct 00-06 UTC)."""
import os, sys, json, urllib.request
import pandas as pd, numpy as np, matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
sys.path.insert(0, os.path.dirname(__file__)); from swlib import *

# ---------- weather: Open-Meteo historical-forecast (model) hourly rain for Belfast
wf = f"{OUT}/om_hist.json"
if not os.path.exists(wf):
    u = ("https://historical-forecast-api.open-meteo.com/v1/forecast?latitude=54.6&longitude=-5.9"
         "&start_date=2026-09-07&end_date=2026-10-05&hourly=precipitation,rain,cloud_cover,wind_speed_10m&timezone=GMT")
    open(wf, "wb").write(urllib.request.urlopen(u, timeout=60).read())
w = pd.DataFrame(json.load(open(wf))["hourly"]); w["t"] = pd.to_datetime(w.time).dt.tz_localize("UTC")
w = w.set_index("t")

kp = pd.read_csv(f"{DATA}/storm_exports/kp_index.csv"); kp["t"] = pd.to_datetime(kp.ts_utc, utc=True)
kp = kp.set_index("t").kp
dst = pd.read_csv(f"{DATA}/storm_exports/dst_index.csv"); dst["t"] = pd.to_datetime(dst.ts_utc, utc=True)
dst = dst.set_index("t").dst; dst_r = dst.rolling(3, center=True, min_periods=1).median()
net = pd.read_csv(f"{OUT}/home_network_roti_m30.csv", index_col=0, parse_dates=True)

res, frames = {}, []
for lab, f in [("7-8 Sep", f"{DATA}/starlink_0708sep.csv"), ("5 Oct", f"{X}/starlink_05oct.csv")]:
    s = pd.read_csv(f); s["t"] = pd.to_datetime(s.ts_utc, utc=True); s = s.sort_values("t").set_index("t")
    s["full_drop"] = (s.ping_drop_rate >= 1).astype(float)
    m5 = pd.DataFrame({"lat_med": s.ping_latency_ms.resample("5min").median(),
                       "lat_p95": s.ping_latency_ms.resample("5min").quantile(.95),
                       "drop_mean": s.ping_drop_rate.resample("5min").mean(),
                       "full_drop_s": s.full_drop.resample("5min").sum()})
    m5["kp"] = kp.reindex(m5.index, method="ffill")          # Kp value of the 3-h block
    m5["dst"] = dst_r.reindex(m5.index.floor("h")).to_numpy()
    m5["rain_mm"] = w.precipitation.reindex(m5.index.floor("h")).to_numpy()
    m5["roti_2nd"] = net.roti_2nd.reindex(m5.index)
    m5["window"] = lab
    frames.append(m5)
    res[lab] = dict(seconds=len(s), latency_median_ms=round(s.ping_latency_ms.median(), 2),
        latency_p95_ms=round(s.ping_latency_ms.quantile(.95), 2), mean_drop_pct=round(100*s.ping_drop_rate.mean(), 3),
        fully_dropped_seconds=int(s.full_drop.sum()), kp_values=sorted(m5.kp.unique().tolist()),
        rain_total_mm=round(float(w.precipitation[s.index.min().floor("h"):s.index.max()].sum()), 2))
d = pd.concat(frames)
d.to_csv(f"{OUT}/starlink_5min.csv")

# ---------- storm (Kp>=5) vs less-disturbed (Kp<5) 5-min blocks, block bootstrap
hi, lo = d[d.kp >= 5], d[d.kp < 5]
for col, stat in [("lat_med", np.median), ("drop_mean", np.mean)]:
    diff, a, b = block_bootstrap_diff(hi[col].values, lo[col].values, stat=stat, block=6)
    res[f"kp>=5_minus_kp<5_{col}"] = dict(n_hi=len(hi), n_lo=len(lo), diff=round(diff, 4), ci95=[round(a, 4), round(b, 4)])
# rain vs dry 5-min blocks
wet, dry = d[d.rain_mm > 0.1], d[d.rain_mm <= 0.1]
for col, stat in [("lat_med", np.median), ("drop_mean", np.mean)]:
    if len(wet) > 3:
        diff, a, b = block_bootstrap_diff(wet[col].values, dry[col].values, stat=stat, block=6)
        res[f"rain_minus_dry_{col}"] = dict(n_wet=len(wet), n_dry=len(dry), diff=round(diff, 4), ci95=[round(a, 4), round(b, 4)])

# ---------- multiple regression: latency ~ Kp + rain + window  (controls for weather)
X_ = np.column_stack([np.ones(len(d)), d.kp, d.rain_mm.fillna(0), (d.window == "5 Oct").astype(float)])
y = d.lat_med.values
beta = np.linalg.lstsq(X_, y, rcond=None)[0]
rng = np.random.default_rng(3); bs = []
idx = np.arange(len(d)); blocks = [idx[i:i+6] for i in range(0, len(d), 6)]
for _ in range(3000):
    pick = np.concatenate([blocks[i] for i in rng.integers(0, len(blocks), len(blocks))])
    bs.append(np.linalg.lstsq(X_[pick], y[pick], rcond=None)[0])
bs = np.array(bs)
res["regression_latency_ms"] = {n: dict(coef=round(beta[i], 3), ci95=[round(np.percentile(bs[:, i], 2.5), 3), round(np.percentile(bs[:, i], 97.5), 3)])
                                for i, n in enumerate(["intercept", "per_Kp_unit", "per_mm_rain", "5Oct_offset"])}

# ---------- correlations (block permutation, honest for autocorrelated series)
for a_, b_ in [("roti_2nd", "lat_med"), ("roti_2nd", "drop_mean"), ("kp", "lat_med"), ("rain_mm", "drop_mean"), ("rain_mm", "lat_med")]:
    rho, p, n = spearman_block_perm(d[a_].values, d[b_].values, block=6)
    res[f"spearman_{a_}_vs_{b_}"] = dict(rho=round(rho, 3), p_block_perm=round(p, 4), n=n)

# ---------- figure
fig, axs = plt.subplots(4, 2, figsize=(12, 9), sharex="col")
for j, (lab, g) in enumerate(d.groupby("window", sort=False)):
    axs[0, j].plot(g.index, g.lat_med, label="median"); axs[0, j].plot(g.index, g.lat_p95, alpha=.5, label="95th pct")
    axs[0, j].set_ylabel("latency ms"); axs[0, j].legend(fontsize=7); axs[0, j].set_title(f"Starlink {lab}")
    axs[1, j].bar(g.index, 100*g.drop_mean, width=.003, color="tab:red"); axs[1, j].set_ylabel("drop %")
    axs[2, j].step(g.index, g.kp, where="post", color="tab:orange"); axs[2, j].set_ylabel("Kp")
    ax2 = axs[2, j].twinx(); ax2.plot(g.index, g.dst, c="tab:purple"); ax2.set_ylabel("Dst nT", color="tab:purple")
    axs[3, j].plot(g.index, g.roti_2nd, c="k", label="ROTI 2nd"); axs[3, j].set_ylabel("ROTI")
    ax3 = axs[3, j].twinx(); ax3.bar(g.index, g.rain_mm, width=.003, alpha=.4); ax3.set_ylabel("rain mm/h", color="tab:blue")
plt.tight_layout(); plt.savefig(f"{FIG}/05_starlink_vs_drivers.png", dpi=130); plt.close()

json.dump(res, open(f"{OUT}/starlink.json", "w"), indent=1)
print(json.dumps(res, indent=1))
