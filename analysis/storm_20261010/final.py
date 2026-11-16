"""Final (11 Oct) analysis of the 10-11 Oct 2026 G3 storm at the home station + archive stations.
Test windows fixed a priori from storm timing: MAIN 10 Oct 16:00 - 11 Oct 06:00 UTC, RECOVERY 11 Oct 06:00-17:00 UTC.
Comparison: quiet day 2 Oct, matched by UTC hour of day."""
from pathlib import Path as _RepoPath
import os as _repo_os
REPO_ROOT = _RepoPath(_repo_os.environ.get('REPO_ROOT', _RepoPath(__file__).resolve().parents[2]))
import sys, json, numpy as np, pandas as pd, matplotlib, sqlite3, datetime as dt
matplotlib.use("Agg"); import matplotlib.pyplot as plt
sys.path.insert(0, str(REPO_ROOT / 'analysis' / 'reanalysis')); from swlib import compute_rot, compute_roti, network, s4_from_cno, block_bootstrap_diff, wilson
sys.path.insert(0, str(REPO_ROOT / 'analysis' / 'global_logger')); from global_logger import archives
S = str(REPO_ROOT / 'data' / 'storm_20261010'); F = str(REPO_ROOT / 'analysis' / 'storm_20261010' / 'output')
T0, TM, TR, TE = [pd.Timestamp(x, tz="UTC") for x in ("2026-10-10T12:00", "2026-10-10T16:00", "2026-10-11T06:00", "2026-10-11T17:00")]
def tec(name):
    d = pd.read_csv(f"{S}/tec_{name}.csv"); d["t"] = pd.to_datetime(d.ts_utc, utc=True, format="ISO8601")
    return d.drop_duplicates(["sv", "t"]).sort_values(["sv", "t"])
st, qu = tec("storm"), tec("quiet")
st = st[st.t < TE]
def proc(d):
    ro = compute_roti(compute_rot(d, elev_mask=20)[0]); net = network(ro); s4 = s4_from_cno(d)
    return ro, net, s4
ro_s, net_s, s4_s = proc(st); ro_q, net_q, s4_q = proc(qu)
for x in (net_s, net_q): x["roti_med"] = x.roti_med.astype(float); x["roti_2nd"] = x.roti_2nd.astype(float)
# coverage
sec = st.t.dt.floor("s").drop_duplicates().sort_values(); g = sec.diff().dt.total_seconds()
cov = dict(epochs=len(sec), expected=int((TE - T0).total_seconds()), gaps_gt10s=int((g > 10).sum()), longest_gap_s=float(g.max()),
           sats_ge20_median=float(st[st.elev_deg >= 20].groupby(st.t.dt.floor("5min")).sv.nunique().median()), slip_flags=int(st.slip.sum()))
# quiet hour-matched: map each storm window onto 2 Oct by time of day
def tod(ix): return ix.hour * 3600 + ix.minute * 60
def window_stats(a, b, lab):
    ns = net_s[(net_s.index >= a) & (net_s.index < b)]
    secs = set(tod(ns.index)); nq = net_q[np.isin(tod(net_q.index), list(secs))]
    rs = ro_s[(ro_s.t >= a) & (ro_s.t < b)]; rq = ro_q[np.isin(tod(ro_q.t.dt), list(secs))] if False else ro_q[np.isin(ro_q.t.dt.hour * 3600 + ro_q.t.dt.minute * 60, list(secs))]
    ss = s4_s[(s4_s.t >= a) & (s4_s.t < b)].sort_values("win"); sq = s4_q[np.isin((s4_q.t.dt.hour * 60 + s4_q.t.dt.minute) * 60, [((h * 60 + m) * 60) for h, m in zip(ss.t.dt.hour, ss.t.dt.minute)])].sort_values("win")
    return {"window": lab, "n_net_windows": [len(ns), len(nq)],
            "net_median_storm_quiet": [float(ns.roti_med.median()), float(nq.roti_med.median())], "net_median_diff_CI": block_bootstrap_diff(ns.roti_med.values, nq.roti_med.values),
            "net_2nd_storm_quiet": [float(ns.roti_2nd.median()), float(nq.roti_2nd.median())], "net_2nd_diff_CI": block_bootstrap_diff(ns.roti_2nd.values, nq.roti_2nd.values),
            "pct_sat_windows_gt05_storm": [100 * v for v in wilson(int((rs.roti > .5).sum()), len(rs))],
            "pct_sat_windows_gt05_quiet": [100 * v for v in wilson(int((rq.roti > .5).sum()), len(rq))],
            "s4_median_storm_quiet": [float(ss.s4.median()), float(sq.s4.median())], "s4_diff_CI": block_bootstrap_diff(ss.s4.values, sq.s4.values, block=60, n=1000),
            "s4_pct_gt03": [100 * (ss.s4 > .3).mean(), 100 * (sq.s4 > .3).mean()]}
