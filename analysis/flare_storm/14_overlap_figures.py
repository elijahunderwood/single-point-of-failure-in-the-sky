#!/usr/bin/env python3
"""Figures 9-11 and the combined cases/matches/metrics CSV for the overlap ('does flare + storm together do more?') test. Run after 10, 12, 13."""
import ast, json, numpy as np, pandas as pd, matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
from pathlib import Path
B = Path(__file__).resolve().parents[1]; T = B / 'tables'; F = B / 'figures'
plt.rcParams.update({'font.size': 14, 'axes.titlesize': 16, 'axes.labelsize': 14, 'legend.fontsize': 12})
rng = np.random.default_rng(2027)
def arr(s):
    return np.array(ast.literal_eval(str(s).replace('NaN', 'None')), dtype=float)
C = pd.read_csv(T / 'overlap_cases.csv'); M = pd.read_csv(T / 'overlap_flare_jump_metrics.csv')
D = C.merge(M[['storm_id'] + [c for c in M.columns if c.startswith('D_')]], on='storm_id')
D['D_stormonly_median_all'] = D['D_stormonly|all'].map(lambda s: np.nanmedian(arr(s)))
D['D_flareonly_median_all'] = D['D_flareonly|all'].map(lambda s: np.nanmedian(arr(s)))
D['expected_if_additive_all'] = D.D_stormonly_median_all + D.D_flareonly_median_all
D['interaction_all_TECU'] = D['D_overlap|all'] - D.expected_if_additive_all
# per-case uncertainty: bootstrap over that case's controls
lo, hi = [], []
for _, r in D.iterrows():
    so, fo = arr(r['D_stormonly|all']), arr(r['D_flareonly|all']); so, fo = so[np.isfinite(so)], fo[np.isfinite(fo)]
    b = [r['D_overlap|all'] - np.median(rng.choice(so, len(so))) - np.median(rng.choice(fo, len(fo))) for _ in range(4000)]
    lo.append(np.percentile(b, 2.5)); hi.append(np.percentile(b, 97.5))
D['interaction_ci95_lo'], D['interaction_ci95_hi'] = np.round(lo, 2), np.round(hi, 2)
S = pd.read_csv(T / 'storm_impact_by_group.csv'); D = D.merge(S[['storm_id', 'all', 'all %']].rename(columns={'all': 'storm12h_dayside_absanom_TECU', 'all %': 'storm12h_dayside_absanom_pct'}), on='storm_id', how='left')
cols = ['storm_id', 'onset', 'kp_max', 'dst_min', 'flare_cls', 'flare_peak', 'phase_h', 'storm_controls', 'storm_control_kp', 'storm_control_dst', 'flare_controls', 'flare_control_cls',
        'D_overlap|all', 'D_stormonly|all', 'D_flareonly|all', 'D_stormonly_median_all', 'D_flareonly_median_all', 'expected_if_additive_all', 'interaction_all_TECU', 'interaction_ci95_lo', 'interaction_ci95_hi',
        'storm12h_dayside_absanom_TECU', 'storm12h_dayside_absanom_pct'] + [c for c in D.columns if c.startswith('D_') and '|all' not in c]
D[cols].round(3).to_csv(T / 'overlap_cases_matches_metrics.csv', index=False)
I = D.interaction_all_TECU.values
# headline CI = script 12 bootstrap (resamples cases AND their controls)
INT = pd.read_csv(T / 'overlap_interaction_summary.csv'); ci = np.array([float(v) for v in __import__('re').findall(r'-?\d+\.\d+', INT.loc[INT.band == 'all', 'ci95'].iloc[0])])
x = I[D.storm_id != 'S2003102906']; bs2 = [rng.choice(x, len(x)).mean() for _ in range(10000)]; ci2 = np.percentile(bs2, [2.5, 97.5])
summ = dict(n=len(I), mean=round(float(I.mean()), 2), median=round(np.median(I), 2), ci95=list(np.round(ci, 2)), n_positive=int((I > 0).sum()),
            excl_2003_cases_only_bootstrap=dict(n=len(x), mean=round(x.mean(), 2), median=round(np.median(x), 2), ci95=list(np.round(ci2, 2))))
json.dump(summ, open(T / 'overlap_interaction_headline.json', 'w'), indent=1); print(summ)

