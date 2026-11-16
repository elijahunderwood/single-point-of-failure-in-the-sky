#!/usr/bin/env python3
"""How often do strong flares and strong geomagnetic storms come together? (1996-2026)
Storm = run of 3-hour GFZ Kp >= 6.66 (i.e. Kp 7- = 6.667 or more, NOAA G3; thresholds set 0.01 below the thirds to avoid rounding loss) merged when gaps <= 24 h.
Strong flare = GOES 0.1-0.8 nm peak flux >= 5e-5 W/m2 (M5) or >= 1e-4 (X), on the GOES-R scale (see 01).
Chance baseline: each storm (or flare) is moved to a random time within +/-182 days of its real time
(so the baseline keeps the solar-cycle activity level) and the statistic is recomputed 5000 times."""
import json, numpy as np, pandas as pd, sys
from pathlib import Path
B = Path(__file__).resolve().parents[1]; T = B / 'tables'
rng = np.random.default_rng(20261025)
SCALE = sys.argv[1] if len(sys.argv) > 1 else 'goesr'          # 'goesr' (main) or 'reported' (sensitivity)
fl = pd.read_csv(T / 'flare_catalogue_1996_2026.csv', parse_dates=['start', 'peak', 'end'])
fl['F'] = fl.flux if SCALE == 'goesr' else fl.flux_reported
kp = pd.read_csv(T / 'kp_gfz_1996_2026.csv', parse_dates=['t']); dst = pd.read_csv(T / 'dst_omni_1996_2026.csv', parse_dates=['t'])
END = pd.Timestamp('2026-10-24')
CAT_GAP = (pd.Timestamp('2017-01-01'), pd.Timestamp('2017-02-09'))   # no flare list available for this interval
def storms(th, gap_h=24):
    s = kp[kp.kp >= th].t.sort_values().tolist(); ev = []
    for t in s:
        if ev and (t - ev[-1][1]).total_seconds() <= gap_h * 3600: ev[-1][1] = t
        else: ev.append([t, t])
    out = []
    for a, b in ev:
        e = b + pd.Timedelta(hours=3); w = kp[(kp.t >= a - pd.Timedelta(hours=12)) & (kp.t <= e + pd.Timedelta(hours=12))]
        dd = dst[(dst.t >= a - pd.Timedelta(hours=12)) & (dst.t <= e + pd.Timedelta(hours=24))]
        out.append(dict(onset=a, end=e, kp_max=w.kp.max(), dst_min=dd.dst.min() if len(dd) else np.nan))
    d = pd.DataFrame(out); return d[~((d.onset >= CAT_GAP[0] - pd.Timedelta(days=4)) & (d.onset <= CAT_GAP[1] + pd.Timedelta(days=4)))]
fp = {th: np.sort(fl[fl.F >= th].peak.values.astype('datetime64[s]').astype(np.int64)) for th in (5e-5, 1e-4)}
def any_in(times, a, b):  # vectorised: is there any flare time in [a, b)?
    i = np.searchsorted(times, a, 'left'); j = np.searchsorted(times, b, 'left'); return j > i
D = 86400
def windows(st):
    on = st.onset.values.astype('datetime64[s]').astype(np.int64); en = st.end.values.astype('datetime64[s]').astype(np.int64)
    return on, en
def stats(on, en, times, k=3):
    before = any_in(times, on - k * D, on); during = any_in(times, on, en); after = any_in(times, en, en + k * D)
    return dict(before=before, during=during, after=after, before_or_during=before | during, any=before | during | after)
