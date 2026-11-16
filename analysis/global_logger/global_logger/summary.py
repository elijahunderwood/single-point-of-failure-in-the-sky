"""summary.py - cross-storm analysis:
 * per-storm figures (calls plots.storm_figure)
 * % disturbed (storm minus the station's own quiet day) vs geomagnetic latitude, coloured by Kp
 * Kp threshold for the Belfast-latitude band: logistic fit of P(3-h block disturbed) vs Kp,
   95% CI from a bootstrap that resamples whole days (blocks inside a day are not independent).
"""
import os, json
import numpy as np, pandas as pd, matplotlib
matplotlib.use("Agg"); import matplotlib.pyplot as plt
from . import plots

QUIET_FOR = {"may2024": "quiet_may2024", "apr2023": "quiet_may2024", "aug2024": "quiet_may2024",
             "jun2025": "quiet_may2024", "oct2024": "quiet_oct2024", "nov2025": "quiet_oct2024",
             "oct2026": "quiet_oct2026"}

def logit_fit(x, y, iters=50):
    """Logistic regression P = 1/(1+exp(-(b0+b1 x))) by Newton-Raphson (tiny ridge for stability)."""
    X = np.c_[np.ones_like(x), x]; b = np.zeros(2)
    for _ in range(iters):
        p = 1 / (1 + np.exp(-X @ b)); W = p * (1 - p)
        H = X.T @ (X * W[:, None]) + 1e-6 * np.eye(2); g = X.T @ (y - p)
        step = np.linalg.solve(H, g); b += step
        if np.abs(step).max() < 1e-8: break
    return b

def kp_threshold(blocks, station, thr_frac, nboot=2000, seed=0):
    d = blocks[blocks.station == station].dropna(subset=["kp"])
    x, y = d.kp.to_numpy(), (d.frac > thr_frac).astype(float).to_numpy()
    out = dict(station=station, thr_frac=thr_frac, n_blocks=len(d), n_days=d.day.nunique(), n_disturbed=int(y.sum()),
               kp_max_seen=float(x.max()) if len(x) else None)
    if y.sum() == 0:
        out["kp50"] = None; out["note"] = f"no disturbed blocks up to Kp {x.max():.2f}: threshold is above this"; return out
    if y.sum() == len(y): out["kp50"] = None; out["note"] = "all blocks disturbed"; return out
    b = logit_fit(x, y); out["kp50"] = float(-b[0] / b[1]); out["slope"] = float(b[1])
    # empirical check: lowest Kp with a disturbed block, highest Kp without one
    out["lowest_kp_disturbed"] = float(x[y == 1].min()); out["highest_kp_quiet"] = float(x[y == 0].max())
    rng = np.random.default_rng(seed); days = d.day.unique(); bs = []
    g = {k: v for k, v in d.groupby("day")}
    for _ in range(nboot):
        s = pd.concat([g[k] for k in rng.choice(days, len(days))])
        ys = (s.frac > thr_frac).astype(float).to_numpy()
        if 0 < ys.sum() < len(ys):
            bb = logit_fit(s.kp.to_numpy(), ys)
            if bb[1] > 0: bs.append(-bb[0] / bb[1])
    bs = np.array(bs); bs = bs[(bs > 0) & (bs < 12)]
    out["kp50_ci95"] = [float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))] if len(bs) > 100 else None
    out["boot_ok"] = int(len(bs)); out["b"] = b.tolist()
    return out