res = {"coverage": cov, "main": window_stats(TM, TR, "MAIN 10 Oct 16:00-11 Oct 06:00 UTC"), "recovery": window_stats(TR, TE, "RECOVERY 11 Oct 06-17 UTC")}
pk = net_s.roti_2nd.rolling(12).median(); res["peak_1h_median_of_2nd_roti"] = [float(pk.max()), str(pk.idxmax()), str((pk.idxmax() - pd.Timedelta("55min")).tz_convert("Europe/London"))]
pm = net_s.roti_med.rolling(12).median(); res["peak_1h_network_median_roti"] = [float(pm.max()), str((pm.idxmax() - pd.Timedelta("55min")).tz_convert("Europe/London")) + " to " + str(pm.idxmax().tz_convert("Europe/London"))]
# hourly table
h_s = pd.DataFrame({"med": net_s.roti_med.resample("1h").median(), "pct": ro_s.set_index("t").roti.resample("1h").apply(lambda v: 100 * (v > .5).mean() if len(v) else np.nan)})
ro_q["hr"] = ro_q.t.dt.hour; net_q["hr"] = net_q.index.hour
qh_med = net_q.groupby("hr").roti_med.median(); qh_pct = ro_q.groupby("hr").roti.apply(lambda v: 100 * (v > .5).mean())
h_s["q_med"] = [qh_med.get(i.hour) for i in h_s.index]; h_s["q_pct"] = [qh_pct.get(i.hour) for i in h_s.index]
h_s.round(3).to_csv(f"{F}/home_hourly_vs_quiet.csv")
# starlink
def sl(name):
    s = pd.read_csv(f"{S}/sl_{name}.csv"); s["t"] = pd.to_datetime(s.ts_utc, utc=True); return s.set_index("t")
sls, slq = sl("storm"), sl("quiet")
for key, a, b in [("main", TM, TR), ("recovery", TR, TE)]:
    x = sls[(sls.index >= a) & (sls.index < b)]; secs = set(x.index.hour * 3600 + x.index.minute * 60 + x.index.second)
    q = slq[np.isin(slq.index.hour * 3600 + slq.index.minute * 60 + slq.index.second, list(secs))]
    x5, q5 = x.resample("5min").agg({"ping_latency_ms": "median", "ping_drop_rate": "mean"}).dropna(), q.resample("5min").agg({"ping_latency_ms": "median", "ping_drop_rate": "mean"}).dropna()
    res[f"starlink_{key}"] = dict(latency_median=[float(x.ping_latency_ms.median()), float(q.ping_latency_ms.median())],
                                  latency_diff_CI=block_bootstrap_diff(x5.ping_latency_ms.values, q5.ping_latency_ms.values),
                                  drop_pct=[100 * float(x.ping_drop_rate.mean()), 100 * float(q.ping_drop_rate.mean())],
                                  drop_diff_pct_CI=[100 * v for v in block_bootstrap_diff(x5.ping_drop_rate.values, q5.ping_drop_rate.values, stat=np.mean)],
                                  outage_s=[int((x.ping_drop_rate >= 1).sum()), int((q.ping_drop_rate >= 1).sum())], seconds=[len(x), len(q)])
