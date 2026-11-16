#!/usr/bin/env python3
"""Select OVERLAP cases (M5+ flare peaking from 3 h before G3+ storm onset to the time of minimum Dst, i.e. during the
main phase), matched FLARE-FREE STORM controls and matched FLARE-ONLY controls. Writes tables/overlap_cases.csv and the
list of UQRG daily map files needed (event days + quiet-baseline days)."""
import numpy as np, pandas as pd
from pathlib import Path
B = Path(__file__).resolve().parents[1]; T = B / 'tables'
fl = pd.read_csv(T / 'flare_catalogue_1996_2026.csv', parse_dates=['peak'])
kp = pd.read_csv(T / 'kp_gfz_1996_2026.csv', parse_dates=['t']); dst = pd.read_csv(T / 'dst_omni_1996_2026.csv', parse_dates=['t'])
st = pd.read_csv(T / 'storms_G3plus_goesr.csv', parse_dates=['onset', 'end'])
st = st[(st.onset >= '1998-01-01')].reset_index(drop=True)
def tmin(r):
    d = dst[(dst.t >= r.onset - pd.Timedelta(hours=3)) & (dst.t <= r.end + pd.Timedelta(hours=24))]
    return d.loc[d.dst.idxmin(), 't'] if len(d) else r.end
st['t_dstmin'] = st.apply(tmin, axis=1)
st.loc[st.t_dstmin < st.onset, 't_dstmin'] = st.end
big = fl[fl.flux >= 5e-5]
rows = []
for i, r in st.iterrows():
    w = big[(big.peak >= r.onset - pd.Timedelta(hours=3)) & (big.peak <= max(r.t_dstmin, r.onset + pd.Timedelta(hours=3)))]
    pre = big[(big.peak >= r.onset - pd.Timedelta(days=3)) & (big.peak <= r.end + pd.Timedelta(hours=3))]
    st.loc[i, 'group'] = 'overlap' if len(w) else ('flare_free' if len(pre) == 0 else 'flare_before_only')
    if len(w):
        f = w.loc[w.flux.idxmax()]; st.loc[i, 'flare_peak'] = f.peak; st.loc[i, 'flare_cls'] = f.cls; st.loc[i, 'flare_flux'] = f.flux
st['storm_id'] = st.onset.dt.strftime('S%Y%m%d%H')
ov = st[st.group == 'overlap'].copy(); ff = st[st.group == 'flare_free'].copy()
kpm = kp.set_index('t').kp
def quiet_kp(t):
    w = kpm[(kpm.index >= t - pd.Timedelta(hours=24)) & (kpm.index <= t + pd.Timedelta(hours=24))]; return w.max()
fonly = big[(big.peak >= '1998-01-01')].copy(); fonly['kpmax48'] = fonly.peak.apply(quiet_kp); fonly = fonly[fonly.kpmax48 <= 3.0]
case_rows = []
for _, o in ov.iterrows():
    c = ff.copy(); c['d'] = (c.kp_max - o.kp_max).abs() / 0.667 + (np.log(c.dst_min.abs().clip(30) / max(abs(o.dst_min), 30))).abs() / np.log(1.5)
    c = c.sort_values('d').head(3)
    f = fonly[(fonly.peak.dt.year - o.flare_peak.year).abs() <= 4].copy(); f['d'] = (np.log10(f.flux) - np.log10(o.flare_flux)).abs()
    f = f.sort_values('d').head(4)
    case_rows.append(dict(storm_id=o.storm_id, onset=o.onset, t_dstmin=o.t_dstmin, kp_max=o.kp_max, dst_min=o.dst_min, flare_peak=o.flare_peak, flare_cls=o.flare_cls,
                          flare_flux=o.flare_flux, phase_h=(o.flare_peak - o.onset).total_seconds() / 3600,
                          storm_controls=';'.join(c.storm_id), storm_control_kp=';'.join(f'{x:.2f}' for x in c.kp_max), storm_control_dst=';'.join(f'{x:.0f}' for x in c.dst_min),
                          storm_control_match_d=';'.join(f'{x:.2f}' for x in c.d), flare_controls=';'.join(f.peak.dt.strftime('%Y-%m-%dT%H:%M')),
                          flare_control_cls=';'.join(f.cls)))
