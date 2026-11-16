"""04_highlat.py - Tromso (TRO1) and Ny-Alesund (NYA2) 30-s RINEX -> TEC -> ROTI,
with satellite elevations computed from IGS broadcast orbits (so a proper
elevation mask is used, instead of a signal-strength filter)."""
from pathlib import Path as _RepoPath
import os as _repo_os
REPO_ROOT = _RepoPath(_repo_os.environ.get('REPO_ROOT', _RepoPath(__file__).resolve().parents[2]))
import os, sys, json, glob
import pandas as pd, numpy as np, matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
sys.path.insert(0, os.path.dirname(__file__)); from swlib import *

NAV = str(_repo_os.environ.get('NAV_DIR', REPO_ROOT / 'data' / 'nav'))
DAYS = {214: "02 Aug", 220: "08 Aug", 251: "08 Sep", 275: "02 Oct (quiet)", 277: "04 Oct", 278: "05 Oct"}
L1W, L2W = C/F1, C/F2

def process(path, doy):
    cache = f"{OUT}/hilat_{os.path.basename(path)[:4]}_{doy}.pkl"
    if os.path.exists(cache): return pd.read_pickle(cache)
    o = read_rinex3_gps(path); rx = o.attrs["rx"]
    eph = pd.DataFrame(read_nav2(f"{NAV}/brdc{doy}.n"))
    day0 = pd.Timestamp(2026, 1, 1, tz="UTC") + pd.Timedelta(days=doy-1)
    gps0 = pd.Timestamp(1980, 1, 6, tz="UTC")
    o["tow"] = (o.tsec - (gps0 - pd.Timestamp(0, tz="UTC")).total_seconds()) % 604800 + 18   # UTC->GPS time (+18 s)
    el = np.full(len(o), np.nan)
    for sv, g in o.groupby("sv"):
        E = eph[eph.prn == sv]
        if E.empty: continue
        toes = E.toe.to_numpy()
        # elevation every 5 min, interpolate (satellites move slowly)
        tg = np.arange(g.tow.min(), g.tow.max() + 300, 300)
        eg = [elevation(rx, sat_ecef(E.iloc[np.argmin(np.abs(((t - toes + 302400) % 604800) - 302400))].to_dict(), t)) for t in tg]
        el[g.index] = np.interp(g.tow, tg, eg)
    o["elev_deg"] = el
    o["phase_tec"] = K_TEC * (o.L1 * L1W - o.L2 * L2W)
    o["slip"] = (o.lli & 1 > 0).astype(int)
    o["t"] = pd.to_datetime(o.tsec, unit="s", utc=True)
    o = o.dropna(subset=["phase_tec", "elev_deg"])
    o.attrs = {}
    o[["t", "sv", "elev_deg", "phase_tec", "slip", "S1"]].to_pickle(cache)
    return o

res, series = {}, {}
for st in ["TRO1", "NYA2"]:
    for doy, lab in DAYS.items():
        f = glob.glob(f"{X}/hilat_rinex/{st}*_2026{doy}0000_01D_30S_MO.rnx")[0]
        o = process(f, doy)
        r = {}
        for mask in (20, 30):
            rot, qc = compute_rot(o, elev_mask=mask, base_s=30, gap_s=45, jump_tecu=5.0)
            ro = compute_roti(rot); net = network(ro)
            k = int((ro.roti > .5).sum()); p, lo_, hi_ = wilson(k, len(ro))
            r[f"m{mask}"] = dict(sat_windows=len(ro), roti_median=round(ro.roti.median(), 4),
                                 frac_sat_gt05=[round(p, 4), round(lo_, 4), round(hi_, 4)],
                                 frac_net_med_gt05=round(float((net.roti_med > .5).mean()), 4),
                                 frac_net_2nd_gt05=round(float((net.roti_2nd > .5).mean()), 4),
                                 rot_rejected_pct=round(100*qc["rot_rejected"]/max(1, qc["rot_total"]), 2))
            if mask == 20: series[(st, doy)] = net
        # the previous analysis' approach: no elevation mask, signal-strength (S1>=40 dB-Hz) filter instead
        o2 = o[o.S1 >= 40].copy(); o2["elev_deg"] = 90.0
        rot2, _ = compute_rot(o2, elev_mask=0, base_s=30, gap_s=45, jump_tecu=5.0); ro2 = compute_roti(rot2)
        r["snr40_nomask"] = dict(roti_median=round(ro2.roti.median(), 4), frac_sat_gt05=round(float((ro2.roti > .5).mean()), 4))
        r["l2_signal"] = "see header"; res[f"{st} {lab}"] = r
        print(st, lab, json.dumps(r))

# effect vs own quiet-day control
eff = {}
for st in ["TRO1", "NYA2"]:
    q = series[(st, 275)]
    for doy, lab in DAYS.items():
        if doy == 275: continue
        s = series[(st, doy)]
        dmed, a, b = block_bootstrap_diff(s.roti_med.values, q.roti_med.values, block=6)
        eff[f"{st} {lab}"] = dict(diff_net_median=round(dmed, 4), ci95=[round(a, 4), round(b, 4)],
                                  ratio=round(s.roti_med.median()/q.roti_med.median(), 2))
json.dump(dict(days=res, effects=eff), open(f"{OUT}/highlat.json", "w"), indent=1)
print(json.dumps(eff, indent=1))

fig, axs = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
for ax, st in zip(axs, ["TRO1", "NYA2"]):
    for doy, lab in DAYS.items():
        n = series[(st, doy)]
        hrs = (n.index - n.index.normalize()).total_seconds()/3600
        ax.plot(hrs, n.roti_med.rolling(6, min_periods=1).median(), lw=2.5 if doy == 275 else 1,
                c="grey" if doy == 275 else None, label=lab)
    ax.axhline(.5, ls="--", c="k", lw=.7); ax.set_ylabel("network median ROTI\n(TECU/min, 30-min smoothed)")
    ax.set_title(f"{st}: storm days vs quiet control (grey), 20° elevation mask"); ax.legend(fontsize=7, ncol=3)
axs[1].set_xlabel("hour of day (UTC)")
plt.tight_layout(); plt.savefig(f"{FIG}/06_highlat_roti_by_hour.png", dpi=130); plt.close()
