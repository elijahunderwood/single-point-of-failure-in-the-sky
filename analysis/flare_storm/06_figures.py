#!/usr/bin/env python3
"""Poster-ready figures (PNG, 200 dpi, large fonts). Run after 01-05."""
import sqlite3, pickle, numpy as np, pandas as pd, matplotlib
matplotlib.use('Agg'); import matplotlib.pyplot as plt, matplotlib.dates as mdates
from pathlib import Path
B = Path(__file__).resolve().parents[1]; D = B / 'data'; T = B / 'tables'; F = B / 'figures'
plt.rcParams.update({'font.size': 14, 'axes.titlesize': 16, 'axes.labelsize': 14, 'legend.fontsize': 12, 'figure.dpi': 100})
ro = lambda f: sqlite3.connect(f"file:{D / f}?mode=ro", uri=True)
NOTE = 'Data: own Belfast receiver & dish logger; NOAA GOES; GFZ Kp; Kyoto/OMNI Dst; IGS/EUREF stations. Times UTC.'
# ---------- Fig 1: own double-whammy, 7-12 Oct 2026
a, b = '2026-10-07', '2026-10-12T12'
xr = pd.read_sql(f"select ts_utc,flux_long from xray_flux where ts_utc>='{a}' and ts_utc<'{b}'", ro('flare.db')); xr['t'] = pd.to_datetime(xr.ts_utc)
fl = pd.read_sql(f"select class,peak_utc,peak_flux from flares where peak_utc>='{a}' and peak_utc<'{b}' and peak_flux>=1e-5", ro('flare.db')); fl['t'] = pd.to_datetime(fl.peak_utc)
kp = pd.read_csv(T / 'kp_gfz_1996_2026.csv', parse_dates=['t']); kp = kp[(kp.t >= a) & (kp.t < b)]; kp['t'] = kp.t.dt.tz_localize('UTC')
dst = pd.read_sql(f"select ts_utc,dst from dst_index where ts_utc>='{a}' and ts_utc<'{b}'", ro('spaceweather.db')); dst['t'] = pd.to_datetime(dst.ts_utc)
rn = pd.read_sql(f"select window_start,roti_med,roti_2nd from roti_network where window_start>='{a}' and window_start<'{b}'", ro('roti.db')); rn['t'] = pd.to_datetime(rn.window_start)
gn = pd.read_sql(f"select window_start,station,frac_gt05 from roti_network where window_start>='{a}' and window_start<'{b}' and station in ('MORP','TRO1')", ro('global_roti.db')); gn['t'] = pd.to_datetime(gn.window_start, utc=True)
sl = pd.read_csv(T / 'starlink_hourly_with_drivers.csv', parse_dates=['t']); sl = sl[(sl.t >= pd.Timestamp(a, tz='UTC')) & (sl.t < pd.Timestamp(b, tz='UTC'))]
fig, ax = plt.subplots(5, 1, figsize=(16, 17), sharex=True)
ax[0].semilogy(xr.t, xr.flux_long, color='darkorange'); ax[0].axhline(1e-5, ls=':', c='grey'); ax[0].axhline(1e-4, ls=':', c='grey')
ax[0].text(xr.t.iloc[0], 1.15e-5, 'M class', color='grey'); ax[0].set_ylim(1e-7, 2e-4)
for _, r in fl[fl.peak_flux >= 5e-5].iterrows(): ax[0].annotate(f"{r['class']} flare\n{r.t:%d %b %H:%M}", (r.t, r.peak_flux), xytext=(10, 5), textcoords='offset points', fontsize=12, fontweight='bold')
ax[0].set_ylabel('X-ray flux\n(W m$^{-2}$)'); ax[0].set_title('Own "double whammy": two M6+ flares and a G3 storm in 3 days (7-12 Oct 2026)')
cols = ['tab:green' if v < 5 else 'gold' if v < 6 else 'orange' if v < 6.66 else 'red' for v in kp.kp]
ax[1].bar(kp.t + pd.Timedelta(hours=1.5), kp.kp, width=0.12, color=cols); ax[1].axhline(6.667, ls='--', c='red'); ax[1].text(kp.t.iloc[0], 6.9, 'G3 (Kp 7-)', color='red')
ax[1].set_ylabel('Kp (GFZ)'); ax[1].set_ylim(0, 9)
ax[2].plot(dst.t, dst.dst, c='purple'); ax[2].axhline(-50, ls=':', c='grey'); ax[2].set_ylabel('Dst (nT)\nreal-time')
ax[3].plot(rn.t, rn.roti_med, lw=1, label='Belfast: median over satellites'); ax[3].plot(rn.t, rn.roti_2nd, lw=1, alpha=.6, label='Belfast: 2nd-worst satellite')
ax[3].axhline(0.5, ls='--', c='k'); ax[3].set_ylabel('ROTI\n(TECU/min)'); ax[3].legend(loc='upper left'); ax[3].set_ylim(0, 2.5)
for s, c in [('MORP', 'tab:blue'), ('TRO1', 'tab:red')]:
    x = gn[gn.station == s].set_index('t').frac_gt05.rolling('1h').mean() * 100; ax[3].twinx() if False else None