cases = pd.DataFrame(case_rows); cases.to_csv(T / 'overlap_cases.csv', index=False)
st.to_csv(T / 'overlap_storm_groups.csv', index=False)
print(st.group.value_counts()); print(cases.to_string())
# files needed: every storm (for the storm-level comparison) + flare-only days; plus quiet baselines
kpd = kp.assign(d=kp.t.dt.floor('D')).groupby('d').kp.max()
def baseline_days(day, n=5):
    prev = [day - pd.Timedelta(days=k) for k in range(1, 16)]; q = [d for d in prev if kpd.get(d, 9) < 4.67][:n]
    return q if len(q) >= 3 else sorted(prev, key=lambda d: kpd.get(d, 9))[:3]
need = set(); evdays = {}
def add(t, hours_after=13):
    days = sorted({(t - pd.Timedelta(hours=2)).floor('D'), t.floor('D'), (t + pd.Timedelta(hours=hours_after)).floor('D')})
    for d in days:
        need.add(d); evdays[d] = baseline_days(d); need.update(evdays[d])
for _, r in st.iterrows(): add(r.onset)
for _, c in cases.iterrows():
    for x in c.flare_controls.split(';'): add(pd.Timestamp(x), 2)
pd.Series(sorted(need)).dt.strftime('%Y-%m-%d').to_csv(B / 'catalogues/uqrg_needed_days.txt', index=False, header=False)
pd.DataFrame([(k.strftime('%Y-%m-%d'), ';'.join(d.strftime('%Y-%m-%d') for d in v)) for k, v in evdays.items()], columns=['day', 'baseline_days']).to_csv(T / 'uqrg_baseline_days.csv', index=False)
print('days needed', len(need))
# ---- 'storm then flare': M5+ flares 0-72 h after a G3+ storm ended (ionosphere still recovering), with flare-only controls
after = []
for _, r in st.iterrows():
    w = big[(big.peak > r.end) & (big.peak <= r.end + pd.Timedelta(hours=72))]
    if len(w):
        f = w.loc[w.flux.idxmax()]
        c = fonly[(fonly.peak.dt.year - f.peak.year).abs() <= 4].copy(); c['d'] = (np.log10(c.flux) - np.log10(f.flux)).abs(); c = c.sort_values('d').head(4)
        after.append(dict(storm_id=r.storm_id, storm_end=r.end, kp_max=r.kp_max, flare_peak=f.peak, flare_cls=f.cls, flare_flux=f.flux,
                          hours_after_end=(f.peak - r.end).total_seconds() / 3600, flare_controls=';'.join(c.peak.dt.strftime('%Y-%m-%dT%H:%M')), flare_control_cls=';'.join(c.cls)))
after = pd.DataFrame(after); after.to_csv(T / 'storm_then_flare_cases.csv', index=False); print('storm-then-flare cases', len(after))
for _, a in after.iterrows():
    add(a.flare_peak, 2)
    for x in a.flare_controls.split(';'): add(pd.Timestamp(x), 2)
pd.Series(sorted(need)).dt.strftime('%Y-%m-%d').to_csv(B / 'catalogues/uqrg_needed_days.txt', index=False, header=False)
pd.DataFrame([(k.strftime('%Y-%m-%d'), ';'.join(d.strftime('%Y-%m-%d') for d in v)) for k, v in evdays.items()], columns=['day', 'baseline_days']).to_csv(T / 'uqrg_baseline_days.csv', index=False)
print('days needed incl. storm-then-flare', len(need))