def run(conn, cfg):
    figdir = cfg["paths"]["figures"]; storms = {s["name"]: s for s in cfg["storms"]}
    for name, q in QUIET_FOR.items():
        try: plots.storm_figure(conn, cfg, name, q)
        except Exception as e: print("plot failed", name, e)
    st = pd.read_sql("select station, geomag_lat from stations", conn).set_index("station").geomag_lat
    st["HOME"] = 57.3        # Belfast 54.6N 5.9W, same dipole model
    ro = pd.read_sql("select station, window_start, roti from roti", conn)
    ro["day"] = ro.window_start.str[:10]
    ro["t"] = pd.to_datetime(ro.window_start, utc=True)
    daily = ro.groupby(["station", "day"]).roti.agg(frac=lambda v: 100 * (v > 0.5).mean(), n="count").reset_index()
    # ---- cross-storm: storm-day (worst day) minus own quiet day
    rows = []
    for name, q in QUIET_FOR.items():
        sd = [str(d) for d in storms[name]["days"]]; qd = [str(d) for d in storms[q]["days"]]
        for s in st.index:
            a = daily[(daily.station == s) & daily.day.isin(sd)]; b = daily[(daily.station == s) & daily.day.isin(qd)]
            if a.empty or b.empty: continue
            worst = a.loc[a.frac.idxmax()]
            rows.append(dict(storm=name, station=s, geomag_lat=st[s], kp_max=storms[name]["kp_max"], dst_min=storms[name]["dst_min"],
                             storm_pct_worst_day=round(worst.frac, 2), worst_day=worst.day,
                             storm_pct_all_days=round(float(np.average(a.frac, weights=a.n)), 2),
                             quiet_pct=round(float(np.average(b.frac, weights=b.n)), 2),
                             excess_pct=round(worst.frac - float(np.average(b.frac, weights=b.n)), 2)))
    X = pd.DataFrame(rows); X.to_csv(os.path.join(figdir, "cross_storm_table.csv"), index=False)
    fig, ax = plt.subplots(figsize=(11, 6))
    sc = ax.scatter(X.geomag_lat, X.excess_pct, c=X.kp_max, cmap="plasma", vmin=5, vmax=9, s=55, edgecolor="k")
    for name in QUIET_FOR:
        x = X[X.storm == name].sort_values("geomag_lat")
        ax.plot(x.geomag_lat, x.excess_pct, "-", lw=0.8, alpha=0.5, color=plt.cm.plasma((storms[name]["kp_max"] - 5) / 4))
    ax.axvspan(55, 59, color="tab:green", alpha=0.12, label="Belfast / Morpeth band (~57° geomag)")
    ax.axhline(0, color="k", lw=0.8); ax.set_xlabel("geomagnetic latitude (deg, IGRF-2025 dipole)")
    ax.set_ylabel("% disturbed (worst storm day) minus\nsame station's quiet day (percentage points)")
    plt.colorbar(sc, label="storm Kp max (GFZ)"); ax.legend(loc="upper left"); ax.grid(alpha=.3)
    ax.set_title("Storm-time ROTI disturbance vs geomagnetic latitude, all storms (each dot = one station, one storm)")
    plt.tight_layout(); plt.savefig(os.path.join(figdir, "cross_storm_excess_vs_maglat.png"), dpi=130); plt.close()
    # ---- Kp threshold
    kp = pd.read_sql("select ts_utc, kp from kp_index", conn); kp["t"] = pd.to_datetime(kp.ts_utc, utc=True)
    ro["blk"] = ro.t.dt.floor("3h")
    blocks = ro.groupby(["station", "blk"]).roti.agg(frac=lambda v: (v > 0.5).mean(), n="count").reset_index()
    blocks = blocks[blocks.n >= 50]           # at least ~1/4 of a normal 3-h block of satellite windows
    blocks = blocks.merge(kp[["t", "kp"]], left_on="blk", right_on="t", how="left")
    blocks["day"] = blocks.blk.dt.strftime("%Y-%m-%d")
    res = []
    for s in ["MORP", "HOME", "HERS", "BRUX", "TRO1", "KIRU", "REYK"]:
        for thr in (0.01, 0.02, 0.05):
            res.append(kp_threshold(blocks, s, thr))
    json.dump(res, open(os.path.join(figdir, "kp_threshold.json"), "w"), indent=1)
    fig, axs = plt.subplots(1, 2, figsize=(13, 5))
    for ax, s in zip(axs, ["MORP", "HOME"]):
        d = blocks[blocks.station == s].dropna(subset=["kp"])
        ax.scatter(d.kp + np.random.default_rng(1).uniform(-.08, .08, len(d)), 100 * d.frac, s=14, alpha=.6)
        r = next(x for x in res if x["station"] == s and x["thr_frac"] == 0.02)
        ax.axhline(2, ls=":", c="grey")
        if s == "HOME":
            from numpy import corrcoef
            rho = pd.Series(d.kp.to_numpy()).rank().corr(pd.Series(d.frac.to_numpy()).rank())
            ax.set_title(f"HOME (Belfast, 1-Hz u-blox): no Kp trend up to Kp {d.kp.max():.2f}, Spearman rho = {rho:.2f}\n"
                         "quiet-day floor ~4-5% (higher receiver noise) so no logistic fit; storm adds nothing", fontsize=9)
        elif r.get("kp50"):
            kk = np.linspace(0, 9, 200); p = 1 / (1 + np.exp(-(r["b"][0] + r["b"][1] * kk)))
            a2 = ax.twinx(); a2.plot(kk, p, "r"); a2.set_ylim(0, 1); a2.set_ylabel("fitted P(block disturbed)", color="r")
            ci = r.get("kp50_ci95")
            if ci: a2.axvspan(*ci, color="r", alpha=0.12)
            ax.set_title(f"{s}: Kp50 = {r['kp50']:.2f}" + (f" (95% CI {ci[0]:.2f}-{ci[1]:.2f})" if ci else ""))
        else:
            ax.set_title(f"{s}: {r.get('note')}")
        ax.set_xlabel("Kp (3-hour, GFZ)"); ax.set_ylabel("% of satellite windows ROTI > 0.5 in the 3-h block"); ax.set_xlim(-0.3, 9.3)
    plt.tight_layout(); plt.savefig(os.path.join(figdir, "kp_threshold_morpeth_home.png"), dpi=130); plt.close()
    return X, res