ax3b = ax[3].twinx()
for s, c, lab in [('MORP', 'navy', 'Morpeth (England)'), ('TRO1', 'crimson', 'Tromsø (Arctic)')]:
    x = gn[gn.station == s].set_index('t').frac_gt05.rolling('1h').mean() * 100; ax3b.plot(x.index, x, c=c, lw=2, label=f'{lab}: % sats ROTI>0.5')
ax3b.set_ylabel('% satellites\nROTI > 0.5'); ax3b.legend(loc='upper right'); ax3b.set_ylim(0, 100)
ax[4].plot(sl.t, sl.lat_mean, 'o-', ms=3, c='teal'); ax[4].set_ylabel('LEO broadband\nlatency (ms, hourly)')
ax4b = ax[4].twinx(); ax4b.bar(sl.t, sl.precipitation_mm, width=0.04, color='steelblue', alpha=.4); ax4b.set_ylabel('rain (mm/h)')
for x in ax:
    for _, r in fl[fl.peak_flux >= 5e-5].iterrows(): x.axvline(r.t, c='darkorange', alpha=.5, lw=2)
    x.axvspan(pd.Timestamp('2026-10-10T15', tz='UTC'), pd.Timestamp('2026-10-11T00', tz='UTC'), color='red', alpha=.08)
ax[-1].xaxis.set_major_formatter(mdates.DateFormatter('%d %b\n%H:%M')); fig.text(0.01, 0.005, NOTE, fontsize=10)
plt.tight_layout(); plt.savefig(F / 'fig01_own_double_whammy_oct2026.png', dpi=200); plt.close()
# ---------- Fig 2: Belfast flare superposed epoch
g = pd.read_csv(D / 'win/gnss10s.csv', dtype={'flare_id': str}); s = pd.read_csv(D / 'win/starlink10s.csv', dtype={'flare_id': str})
ev = pd.read_csv(T / 'belfast_flare_event_metrics.csv', dtype={'flare_id': str}).drop_duplicates('flare_id')[['flare_id', 'peak_utc', 'peak_flux', 'group']]
OFF = {'flare': 0, 'ctrl_day': 86400, 'ctrl_sid': 86164}; pk = dict(zip(ev.flare_id, pd.to_datetime(ev.peak_utc)))
for df in (g, s):
    df['t'] = pd.to_datetime(df['bin'] + '0', utc=True)
    df['tm'] = [((t - (pk[f] - pd.Timedelta(seconds=OFF[w]))).total_seconds() / 60) for t, f, w in zip(df.t, df.flare_id, df.win)]; df['m'] = df.tm.round(0)
