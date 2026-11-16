"""06_sea_correlations.py - storm list from Kp, superposed-epoch analysis of the
drivers (and of whatever home-station ROTI exists around each onset), and
driver-vs-ionosphere correlation tests."""
import os, sys, json, sqlite3
import pandas as pd, numpy as np, matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.stats import spearmanr
sys.path.insert(0, os.path.dirname(__file__)); from swlib import *

kp = pd.read_csv(f"{DATA}/storm_exports/kp_index.csv"); kp["t"] = pd.to_datetime(kp.ts_utc, utc=True); kp = kp.set_index("t").kp
dst = pd.read_csv(f"{DATA}/storm_exports/dst_index.csv"); dst["t"] = pd.to_datetime(dst.ts_utc, utc=True); dst = dst.set_index("t").dst
c = sqlite3.connect(f"file:{DATA}/spaceweather.db?mode=ro", uri=True)
mag = pd.read_sql("select ts_utc,bz_gsm from solar_wind_mag", c); mag["t"] = pd.to_datetime(mag.ts_utc, utc=True); mag = mag.set_index("t").bz_gsm
pl = pd.read_sql("select ts_utc,speed_kms from solar_wind_plasma", c); pl["t"] = pd.to_datetime(pl.ts_utc, utc=True); pl = pl.set_index("t").speed_kms
mag = mag[(mag > -900) & (mag < 900)]; pl = pl[(pl > 0) & (pl < 3000)]          # remove fill values
bz_h = mag.resample("1h").median(); v_h = pl.resample("1h").median()

# Dst spikes: single hours that differ from both neighbours by >10 nT
dr = dst.rolling(3, center=True, min_periods=1).median()
spikes = dst[(dst - dr).abs() > 10]
res = {"dst_single_hour_spikes": {str(k): float(v) for k, v in spikes.items()}}

# ---- storm list: Kp >= 5 blocks, merged if within 24 h
s = kp[kp >= 5]; onsets = []
for t in s.index:
    if not onsets or (t - onsets[-1][-1]) > pd.Timedelta("24h"): onsets.append([t])
    else: onsets[-1].append(t)
storms = []
for grp in onsets:
    t0 = grp[0]; w = slice(t0 - pd.Timedelta("6h"), t0 + pd.Timedelta("36h"))
    storms.append(dict(onset=str(t0), kp_max=float(kp[w].max()), dst_min_raw=float(dst[w].min()),
                       dst_min_robust=float(dr[w].min()), bz_min_hourly=float(bz_h[w].min()) if len(bz_h[w]) else None,
                       vsw_max=float(v_h[w].max()) if len(v_h[w]) else None))
res["storms_kp_ge5"] = storms
for x in storms: print(x)

# ---- superposed epoch of the drivers
lags = np.arange(-24, 49)
def sea(series):
    M = []
    for x in storms:
        t0 = pd.Timestamp(x["onset"]).floor("h")
        M.append(series.reindex([t0 + pd.Timedelta(hours=int(l)) for l in lags]).to_numpy())
    return np.array(M, float)
kp_h = kp.resample("1h").ffill()
fig, axs = plt.subplots(4, 1, figsize=(9, 10), sharex=True)
for ax, (name, ser) in zip(axs, [("Kp", kp_h), ("Dst robust (nT)", dr), ("Bz GSM hourly median (nT)", bz_h), ("Solar-wind speed (km/s)", v_h)]):
    M = sea(ser)
    for row, x in zip(M, storms): ax.plot(lags, row, lw=.8, alpha=.6, label=x["onset"][:10])
    mean = np.nanmean(M, axis=0); ax.plot(lags, mean, "k", lw=2.5, label="superposed mean")
    ax.axvline(0, c="r", lw=.8); ax.set_ylabel(name)
axs[0].legend(fontsize=7, ncol=3); axs[-1].set_xlabel("hours from storm onset (first Kp≥5 block)")
axs[0].set_title("Superposed-epoch analysis of the space-weather driver (5 storms)")
plt.tight_layout(); plt.savefig(f"{FIG}/09_sea_drivers.png", dpi=130); plt.close()

# ---- home ROTI around onsets (only the exported windows exist)
net = pd.read_csv(f"{OUT}/home_network_roti_m30.csv", index_col=0, parse_dates=True)
fig, ax = plt.subplots(figsize=(9, 4))
cover = {}
for x in storms:
    t0 = pd.Timestamp(x["onset"])
    g = net[(net.index > t0 - pd.Timedelta("24h")) & (net.index < t0 + pd.Timedelta("48h"))]
    cover[x["onset"]] = round(len(g)/12, 1)
    if len(g):
        h = (g.index - t0).total_seconds()/3600
        ax.plot(h, g.roti_2nd.rolling(3, min_periods=1).median(), ".", ms=3, label=x["onset"][:10])
q = net[net.window.str.startswith("Q")]
ax.axhspan(q.roti_2nd.quantile(.05), q.roti_2nd.quantile(.95), color="grey", alpha=.3, label="quiet 5-95% range")
ax.axvline(0, c="r"); ax.set_xlabel("hours from storm onset"); ax.set_ylabel("home ROTI 2nd-highest (TECU/min)")
ax.set_title("Home-station ROTI around storm onsets (only the exported hours exist)"); ax.legend(fontsize=7)
plt.tight_layout(); plt.savefig(f"{FIG}/10_sea_home_roti.png", dpi=130); plt.close()
res["home_hours_available_around_each_onset"] = cover

# ---- correlations: home 5-min network ROTI vs Kp / Dst (all windows pooled)
net["kp"] = kp.reindex(net.index, method="ffill").to_numpy()
net["dst"] = dr.reindex(net.index.floor("h")).to_numpy()
for col in ["kp", "dst"]:
    for y in ["roti_med", "roti_2nd"]:
        rho, p, n = spearman_block_perm(net[col].values, net[y].values, block=12)
        res[f"home_spearman_{col}_vs_{y}"] = dict(rho=round(rho, 3), p_block_perm=round(p, 4), n=n)
# high latitude: daily Kp max vs daily disturbed fraction (n = 6 days per station)
hl = json.load(open(f"{OUT}/highlat.json"))["days"]
days = {"02 Aug": "2026-08-02", "08 Aug": "2026-08-08", "08 Sep": "2026-09-08", "02 Oct (quiet)": "2026-10-02", "04 Oct": "2026-10-04", "05 Oct": "2026-10-05"}
for st in ["TRO1", "NYA2"]:
    x = [kp[pd.Timestamp(d, tz="UTC"):pd.Timestamp(d, tz="UTC") + pd.Timedelta("23h59min")].max() for d in days.values()]
    xs = [kp[pd.Timestamp(d, tz="UTC"):pd.Timestamp(d, tz="UTC") + pd.Timedelta("23h59min")].sum() for d in days.values()]
    y = [hl[f"{st} {k}"]["m20"]["frac_sat_gt05"][0] for k in days]
    r1 = spearmanr(xs, y)
    res[f"{st}_daily_sumKp_vs_disturbed_fraction"] = dict(rho=round(r1.statistic, 3), p=round(r1.pvalue, 4), n=6, sumKp=xs, frac=y)
json.dump(res, open(f"{OUT}/sea_corr.json", "w"), indent=1, default=str)
print(json.dumps({k: v for k, v in res.items() if k != "storms_kp_ge5"}, indent=1, default=str))
