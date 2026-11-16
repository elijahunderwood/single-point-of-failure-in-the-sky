#!/usr/bin/env python3
"""Is a flare + storm overlap worse than the sum of its parts?  (UQRG 15-min global vertical TEC maps, 1998-2026)
Anomaly A(t) = TEC(t) - quiet baseline (median of the same UT slot on up to 5 of the 15 preceding days with daily max Kp < 4.67).
Metric 1, FLARE JUMP D: dayside (solar zenith angle < 60 deg at the flare time, area-weighted) mean of
   [mean A over maps in (t, t+30 min]] - [mean A over maps in [t-45, t-15 min]],  t = GOES X-ray peak.
   Measured for: overlap flare (inside storm main phase); storm-only controls at the same storm phase (no flare);
   flare-only controls (same class within ~0.1 dex, Kp <= 3 for +/-24 h, within 4 years).
   Interaction I = D_overlap - median(D_storm-only) - median(D_flare-only).  I > 0 means super-additive ('worse').
Metric 2, STORM IMPACT S: mean over onset..onset+12 h of the dayside (SZA < 80 deg) mean |A| (TECU) and |A|/baseline (%),
   per magnetic-latitude band, for every G3+ storm 1998-2026; compared by group with a Kp regression.
Metric 3, STORM-THEN-FLARE: flare jump D for M5+ flares 0-72 h after a G3+ storm vs matched flare-only controls."""
import json, numpy as np, pandas as pd, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent)); import ionex as X
B = Path(__file__).resolve().parents[1]; T = B / 'tables'
rng = np.random.default_rng(42)
bl = pd.read_csv(T / 'uqrg_baseline_days.csv'); BL = {pd.Timestamp(r.day): [pd.Timestamp(x) for x in r.baseline_days.split(';')] for r in bl.itertuples()}
_bc = {}
def baseline(day):
    day = pd.Timestamp(day).floor('D')
    if day in _bc: return _bc[day]
    arr = [X.load_day(d) for d in BL.get(day, [])]; arr = [a for a in arr if a is not None]
    _bc[day] = np.nanmedian(np.array(arr), axis=0) if len(arr) >= 2 else None; return _bc[day]