# Fig 9: per-case interaction
o = D.sort_values('onset').reset_index(drop=True); lab = [f"{r.onset[:10]}\n{r.flare_cls}" for r in o.itertuples()]
fig, ax = plt.subplots(1, 2, figsize=(16, 7.5), gridspec_kw={'width_ratios': [2.3, 1]})
y = np.arange(len(o)); a = ax[0]
a.barh(y - 0.2, o['D_overlap|all'], 0.38, color='#c0392b', label='Measured: flare during storm')
a.barh(y + 0.2, o.expected_if_additive_all, 0.38, color='#95a5a6', label='Expected if effects just add\n(storm-only + flare-only controls)')
a.set_yticks(y); a.set_yticklabels(lab, fontsize=10); a.invert_yaxis(); a.axvline(0, color='k', lw=0.8)
a.set_xlabel('Dayside TEC jump in 30 min after flare (TECU)'); a.set_title('13 storms with an M5+ flare in the main phase'); a.legend(loc='lower right', fontsize=11)
a = ax[1]; a.errorbar(o.interaction_all_TECU, y, xerr=[o.interaction_all_TECU - o.interaction_ci95_lo, o.interaction_ci95_hi - o.interaction_all_TECU], fmt='o', color='k', capsize=3)
a.axvline(0, color='k', lw=0.8); a.axvspan(ci[0], ci[1], color='#3498db', alpha=0.25, label=f'Mean {I.mean():.1f} TECU,\n95% CI {ci[0]:.1f} to {ci[1]:.1f}')
a.set_yticks(y); a.set_yticklabels([]); a.invert_yaxis(); a.set_xlabel('Extra (measured − expected), TECU'); a.set_title('Extra effect per case'); a.legend(loc='lower right', fontsize=11)
fig.suptitle('Does a flare during a storm do MORE than the two separately? Verdict: cannot tell (n = 13)', fontsize=17)
plt.tight_layout(); plt.savefig(F / 'fig09_overlap_interaction_per_case.png', dpi=200); plt.close()

# Fig 10: storm impact vs Kp by group
fig, ax = plt.subplots(figsize=(11, 7.5)); sty = {'flare_free': ('#2980b9', 'o', 'No M5+ flare within 3 days'), 'flare_before_only': ('#f39c12', 's', 'M5+ flare in the 3 days before only'), 'overlap': ('#c0392b', '*', 'M5+ flare during the main phase')}
reg = json.load(open(T / 'overlap_other_tests.json'))['storm_impact_regression']['all %']
for g, (c, m, l) in sty.items():
    d = S[S.group == g]; ax.scatter(d.kp_max + rng.uniform(-0.08, 0.08, len(d)), d['all %'], c=c, marker=m, s=160 if m == '*' else 55, alpha=0.85, label=f'{l} (n={len(d)})', edgecolor='k', lw=0.4)
ax.set_xlabel('Storm maximum Kp'); ax.set_ylabel('Dayside |TEC change from quiet| over first 12 h (%)')
ax.set_title('Storm-wide ionospheric disturbance, G3+ storms 1998-2026')
ax.text(0.02, 0.97, f"After allowing for Kp: overlap storms {reg['overlap_effect']:+.1f} points (95% CI {reg['overlap_ci95'][0]:.1f} to {reg['overlap_ci95'][1]:+.1f})\n"
        f"flare-before storms {reg['flare_before_effect']:+.1f} points (95% CI {reg['flare_before_ci95'][0]:.1f} to {reg['flare_before_ci95'][1]:+.1f})  ->  cannot tell",
        transform=ax.transAxes, va='top', fontsize=12, bbox=dict(fc='w', ec='0.7'))
ax.legend(loc='lower right'); plt.tight_layout(); plt.savefig(F / 'fig10_storm_impact_by_group_vs_kp.png', dpi=200); plt.close()

# Fig 11: storm then flare
Q = pd.read_csv(T / 'storm_then_flare_metrics.csv'); stf = json.load(open(T / 'overlap_other_tests.json'))['storm_then_flare']
fig, ax = plt.subplots(figsize=(9, 8)); ax.scatter(Q.D_flareonly_median, Q.D_after, s=60, c=Q.hours_after_end, cmap='viridis', edgecolor='k', lw=0.4)
lim = [min(Q.D_flareonly_median.min(), Q.D_after.min()) - 0.3, max(Q.D_flareonly_median.max(), Q.D_after.max()) + 0.3]
ax.plot(lim, lim, 'k--', lw=1, label='Same size either way'); ax.set_xlim(lim); ax.set_ylim(lim)
cb = plt.colorbar(ax.collections[0]); cb.set_label('Hours after the storm ended')
ax.set_xlabel('TEC jump of similar flares on quiet days (TECU)'); ax.set_ylabel('TEC jump of flare 0-72 h after a storm (TECU)')
ax.set_title(f"Storm THEN flare (n={stf['n']}): difference {stf['mean_diff']:+.2f} TECU\n95% CI {stf['ci95'][0]:.2f} to {stf['ci95'][1]:+.2f}  ->  no different", fontsize=15)
ax.legend(loc='upper left'); plt.tight_layout(); plt.savefig(F / 'fig11_storm_then_flare.png', dpi=200); plt.close()
