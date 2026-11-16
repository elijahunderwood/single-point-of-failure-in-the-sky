"""Preliminary look at the 10 Oct 2026 G3 storm in the home-station data, compared with
the same UTC hours yesterday (9 Oct) and on the quiet day (2 Oct). Same pipeline as the reanalysis."""
from pathlib import Path as _RepoPath
import os as _repo_os
REPO_ROOT = _RepoPath(_repo_os.environ.get('REPO_ROOT', _RepoPath(__file__).resolve().parents[2]))
import sys, json, numpy as np, pandas as pd, matplotlib
matplotlib.use("Agg"); import matplotlib.pyplot as plt
sys.path.insert(0, str(REPO_ROOT / 'analysis' / 'reanalysis')); from swlib import compute_rot, compute_roti, network, s4_from_cno, block_bootstrap_diff, wilson
D = str(REPO_ROOT / 'data' / 'storm_20261010'); F = str(REPO_ROOT / 'analysis' / 'storm_20261010')
days = {"storm 10 Oct": "2026-10-10", "yesterday 9 Oct": "2026-10-09", "quiet 2 Oct": "2026-10-02"}
end_tod = pd.read_csv(f"{D}/tec_2026-10-10.csv", usecols=["ts_utc"]).ts_utc.max()[11:19]   # matched hours 12:00 -> latest
R = {}; nets = {}; res = {"window_utc": f"12:00-{end_tod}"}
for lab, d in days.items():
    df = pd.read_csv(f"{D}/tec_{d}.csv"); df["t"] = pd.to_datetime(df.ts_utc, utc=True, format="ISO8601")
    df = df[df.t < pd.Timestamp(f"{d}T{end_tod}", tz="UTC")].drop_duplicates(["sv", "t"]).sort_values(["sv", "t"])
    sec = df.t.dt.floor("s").drop_duplicates().sort_values()
    gaps = sec.diff().dt.total_seconds(); span = (sec.max() - sec.min()).total_seconds()
    vis = df[df.elev_deg >= 20].groupby(df.t.dt.floor("5min")).sv.nunique()
    rot, qc = compute_rot(df, elev_mask=20)
    ro = compute_roti(rot); net = network(ro); nets[lab] = net
    s4 = s4_from_cno(df)
    k = int((ro.roti > 0.5).sum()); n = len(ro)
    R[lab] = dict(rows=len(df), epochs=len(sec), coverage_pct=round(100 * len(sec) / (span + 1), 1),
                  gaps_gt10s=int((gaps > 10).sum()), longest_gap_s=float(gaps.max()),
                  sats_ge20_median=float(vis.median()), slip_flags=int(df.slip.sum()), arcs=qc["arcs"],
                  rot_rejected_pct=round(100 * qc["rot_rejected"] / max(1, qc["rot_total"]), 3),
                  sat_windows=n, frac_gt05=wilson(k, n), roti_median=float(ro.roti.median()), roti_p95=float(ro.roti.quantile(.95)),
                  net_med_median=float(net.roti_med.median()), net_2nd_max=float(net.roti_2nd.max()),
                  net_2nd_max_time=str(net.roti_2nd.astype(float).idxmax()),
                  s4_median=float(s4.s4.median()), s4_p99=float(s4.s4.quantile(.99)), s4_frac_gt03=wilson(int((s4.s4 > .3).sum()), len(s4)))
    R[lab]["_ro"] = ro; R[lab]["_s4"] = s4
for b in ["yesterday 9 Oct", "quiet 2 Oct"]:
    a, c = nets["storm 10 Oct"], nets[b]
    res[f"net_median_roti_diff_vs_{b}"] = block_bootstrap_diff(a.roti_med.astype(float).to_numpy(), c.roti_med.astype(float).to_numpy())
    res[f"net_2nd_roti_diff_vs_{b}"] = block_bootstrap_diff(a.roti_2nd.astype(float).to_numpy(), c.roti_2nd.astype(float).to_numpy())
    res[f"s4_median_diff_vs_{b}"] = block_bootstrap_diff(R["storm 10 Oct"]["_s4"].sort_values("win").s4.to_numpy(), R[b]["_s4"].sort_values("win").s4.to_numpy(), block=60, n=1000)
# ---- Starlink
sl = {}
for lab, d in days.items():
    s = pd.read_csv(f"{D}/sl_{d}.csv"); s["t"] = pd.to_datetime(s.ts_utc, utc=True)
    s = s[s.t < pd.Timestamp(f"{d}T{end_tod}", tz="UTC")]
    m = s.set_index("t").resample("5min").agg({"ping_latency_ms": "median", "ping_drop_rate": "mean"})
    sl[lab] = m
    res[f"starlink_{lab}"] = dict(seconds=len(s), latency_median=float(s.ping_latency_ms.median()), latency_p95=float(s.ping_latency_ms.quantile(.95)),
                                  drop_mean_pct=100 * float(s.ping_drop_rate.mean()), outage_seconds=int((s.ping_drop_rate >= 1).sum()))
for b in ["yesterday 9 Oct", "quiet 2 Oct"]:
    res[f"starlink_latency_diff_vs_{b}"] = block_bootstrap_diff(sl["storm 10 Oct"].ping_latency_ms.dropna().to_numpy(), sl[b].ping_latency_ms.dropna().to_numpy())
    res[f"starlink_drop_pct_diff_vs_{b}"] = [100 * x for x in block_bootstrap_diff(sl["storm 10 Oct"].ping_drop_rate.dropna().to_numpy(), sl[b].ping_drop_rate.dropna().to_numpy(), stat=np.mean)]