sun = set(ev[(ev.group == 'sunlit') & (ev.peak_flux >= 1e-5)].flare_id)
curves = pickle.load(open(D / 'belfast_dtec_curves.pkl', 'rb'))
fig, ax = plt.subplots(1, 3, figsize=(20, 6.5))
for w, c, lab in [('flare', 'darkorange', 'flare days'), ('ctrl_sid', 'grey', 'control: sidereal day before')]:
    cs = [curves[(f, w)] for f in sun if (f, w) in curves]
    if cs:
        M = pd.concat([x.groupby(x.index.round(0)).mean() for x in cs], axis=1); ax[0].plot(M.index, M.median(axis=1), c=c, lw=2.5, label=f'{lab} (n={len(cs)})')
        ax[0].fill_between(M.index, M.quantile(.25, axis=1), M.quantile(.75, axis=1), color=c, alpha=.2)
    x = g[(g.flare_id.isin(sun)) & (g.win == w) & (g.elev >= 30)].groupby(['flare_id', 'm']).cno_l1.mean().unstack(0)
    x = x - x.loc[-60:-10].mean(); ax[1].plot(x.index, x.mean(axis=1), c=c, lw=2.5, label=lab)
    y = s[(s.flare_id.isin(sun)) & (s.win == w)].groupby(['flare_id', 'm']).lat.mean().unstack(0); y = y - y.loc[-60:-10].mean()
    ax[2].plot(y.index, y.rolling(5, center=True).mean().mean(axis=1), c=c, lw=2.5, label=lab)
for a_, yl, tt in zip(ax, ['vertical dTEC (TECU)', 'C/N0 change, L1 (dB-Hz)', 'latency change (ms)'],
                      ['GPS TEC (network median)', 'GPS signal strength (elev. ≥30°)', 'LEO broadband latency']):
    a_.axvline(0, c='darkorange', ls='--'); a_.axvspan(-5, 20, color='orange', alpha=.08); a_.set_xlabel('minutes from X-ray peak'); a_.set_ylabel(yl); a_.set_title(tt); a_.legend(fontsize=11)
fig.suptitle(f'Belfast: superposed epoch of up to {len(sun)} sunlit M-class flares (TEC panel: only flares with clean satellite arcs)  - no effect clearly above day-to-day noise', fontsize=16)
plt.tight_layout(); plt.savefig(F / 'fig02_belfast_flare_superposed_epoch.png', dpi=200); plt.close()
# ---------- Fig 3: global flare response
fr = pd.read_csv(T / 'global_flare_station_responses.csv'); q = fr[(fr.kind == 'flare') & fr.quality]
fig, ax = plt.subplots(1, 2, figsize=(18, 6.5))
S = pd.read_csv(T / 'global_flare_detection_summary.csv')
for i, grp in enumerate(['class', 'sza']):
    x = S[S.grouping == grp]; ci = x.ci95.apply(eval)
    ax[i].bar(x.bin, x.pct_credible, yerr=[x.pct_credible - [c[0] for c in ci], [c[1] for c in ci] - x.pct_credible], capsize=6, color='darkorange')
    for j, (p, n) in enumerate(zip(x.pct_credible, x.n_station_flares)): ax[i].text(j, 2, f'n={n}', ha='center', color='white', fontweight='bold')
    ax[i].set_ylabel('% station-flares with a credible TEC jump'); ax[i].set_xlabel('flare class' if grp == 'class' else 'solar zenith angle at station (deg)')
ax[0].set_title('Bigger flares are detected more often'); ax[1].set_title('Sun higher in the sky -> more detections')
fig.suptitle('Worldwide stations, 24 M-class flares (Jul-Oct 2026); controls: 0 of 9 false detections', fontsize=16)
plt.tight_layout(); plt.savefig(F / 'fig03_global_flare_detection.png', dpi=200); plt.close()
# ---------- Fig 4: storm heatmap
H = pd.read_csv(T / 'global_storm_days_pct_roti_gt05.csv', index_col=0); drv = pd.read_csv(T / 'global_storm_days_drivers.csv')
days = [c for c in H.columns if c[:2] == '20']; M = H[days + ['quiet_pct_median']]
fig, ax = plt.subplots(figsize=(19, 9)); im = ax.imshow(M.values, cmap='magma_r', vmin=0, vmax=60, aspect='auto')
for i in range(M.shape[0]):
    for j in range(M.shape[1]):
        v = M.values[i, j]; ax.text(j, i, '' if np.isnan(v) else f'{v:.0f}', ha='center', va='center', fontsize=10, color='white' if v > 35 else 'black')
