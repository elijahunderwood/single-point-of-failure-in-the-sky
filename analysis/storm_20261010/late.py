from pathlib import Path as _RepoPath
import os as _repo_os
REPO_ROOT = _RepoPath(_repo_os.environ.get('REPO_ROOT', _RepoPath(__file__).resolve().parents[2]))
import sys, json, numpy as np, pandas as pd
sys.path.insert(0, str(REPO_ROOT / 'analysis' / 'reanalysis')); from swlib import compute_rot, compute_roti, network, block_bootstrap_diff, wilson
out = {}
for d in ["2026-10-10", "2026-10-02"]:
    df = pd.read_csv(f"st/tec_{d}.csv"); df["t"] = pd.to_datetime(df.ts_utc, utc=True, format="ISO8601")
    df = df[(df.t >= pd.Timestamp(f"{d}T17:30", tz="UTC")) & (df.t < pd.Timestamp(f"{d}T19:05", tz="UTC"))].drop_duplicates(["sv", "t"]).sort_values(["sv", "t"])
    ro = compute_roti(compute_rot(df)[0]); net = network(ro)
    out[d] = dict(net=net, k=int((ro.roti > .5).sum()), n=len(ro), med=float(net.roti_med.astype(float).median()), m2=float(net.roti_2nd.astype(float).median()))
a, b = out["2026-10-10"], out["2026-10-02"]
print("17:30-19:05 UTC  storm net median ROTI %.3f vs quiet %.3f" % (a["med"], b["med"]), "diff+CI", block_bootstrap_diff(a["net"].roti_med.astype(float).values, b["net"].roti_med.astype(float).values))
print("2nd-highest median %.3f vs %.3f" % (a["m2"], b["m2"]), block_bootstrap_diff(a["net"].roti_2nd.astype(float).values, b["net"].roti_2nd.astype(float).values))
print("frac sat-windows >0.5 storm", wilson(a["k"], a["n"]), "quiet", wilson(b["k"], b["n"]))