# drivers: GFZ nowcast + Kyoto quicklook fetched fresh, plus Pi solar wind
gkp = pd.DataFrame(archives.gfz_kp(dt.date(2026, 10, 10), dt.date(2026, 10, 11)), columns=["ts", "kp", "status"]); gkp["t"] = pd.to_datetime(gkp.ts, utc=True)
prod, dl = archives.kyoto_dst(2026, 10); kd = pd.DataFrame(dl, columns=["ts", "dst"]); kd["t"] = pd.to_datetime(kd.ts, utc=True); kd = kd[(kd.t >= T0) & (kd.t < TE)]
mag = pd.read_csv(f"{S}/sw_solar_wind_mag.csv"); mag["t"] = pd.to_datetime(mag.ts_utc, utc=True); mag = mag[(mag.t >= T0) & (mag.t < TE)]
pl = pd.read_csv(f"{S}/sw_solar_wind_plasma.csv"); pl["t"] = pd.to_datetime(pl.ts_utc, utc=True); pl = pl[(pl.t >= T0) & (pl.t < TE)]
wx = pd.read_csv(f"{S}/wx_weather_hourly.csv"); wx["t"] = pd.to_datetime(wx.ts_utc, utc=True); wx = wx[(wx.t >= T0) & (wx.t < TE)]
res["drivers"] = dict(gfz_kp=gkp[["ts", "kp", "status"]].values.tolist(), kyoto_product=prod, dst_min=[float(kd.dst.min()), str(kd.loc[kd.dst.idxmin(), "t"])],
                      dst_max=float(kd.dst.max()), bz_min=float(mag.bz_gsm.min()), bt_max=float(mag.bt.max()), v_max=float(pl.speed_kms.max()),
                      rain_main_mm=float(wx[(wx.t >= TM) & (wx.t < TR)].precipitation_mm.sum()), rain_recovery_mm=float(wx[wx.t >= TR].precipitation_mm.sum()),
                      rain_hours=int((wx.precipitation_mm > .1).sum()))
# ---- archive stations (10 Oct daily files, 11 Oct not in archive yet)
c = sqlite3.connect(f"{S}/global_roti.db")
arch = {}
for s in ["MORP", "HERS", "BRUX", "TRO1", "KIRU", "REYK", "NYA1"]:
    r = pd.read_sql("select window_start, roti from roti where station=? and (window_start like '2026-10-10%' or window_start like '2026-10-02%')", c, params=(s,))
    a = r[r.window_start.str.startswith("2026-10-10")]; q = r[r.window_start.str.startswith("2026-10-02")]
    a16 = a[a.window_start >= "2026-10-10T16"]; q16 = q[q.window_start >= "2026-10-02T16"]
    arch[s] = dict(day_pct=[100 * v for v in wilson(int((a.roti > .5).sum()), len(a))], quiet_pct=[100 * v for v in wilson(int((q.roti > .5).sum()), len(q))],
                   pct_16_24=[100 * v for v in wilson(int((a16.roti > .5).sum()), len(a16))], quiet_16_24=[100 * v for v in wilson(int((q16.roti > .5).sum()), len(q16))])
res["archive_10oct"] = arch
# home 16-24 UTC on 10 Oct for like-for-like with Morpeth
a = ro_s[(ro_s.t >= TM) & (ro_s.t < pd.Timestamp("2026-10-11", tz="UTC"))]; q = ro_q[ro_q.t.dt.hour >= 16]
res["home_16_24"] = dict(storm=[100 * v for v in wilson(int((a.roti > .5).sum()), len(a))], quiet=[100 * v for v in wilson(int((q.roti > .5).sum()), len(q))])
mn = pd.read_sql("select window_start, roti_med, roti_2nd from roti_network where station='MORP' and window_start like '2026-10-10%'", c)
mn["t"] = pd.to_datetime(mn.window_start, utc=True)
json.dump(res, open(f"{F}/results_final.json", "w"), indent=1, default=str)
print(json.dumps(res, indent=1, default=str)); print(h_s.round(2).to_string())
# ---- figures
fig, ax = plt.subplots(5, 1, figsize=(13, 14), sharex=True)
ax[0].bar(gkp.t, gkp.kp, width=0.12, align="edge", color=["tab:red" if v >= 7 else "tab:orange" if v >= 5 else "tab:green" for v in gkp.kp]); ax[0].set_ylabel("Kp (GFZ)"); ax[0].set_ylim(0, 9)
a0 = ax[0].twinx(); a0.plot(kd.t, kd.dst, "k.-"); a0.set_ylabel(f"Dst nT (Kyoto {prod.split('_')[1]})")
ax[1].plot(mag.t, mag.bz_gsm, lw=.6, label="Bz"); ax[1].plot(mag.t, mag.bt, lw=.6, label="Bt"); ax[1].axhline(0, c="k", lw=.5); ax[1].legend(fontsize=8); ax[1].set_ylabel("IMF nT")
a1 = ax[1].twinx(); a1.plot(pl.t, pl.speed_kms, c="grey", lw=.6); a1.set_ylabel("V km/s")
shift = lambda ix: ix
qn = net_q.copy(); 
for day in [pd.Timestamp("2026-10-10", tz="UTC"), pd.Timestamp("2026-10-11", tz="UTC")]:
    qq = qn.copy(); qq.index = qq.index - pd.Timestamp("2026-10-02", tz="UTC") + day
    qq = qq[(qq.index >= T0) & (qq.index < TE)]
    ax[2].plot(qq.index, qq.roti_med.rolling(6).median(), c="grey", lw=1, label="quiet 2 Oct (same UTC hour)" if day.day == 10 else None)