lab = [f"{d[2:]}\nKp {drv.set_index('day').kp_max.get(d, np.nan):.1f}" for d in days] + ['quiet\nmedian']
ax.set_xticks(range(len(lab))); ax.set_xticklabels(lab, fontsize=10); ax.set_yticks(range(len(M))); ax.set_yticklabels([f"{s} ({H.loc[s, 'geomag_lat']:.0f}°)" for s in M.index])
ax.set_title('Storm days: % of satellites with ROTI > 0.5 TECU/min (stations sorted by magnetic latitude)')
plt.colorbar(im, ax=ax, label='% satellite windows'); ax.axhline(5.5, c='cyan', lw=2); ax.axhline(6.5, c='cyan', lw=2)
ax.set_ylabel('station (magnetic latitude); MORP ≈ Belfast')
plt.tight_layout(); plt.savefig(F / 'fig04_storm_heatmap_by_latitude.png', dpi=200); plt.close()
# ---------- Fig 5: double whammy vs chance
A = pd.read_csv(T / 'storm_flare_association_goesr.csv'); A = A[(A.window_days == 3)]
fig, ax = plt.subplots(1, 2, figsize=(19, 7))
for i, fname in enumerate(['M5+', 'X']):
    x = A[(A.flare == fname) & A.timing.isin(['before', 'during', 'after'])]; storms = ['G3+', 'G4+', 'G5']; tims = ['before', 'during', 'after']
    wdt = 0.13
    for k, st in enumerate(storms):
        for m, tm in enumerate(tims):
            r = x[(x.storm == st) & (x.timing == tm)].iloc[0]; pos = k + (m - 1) * 0.28; ci = eval(r.chance_frac_95.replace('np.float64(', '').replace(')', ''))
            ax[i].bar(pos - wdt / 2, 100 * r.observed_frac, wdt, color=['tab:red', 'tab:purple', 'tab:blue'][m], label=f'observed: flare {tm} storm' if k == 0 else None)
            ax[i].bar(pos + wdt / 2, 100 * r.chance_frac_mean, wdt, color='lightgrey', edgecolor='k', yerr=[[100 * (r.chance_frac_mean - ci[0])], [100 * (ci[1] - r.chance_frac_mean)]], capsize=3, label='chance (shuffled ±6 months)' if (k == 0 and m == 0) else None)
            ax[i].text(pos - wdt / 2, 100 * r.observed_frac + 1, f'{r.observed_n}', ha='center', fontsize=10)
    n = A[(A.flare == fname) & (A.timing == 'before')].set_index('storm').n_storms
    ax[i].set_xticks(range(3)); ax[i].set_xticklabels([f'{s} storms\n(n={n[s]})' for s in storms]); ax[i].set_ylabel('% of storms'); ax[i].set_ylim(0, 105)
    ax[i].set_title(f'{fname} flare within 3 days before / during / 3 days after'); ax[i].legend(fontsize=10, loc='upper left')