res = {}; tabs = []
for sname, th in [('G3+', 6.66), ('G4+', 7.66), ('G5', 8.66)]:
    st = storms(th); on, en = windows(st)
    for fname, ft in [('M5+', 5e-5), ('X', 1e-4)]:
        times = fp[ft]
        for k in (1, 2, 3):
            obs = {kk: v.mean() for kk, v in stats(on, en, times, k).items()}
            sims = {kk: [] for kk in obs}
            for _ in range(5000):
                sh = rng.integers(-182 * D, 182 * D, len(on)); on2 = on + sh; en2 = en + sh
                ok = on2 < np.int64(END.value // 10**9)
                s2 = stats(on2[ok], en2[ok], times, k)
                for kk in sims: sims[kk].append(s2[kk].mean())
            for kk in obs:
                a = np.array(sims[kk]); tabs.append(dict(storm=sname, n_storms=len(st), flare=fname, window_days=k, timing=kk,
                    observed_frac=round(obs[kk], 3), observed_n=int(round(obs[kk] * len(st))), chance_frac_mean=round(a.mean(), 3),
                    chance_frac_95=[round(np.percentile(a, 2.5), 3), round(np.percentile(a, 97.5), 3)],
                    ratio_obs_to_chance=round(obs[kk] / a.mean(), 2) if a.mean() > 0 else None,
                    p_value=round(((a >= obs[kk]).sum() + 1) / (len(a) + 1), 4)))
    # per-storm table
    s = stats(on, en, fp[5e-5], 3); sx = stats(on, en, fp[1e-4], 3)
    st = st.assign(m5_before3d=s['before'], m5_during=s['during'], m5_after3d=s['after'], x_before3d=sx['before'], x_during=sx['during'], x_after3d=sx['after'])
    # biggest flare in [onset-3d, end+3d]
    big = []
    for a, b in zip(st.onset, st.end):
        w = fl[(fl.peak >= a - pd.Timedelta(days=3)) & (fl.peak < b + pd.Timedelta(days=3))]
        big.append(('' if w.empty else f"{w.loc[w.F.idxmax(), 'cls_reported']} ({w.loc[w.F.idxmax(), 'peak']:%Y-%m-%d %H:%M})"))
    st['largest_flare_onset-3d_to_end+3d_as_reported'] = big
    st.to_csv(T / f'storms_{sname.replace("+", "plus")}_{SCALE}.csv', index=False); res[sname] = st
tab = pd.DataFrame(tabs); tab.to_csv(T / f'storm_flare_association_{SCALE}.csv', index=False)
# ---- X flares followed by a storm
out = []
for sname in ('G3+', 'G4+'):
    st = res[sname]; on = st.onset.values.astype('datetime64[s]').astype(np.int64); on.sort()
    for fname, ft in [('X', 1e-4), ('M5+', 5e-5)]:
        f = fp[ft]; f = f[f < np.int64((END - pd.Timedelta(days=4)).value // 10**9)]
        for k in (2, 3, 4):
            obs = any_in(on, f, f + k * D).mean(); sims = []
            for _ in range(5000):
                f2 = f + rng.integers(-182 * D, 182 * D, len(f)); sims.append(any_in(on, f2, f2 + k * D).mean())
            a = np.array(sims); out.append(dict(storm=sname, flare=fname, n_flares=len(f), within_days=k, observed_frac=round(obs, 3),
                observed_n=int(round(obs * len(f))), chance_frac_mean=round(a.mean(), 3), chance_95=[round(np.percentile(a, 2.5), 3), round(np.percentile(a, 97.5), 3)],
                ratio=round(obs / a.mean(), 2), p_value=round(((a >= obs).sum() + 1) / (len(a) + 1), 4)))
fx = pd.DataFrame(out); fx.to_csv(T / f'flare_followed_by_storm_{SCALE}.csv', index=False)
# ---- per-year counts (days)
fl['day'] = fl.peak.dt.floor('D'); kp['day'] = kp.t.dt.floor('D')
m5d = set(fl[fl.F >= 5e-5].day); xd = set(fl[fl.F >= 1e-4].day)
g3d = set(kp[kp.kp >= 6.66].day); g4d = set(kp[kp.kp >= 7.66].day)
comp = {d for d in g3d if any((d - pd.Timedelta(days=i)) in m5d for i in range(0, 4))}   # G3+ day with M5+ that day or within the 3 days before
yrs = []
for y in range(1996, 2027):
    f = lambda S: sum(1 for d in S if d.year == y)
    yrs.append(dict(year=y, days_M5plus_flare=f(m5d), days_X_flare=f(xd), days_G3plus=f(g3d), days_G4plus=f(g4d),
                    days_G3_and_M5_same_day=f(g3d & m5d), days_G3_with_M5_same_or_prev3d=f(comp),
                    days_either_M5_or_G3=f(m5d | g3d), g3_storm_events=int((res['G3+'].onset.dt.year == y).sum()),
                    g3_events_with_M5_before_or_during=int(((res['G3+'].onset.dt.year == y) & (res['G3+'].m5_before3d | res['G3+'].m5_during)).sum())))
yr = pd.DataFrame(yrs); yr.to_csv(T / f'per_year_counts_{SCALE}.csv', index=False)
# ---- per cycle (SILSO minima: Aug 2008 ~ Dec 2008, Dec 2019)
cyc = [('Cycle 23 (1996-08 to 2008-12)', '1996-08-01', '2008-12-01'), ('Cycle 24 (2008-12 to 2019-12)', '2008-12-01', '2019-12-01'),
       ('Cycle 25 (2019-12 to 2026-10)', '2019-12-01', '2026-10-25')]
cy = []
for lab, a, b in cyc:
    for sname in ('G3+', 'G4+', 'G5'):
        s = res[sname]; s = s[(s.onset >= a) & (s.onset < b)]
        cy.append(dict(cycle=lab, storm=sname, n_storms=len(s), with_M5_before3d_or_during=int((s.m5_before3d | s.m5_during).sum()),
                       with_M5_any_minus3d_to_plus3d=int((s.m5_before3d | s.m5_during | s.m5_after3d).sum()),
                       with_X_before3d_or_during=int((s.x_before3d | s.x_during).sum()), with_flare_DURING_storm_M5=int(s.m5_during.sum())))
cy = pd.DataFrame(cy); cy.to_csv(T / f'per_cycle_counts_{SCALE}.csv', index=False)
# Dst <= -100 sensitivity (storm = hours with Dst<=-100 merged 24 h)
s = dst[dst.dst <= -100].t.sort_values().tolist(); ev = []
for t in s:
    if ev and (t - ev[-1][1]).total_seconds() <= 86400: ev[-1][1] = t
    else: ev.append([t, t])
dd = pd.DataFrame(ev, columns=['onset', 'end']); dd['end'] += pd.Timedelta(hours=1)
dd = dd[~((dd.onset >= CAT_GAP[0] - pd.Timedelta(days=4)) & (dd.onset <= CAT_GAP[1] + pd.Timedelta(days=4)))]
on, en = windows(dd); obs = stats(on, en, fp[5e-5], 3)['before_or_during'].mean(); sims = []
for _ in range(5000):
    sh = rng.integers(-182 * D, 182 * D, len(on)); sims.append(stats(on + sh, en + sh, fp[5e-5], 3)['before_or_during'].mean())
a = np.array(sims)
summ = dict(scale=SCALE, n_flares_M5=int(len(fp[5e-5])), n_flares_X=int(len(fp[1e-4])), n_G3=len(res['G3+']), n_G4=len(res['G4+']), n_G5=len(res['G5']),
            dst100=dict(n=len(dd), obs=round(obs, 3), chance=round(a.mean(), 3), ratio=round(obs / a.mean(), 2), p=round(((a >= obs).sum() + 1) / 5001, 4)),
            years_with_compound_G3_M5=int((yr.g3_events_with_M5_before_or_during > 0).sum()), years_total=len(yr))
json.dump(summ, open(T / f'double_whammy_summary_{SCALE}.json', 'w'), indent=1, default=str)
print(json.dumps(summ, indent=1, default=str))
print(tab[(tab.window_days == 3)].to_string()); print(fx.to_string()); print(cy.to_string()); print(yr.to_string())