# ---- drivers + weather
kp = pd.read_csv(f"{D}/sw_kp_index.csv"); kp["t"] = pd.to_datetime(kp.ts_utc, utc=True)
dst = pd.read_csv(f"{D}/sw_dst_index.csv"); dst["t"] = pd.to_datetime(dst.ts_utc, utc=True)
mag = pd.read_csv(f"{D}/sw_solar_wind_mag.csv"); mag["t"] = pd.to_datetime(mag.ts_utc, utc=True)
pl = pd.read_csv(f"{D}/sw_solar_wind_plasma.csv"); pl["t"] = pd.to_datetime(pl.ts_utc, utc=True)
wx = pd.read_csv(f"{D}/wx_weather_hourly.csv"); wx["t"] = pd.to_datetime(wx.ts_utc, utc=True)
for lab, d in days.items():
    a, b = pd.Timestamp(f"{d}T12:00", tz="UTC"), pd.Timestamp(f"{d}T{end_tod}", tz="UTC")
    sel = lambda x: x[(x.t >= a) & (x.t < b)]
    res[f"drivers_{lab}"] = dict(kp=sel(kp)[["ts_utc", "kp"]].values.tolist(), dst_min=float(sel(dst).dst.min()) if len(sel(dst)) else None,
                                 bz_min=float(sel(mag).bz_gsm.min()) if len(sel(mag)) else None, bt_max=float(sel(mag).bt.max()) if len(sel(mag)) else None,
                                 v_max=float(sel(pl).speed_kms.max()) if len(sel(pl)) else None, n_max=float(sel(pl).density.max()) if len(sel(pl)) else None,
                                 rain_mm_total=float(sel(wx).precipitation_mm.sum()), rain_hours=int((sel(wx).precipitation_mm > 0.1).sum()),
                                 cloud_mean=float(sel(wx).cloud_cover_pct.mean()))
for lab in R:
    for k in ("_ro", "_s4"): R[lab].pop(k)
res["gnss"] = R
json.dump(res, open(f"{F}/results.json", "w"), indent=1, default=str)
print(json.dumps(res, indent=1, default=str))
# ---- Figure 1: timeline of storm day
d = "2026-10-10"; a, b = pd.Timestamp(f"{d}T00:00", tz="UTC"), pd.Timestamp(f"{d}T{end_tod}", tz="UTC") + pd.Timedelta("30min")
fig, ax = plt.subplots(5, 1, figsize=(12, 13), sharex=True)
k2 = kp[(kp.t >= a - pd.Timedelta("3h")) & (kp.t < b)]
ax[0].bar(k2.t, k2.kp, width=0.12, align="edge", color=["tab:red" if v >= 7 else "tab:orange" if v >= 5 else "tab:green" for v in k2.kp]); ax[0].set_ylabel("Kp"); ax[0].set_ylim(0, 9)
x = dst[(dst.t >= a) & (dst.t < b)]; a0 = ax[0].twinx(); a0.plot(x.t, x.dst, "k.-"); a0.set_ylabel("Dst nT")
x = mag[(mag.t >= a) & (mag.t < b)]; ax[1].plot(x.t, x.bz_gsm, lw=.7, label="Bz GSM"); ax[1].plot(x.t, x.bt, lw=.7, label="Bt"); ax[1].axhline(0, c="k", lw=.5); ax[1].legend(); ax[1].set_ylabel("IMF nT")
x = pl[(pl.t >= a) & (pl.t < b)]; a1 = ax[1].twinx(); a1.plot(x.t, x.speed_kms, c="grey", lw=.7); a1.set_ylabel("V km/s", color="grey")
tod = lambda net, day: net.set_axis(net.index + (pd.Timestamp(d, tz="UTC") - pd.Timestamp(day, tz="UTC")))
for lab, day in days.items():
    n = tod(nets[lab], day); ax[2].plot(n.index, n.roti_2nd.astype(float), lw=1 if "storm" in lab else .8, label=lab, alpha=1 if "storm" in lab else .6)
ax[2].axhline(0.5, ls=":", c="r"); ax[2].set_ylabel("network ROTI\n2nd-highest (TECU/min)"); ax[2].legend(fontsize=8)
for lab, day in days.items():
    m = tod(sl[lab], day); ax[3].plot(m.index, m.ping_latency_ms, label=lab, lw=.9, alpha=1 if "storm" in lab else .6)
    ax[4].plot(m.index, 100 * m.ping_drop_rate, label=lab, lw=.9, alpha=1 if "storm" in lab else .6)
ax[3].set_ylabel("Starlink latency\n5-min median ms"); ax[4].set_ylabel("Starlink drops\n5-min mean %"); ax[3].legend(fontsize=8)
x = wx[(wx.t >= a) & (wx.t < b)]; a4 = ax[4].twinx(); a4.bar(x.t, x.precipitation_mm, width=0.04, color="tab:blue", alpha=.3); a4.set_ylabel("rain mm/h", color="tab:blue")
ax[0].set_title(f"Home station, 10 Oct 2026 G3 storm (preliminary, data to {end_tod} UTC); 9 Oct and 2 Oct overlaid at the same UTC time")
ax[-1].set_xlim(pd.Timestamp(f"{d}T12:00", tz="UTC"), b); ax[-1].set_xlabel("UTC")
plt.tight_layout(); plt.savefig(f"{F}/fig1_storm_timeline.png", dpi=120); plt.close()