fig.suptitle('1996-2026: how often strong storms come with strong flares, compared with chance', fontsize=17)
fig.text(0.01, 0.01, 'Flares: NOAA NCEI GOES XRS event lists (GOES-R scale). Storms: GFZ Kp >= 7- (G3), 8- (G4), 9- (G5). Number above bar = storms.', fontsize=10)
plt.tight_layout(); plt.savefig(F / 'fig05_double_whammy_vs_chance.png', dpi=200); plt.close()
# ---------- Fig 6: per-year timeline
Y = pd.read_csv(T / 'per_year_counts_goesr.csv')
fig, ax = plt.subplots(figsize=(18, 7)); w = 0.27
ax.bar(Y.year - w, Y.days_M5plus_flare, w, color='darkorange', label='days with an M5+ flare')
ax.bar(Y.year, Y.days_G3plus, w, color='tab:red', label='days with a G3+ storm')
ax.bar(Y.year + w, Y.days_G3_with_M5_same_or_prev3d, w, color='black', label='G3+ storm days with an M5+ flare that day or in the 3 days before')
ax.set_ylabel('days per year'); ax.set_xlabel('year'); ax.legend(); ax.set_title('Flares, storms and "double whammy" days per year, 1996-2026 (two solar maxima: ~2001 and ~2024)')
ax.text(2016.3, 70, 'Jan-Feb 2017: no flare list\n2026: to 24 Oct only', fontsize=11)
plt.tight_layout(); plt.savefig(F / 'fig06_per_year_counts.png', dpi=200); plt.close()
# ---------- Fig 7: X flares -> storm
X = pd.read_csv(T / 'flare_followed_by_storm_goesr.csv')
fig, ax = plt.subplots(figsize=(12, 6.5)); lab = []
for i, (_, r) in enumerate(X[X.within_days == 3].iterrows()):
    ci = eval(r.chance_95.replace('np.float64(', '').replace(')', ''))
    ax.bar(i - .18, 100 * r.observed_frac, .36, color='darkorange', label='observed' if i == 0 else None)
    ax.bar(i + .18, 100 * r.chance_frac_mean, .36, color='lightgrey', edgecolor='k', yerr=[[100 * (r.chance_frac_mean - ci[0])], [100 * (ci[1] - r.chance_frac_mean)]], capsize=4, label='chance' if i == 0 else None)
    ax.text(i - .18, 100 * r.observed_frac + .7, f'{r.observed_n}/{r.n_flares}', ha='center', fontsize=11); lab.append(f'{r.flare} flare ->\n{r.storm} storm')
ax.set_xticks(range(len(lab))); ax.set_xticklabels(lab); ax.set_ylabel('% of flares followed by a storm within 3 days'); ax.legend()
ax.set_title('Most big flares are NOT followed by a big storm (1996-2026)'); plt.tight_layout(); plt.savefig(F / 'fig07_flares_followed_by_storm.png', dpi=200); plt.close()
# ---------- Fig 8: Belfast storm sensitivity
bel = pd.read_csv(T / 'belfast_roti_vs_kp.csv')
fig, ax = plt.subplots(1, 2, figsize=(18, 6.5)); ci = bel.ci95.apply(eval)
ax[0].bar(bel.kp_bin.astype(str), bel.pct_roti_gt05, yerr=[bel.pct_roti_gt05 - [c[0] for c in ci], [c[1] for c in ci] - bel.pct_roti_gt05], capsize=5, color='tab:blue')
for j, (n, nd) in enumerate(zip(bel.n_3h_blocks, bel.n_days)): ax[0].text(j, .05, f'{n} blocks\n{nd} days', ha='center', fontsize=10, color='white')
ax[0].set_ylabel('% satellite windows ROTI > 0.5'); ax[0].set_xlabel('Kp'); ax[0].set_title('Belfast receiver, Jul-Oct 2026 (elev. ≥30°)'); ax[0].tick_params(axis='x', labelsize=11)
import json; J = json.load(open(T / 'starlink_storm_rain_regression.json'))
names = ['storm (Kp≥5)\nlatency', 'rain\nlatency']; vals = [J['lat_mean']['storm_effect'], J['lat_mean']['rain_effect']]; cis = [J['lat_mean']['storm_ci95'], J['lat_mean']['rain_ci95']]
ax[1].errorbar(range(2), vals, yerr=[[v - c[0] for v, c in zip(vals, cis)], [c[1] - v for v, c in zip(vals, cis)]], fmt='o', ms=12, capsize=8, lw=3, c='teal')
ax[1].axhline(0, c='k'); ax[1].set_xticks(range(2)); ax[1].set_xticklabels(names); ax[1].set_ylabel('effect on hourly latency (ms), 95% CI')
ax[1].set_title(f"LEO broadband: {J['n_hours']} h, {J['n_storm_hours_kp_ge5']} storm hours"); ax[1].set_xlim(-.5, 1.5)
plt.tight_layout(); plt.savefig(F / 'fig08_belfast_storm_sensitivity.png', dpi=200); plt.close()
print('figures done')