def anomaly(t0, t1):
    T_, M = X.series(t0, t1)
    if M is None: return [], None, None
    base = []
    for t in T_:
        b = baseline(t.floor('D')); base.append(np.full(M[0].shape, np.nan) if b is None else b[int((t - t.floor('D')).total_seconds() // 900)])
    base = np.array(base); return T_, M - base, base
def wmean(field, mask):
    m = mask & np.isfinite(field); return np.nan if m.sum() < 10 else float((field * X.W)[m].sum() / X.W[m].sum())
def flare_jump(t, sza_max=60):
    t = pd.Timestamp(t); T_, A, _ = anomaly(t - pd.Timedelta(minutes=50), t + pd.Timedelta(minutes=35))
    if A is None: return {}
    T_ = np.array(T_); pre = A[(T_ >= t - pd.Timedelta(minutes=45)) & (T_ <= t - pd.Timedelta(minutes=15))]; post = A[(T_ > t) & (T_ <= t + pd.Timedelta(minutes=30))]
    if len(pre) == 0 or len(post) == 0: return {}
    d = np.nanmean(post, 0) - np.nanmean(pre, 0); day = X.sza_grid(t) < sza_max
    out = {'all': wmean(d, day)}
    for b, (lo, hi) in X.BANDS.items(): out[b] = wmean(d, day & (np.abs(X.MAG) >= lo) & (np.abs(X.MAG) < hi))
    return out
def storm_impact(onset, hours=12):
    T_, A, base = anomaly(pd.Timestamp(onset), pd.Timestamp(onset) + pd.Timedelta(hours=hours))
    if A is None or len(T_) < hours * 3: return {}
    out = {}
    for b, (lo, hi) in [('all', (0, 91))] + list(X.BANDS.items()):
        ab, rel = [], []
        for k, t in enumerate(T_):
            m = (X.sza_grid(t) < 80) & (np.abs(X.MAG) >= lo) & (np.abs(X.MAG) < hi)
            ab.append(wmean(np.abs(A[k]), m)); rel.append(wmean(100 * np.abs(A[k]) / np.maximum(base[k], 1), m))
        out[b] = np.nanmean(ab); out[b + ' %'] = np.nanmean(rel)
    return out
cases = pd.read_csv(T / 'overlap_cases.csv', parse_dates=['onset', 'flare_peak'])
groups = pd.read_csv(T / 'overlap_storm_groups.csv', parse_dates=['onset', 'end']); onset_of = dict(zip(groups.storm_id, groups.onset))
rows = []
for _, c in cases.iterrows():
    r = dict(storm_id=c.storm_id, flare=f"{c.flare_cls} {c.flare_peak:%Y-%m-%d %H:%M}", kp_max=c.kp_max, dst_min=c.dst_min, phase_h=round(c.phase_h, 2))
    ov = flare_jump(c.flare_peak); sc = [flare_jump(onset_of[s] + pd.Timedelta(hours=c.phase_h)) for s in c.storm_controls.split(';')]
    fc = [flare_jump(pd.Timestamp(x)) for x in c.flare_controls.split(';')]
    for b in ['all'] + list(X.BANDS):
        r[f'D_overlap|{b}'] = ov.get(b, np.nan)
        r[f'D_stormonly|{b}'] = json.dumps([round(x.get(b, np.nan), 3) for x in sc]); r[f'D_flareonly|{b}'] = json.dumps([round(x.get(b, np.nan), 3) for x in fc])
    rows.append(r); print(c.storm_id, {k: round(v, 2) for k, v in ov.items()}, flush=True)
R = pd.DataFrame(rows); R.to_csv(T / 'overlap_flare_jump_metrics.csv', index=False)
def interaction(R, b, nboot=5000):
    ov = R[f'D_overlap|{b}'].values; so = [np.array(json.loads(x), float) for x in R[f'D_stormonly|{b}']]; fo = [np.array(json.loads(x), float) for x in R[f'D_flareonly|{b}']]
    ok = [i for i in range(len(ov)) if np.isfinite(ov[i]) and np.isfinite(so[i]).any() and np.isfinite(fo[i]).any()]
    I = np.array([ov[i] - np.nanmedian(so[i]) - np.nanmedian(fo[i]) for i in ok])
    bs = []
    for _ in range(nboot):
        pick = rng.choice(ok, len(ok)); vals = []
        for i in pick:
            s = so[i][np.isfinite(so[i])]; f = fo[i][np.isfinite(fo[i])]
            vals.append(ov[i] - np.median(rng.choice(s, len(s))) - np.median(rng.choice(f, len(f))))
        bs.append(np.mean(vals))
    sd_case = np.std(I, ddof=1) if len(I) > 1 else np.nan
    return dict(band=b, n_cases=len(ok), mean_D_overlap=round(np.mean(ov[ok]), 3), mean_D_stormonly=round(np.mean([np.nanmedian(so[i]) for i in ok]), 3),
                mean_D_flareonly=round(np.mean([np.nanmedian(fo[i]) for i in ok]), 3), mean_interaction=round(I.mean(), 3),
                ci95=[round(np.percentile(bs, 2.5), 3), round(np.percentile(bs, 97.5), 3)], sd_between_cases=round(sd_case, 3),
                cases_positive=int((I > 0).sum()),
                n_needed_detect_1TECU_80pct=int(np.ceil(((1.96 + 0.84) * sd_case / 1.0) ** 2)) if np.isfinite(sd_case) else None,
                n_needed_detect_50pct_of_flare_effect=int(np.ceil(((1.96 + 0.84) * sd_case / max(0.5 * abs(np.mean([np.nanmedian(fo[i]) for i in ok])), 1e-3)) ** 2)) if np.isfinite(sd_case) else None)
INT = pd.DataFrame([interaction(R, b) for b in ['all'] + list(X.BANDS)]); INT.to_csv(T / 'overlap_interaction_summary.csv', index=False); print(INT.to_string())
# ---- Metric 3: storm then flare
A = pd.read_csv(T / 'storm_then_flare_cases.csv', parse_dates=['flare_peak']); ar = []
for _, a in A.iterrows():
    d = flare_jump(a.flare_peak); fc = [flare_jump(pd.Timestamp(x)).get('all', np.nan) for x in a.flare_controls.split(';')]
    ar.append(dict(storm_id=a.storm_id, flare=f"{a.flare_cls} {a.flare_peak:%Y-%m-%d %H:%M}", hours_after_end=round(a.hours_after_end, 1), D_after=d.get('all', np.nan),
                   D_flareonly_median=np.nanmedian(fc) if np.isfinite(fc).any() else np.nan))
AR = pd.DataFrame(ar); AR['diff'] = AR.D_after - AR.D_flareonly_median; AR.to_csv(T / 'storm_then_flare_metrics.csv', index=False)
dd = AR['diff'].dropna().values; bs = [rng.choice(dd, len(dd)).mean() for _ in range(5000)]
stf = dict(n=len(dd), mean_D_after_storm=round(AR.D_after.mean(), 3), mean_D_flareonly=round(AR.D_flareonly_median.mean(), 3), mean_diff=round(dd.mean(), 3),
           ci95=[round(np.percentile(bs, 2.5), 3), round(np.percentile(bs, 97.5), 3)])
print('storm-then-flare', stf)
# ---- Metric 2: storm impact for every G3+ storm
sr = []
for _, g in groups.iterrows():
    s = storm_impact(g.onset); s.update(storm_id=g.storm_id, group=g.group, kp_max=g.kp_max, dst_min=g.dst_min, onset=g.onset); sr.append(s)
S = pd.DataFrame(sr); S.to_csv(T / 'storm_impact_by_group.csv', index=False)
reg = {}
for col in ['all', 'all %', 'mid (20-45°)', 'sub-auroral (45-60°)', 'mid (20-45°) %', 'sub-auroral (45-60°) %']:
    d = S.dropna(subset=[col]); Xm = np.column_stack([np.ones(len(d)), d.kp_max, (d.group == 'overlap').astype(float), (d.group == 'flare_before_only').astype(float)])
    y = d[col].values; b = np.linalg.lstsq(Xm, y, rcond=None)[0]; bb = []
    for _ in range(3000):
        ii = rng.integers(0, len(d), len(d)); bb.append(np.linalg.lstsq(Xm[ii], y[ii], rcond=None)[0])
    bb = np.array(bb); reg[col] = dict(n=len(d), n_overlap=int((d.group == 'overlap').sum()), n_before=int((d.group == 'flare_before_only').sum()), n_free=int((d.group == 'flare_free').sum()),
        kp_slope=round(b[1], 3), overlap_effect=round(b[2], 3), overlap_ci95=[round(np.percentile(bb[:, 2], 2.5), 3), round(np.percentile(bb[:, 2], 97.5), 3)],
        flare_before_effect=round(b[3], 3), flare_before_ci95=[round(np.percentile(bb[:, 3], 2.5), 3), round(np.percentile(bb[:, 3], 97.5), 3)])
json.dump(dict(storm_then_flare=stf, storm_impact_regression=reg), open(T / 'overlap_other_tests.json', 'w'), indent=1, default=str)
print(json.dumps(reg, indent=1))