ax[2].plot(net_s.index, net_s.roti_med.rolling(6).median(), c="tab:blue", lw=1.3, label="home, network median (30-min running)")
ax[2].plot(net_s.index, net_s.roti_2nd.rolling(6).median(), c="tab:red", lw=.9, label="home, 2nd-highest satellite")
ax[2].plot(mn.t, mn.roti_med.rolling(6).median(), c="tab:green", lw=1.2, label="Morpeth network median (10 Oct only)")
ax[2].axhline(.5, ls=":", c="r"); ax[2].legend(fontsize=7, ncol=2); ax[2].set_ylabel("ROTI TECU/min")
sl5 = sls.resample("5min").agg({"ping_latency_ms": "median", "ping_drop_rate": "mean"})
ax[3].plot(sl5.index, sl5.ping_latency_ms, lw=.8); ax[3].set_ylabel("Starlink latency ms")
ax[4].plot(sl5.index, 100 * sl5.ping_drop_rate, lw=.8); ax[4].set_ylabel("Starlink drops %")
a4 = ax[4].twinx(); a4.bar(wx.t, wx.precipitation_mm, width=0.04, alpha=.3); a4.set_ylabel("rain mm/h")
for a in ax: a.axvspan(TM, TR, color="red", alpha=.05); a.axvline(TR, c="k", ls="--", lw=.6)
ax[0].set_title("10-11 Oct 2026 G3 storm at the home station (Belfast). Pink = a-priori MAIN window; after dashed line = RECOVERY")
ax[-1].set_xlim(T0, TE); plt.tight_layout(); plt.savefig(f"{F}/fig1_home_storm_full.png", dpi=115); plt.close()
fig, ax = plt.subplots(figsize=(10, 5)); st_ = list(arch) + ["HOME"]
ml = {"MORP": 57.2, "HERS": 52.7, "BRUX": 52.0, "TRO1": 67.5, "KIRU": 65.6, "REYK": 68.8, "NYA1": 76.3, "HOME": 57.3}
for s in st_:
    v = arch[s]["pct_16_24"] if s != "HOME" else res["home_16_24"]["storm"]; q = arch[s]["quiet_16_24"] if s != "HOME" else res["home_16_24"]["quiet"]
    ax.errorbar(ml[s], v[0], yerr=[[v[0] - v[1]], [v[2] - v[0]]], fmt="o", c="tab:red" if s != "HOME" else "k", capsize=3)
    ax.errorbar(ml[s] + .4, q[0], yerr=[[q[0] - q[1]], [q[2] - q[0]]], fmt="s", c="grey", capsize=3); ax.annotate(s, (ml[s], v[2] + 1), fontsize=8, ha="center")
ax.set_xlabel("geomagnetic latitude (deg)"); ax.set_ylabel("% satellite windows ROTI > 0.5, 16-24 UTC")
ax.set_title("10 Oct 2026, 16-24 UTC: storm (red, HOME black) vs own quiet 2 Oct (grey), 95% Wilson CI"); ax.grid(alpha=.3)
plt.tight_layout(); plt.savefig(f"{F}/fig2_stations_10oct.png", dpi=120); plt.close()
