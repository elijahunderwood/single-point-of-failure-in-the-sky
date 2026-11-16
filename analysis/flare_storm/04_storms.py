#!/usr/bin/env python3
"""Storm impacts from the project's own data.
 (a) Global archive (17 IGS/EUREF stations, same ROTI pipeline as Belfast): % of satellite 5-min windows with
     ROTI > 0.5 TECU/min on each storm day vs quiet days, by station (sorted by geomagnetic latitude).
 (b) Belfast receiver (roti.db, Jul-Oct 2026): ROTI vs Kp class, bootstrap by day.
 (c) Starlink hourly latency/drop vs Kp with rain (Open-Meteo hourly, localweather.db) and hour-of-day controls."""
import sqlite3, numpy as np, pandas as pd, json
from pathlib import Path
B = Path(__file__).resolve().parents[1]; D = B / 'data'; T = B / 'tables'
rng = np.random.default_rng(7)
ro = lambda f: sqlite3.connect(f"file:{D / f}?mode=ro", uri=True)
G = ro('global_roti.db')
st = pd.read_sql('select station,name,geomag_lat,band from stations', G)
net = pd.read_sql('select window_start,station,roti_med,roti_2nd,n_sats,frac_gt05 from roti_network', G)
net['t'] = pd.to_datetime(net.window_start, utc=True); net['day'] = net.t.dt.strftime('%Y-%m-%d')
kpg = pd.read_csv(T / 'kp_gfz_1996_2026.csv', parse_dates=['t']); kpg['day'] = kpg.t.dt.strftime('%Y-%m-%d')
kpday = kpg.groupby('day').kp.max()
dst = pd.read_csv(T / 'dst_omni_1996_2026.csv', parse_dates=['t']); dst['day'] = dst.t.dt.strftime('%Y-%m-%d'); dstday = dst.groupby('day').dst.min()
STORMS = {'2023-04-23': 'Apr 2023 (G4; largest flare M1.7)', '2023-04-24': 'Apr 2023 day 2', '2024-05-10': 'May 2024 (G5; X flares before & during)',
          '2024-05-11': 'May 2024 day 2', '2024-05-12': 'May 2024 day 3', '2024-08-12': 'Aug 2024 (G4)', '2024-10-10': 'Oct 2024 (G5 by GFZ Kp; X1.8 source)',
          '2024-10-11': 'Oct 2024 day 2', '2025-06-01': 'Jun 2025 (G4)', '2025-06-02': 'Jun 2025 day 2', '2025-11-12': 'Nov 2025 (G5 by GFZ Kp; X5.1 source)',
          '2025-11-13': 'Nov 2025 day 2', '2026-10-10': '10 Oct 2026 (G3; M6.8 2 days before, M6.6 during)', '2026-10-11': '11 Oct 2026 recovery'}
QUIET = [d for d in sorted(net.day.unique()) if kpday.get(d, 9) <= 3.0]
day = net.groupby(['station', 'day']).agg(pct_gt05=('frac_gt05', lambda x: 100 * x.mean()), roti_med=('roti_med', 'median'), n=('frac_gt05', 'size')).reset_index()
day = day[day.n >= 144]   # at least half a day of windows
day['kp_max'] = day.day.map(kpday); day['dst_min'] = day.day.map(dstday)
q = day[day.day.isin(QUIET)].groupby('station').pct_gt05.agg(['median', 'count']).rename(columns={'median': 'quiet_pct_median', 'count': 'n_quiet_days'})
sd = day[day.day.isin(STORMS)].copy(); sd['event'] = sd.day.map(STORMS)
tab = sd.pivot_table(index='station', columns='day', values='pct_gt05').join(q).join(st.set_index('station')[['name', 'geomag_lat', 'band']]).sort_values('geomag_lat', ascending=False)
tab.round(1).to_csv(T / 'global_storm_days_pct_roti_gt05.csv')
ev = pd.DataFrame({'day': list(STORMS), 'label': list(STORMS.values())}); ev['kp_max'] = ev.day.map(kpday); ev['dst_min'] = ev.day.map(dstday)
ev.to_csv(T / 'global_storm_days_drivers.csv', index=False)
print(tab.round(1).to_string()); print(ev.to_string()); print('quiet days used:', QUIET)
# (a2) excess over quiet vs Kp, per latitude band, all station-days
day = day.join(q, on='station'); day['excess'] = day.pct_gt05 - day.quiet_pct_median
day = day.merge(st[['station', 'geomag_lat', 'band']], on='station'); day.to_csv(T / 'global_station_days.csv', index=False)
# (b) Belfast own receiver
R = ro('roti.db'); h = pd.read_sql('select window_start,sv,roti,mean_elev from roti where mean_elev>=30', R)
h['t'] = pd.to_datetime(h.window_start, utc=True); h['kp_t'] = h.t.dt.floor('3h').dt.tz_localize(None)
SW = ro('spaceweather.db'); kpl = pd.read_sql('select ts_utc,kp from kp_index', SW); kpl['kp_t'] = pd.to_datetime(kpl.ts_utc, utc=True).dt.tz_localize(None)
h = h.merge(kpl[['kp_t', 'kp']], on='kp_t', how='inner'); h['day'] = h.t.dt.date
bins = [-0.1, 2.0, 3.0, 4.0, 4.9, 6.0, 9.1]; labs = ['0-2', '2-3', '3-4', '4-5-', '5 to 6- (G1-G2)', '6+ (G2-G3)']
h['kpbin'] = pd.cut(h.kp, bins, labels=labs)
rows = []
for b_, g in h.groupby('kpbin', observed=True):
    days = g.day.unique(); per = g.groupby('day').apply(lambda x: ((x.roti > 0.5).mean(), x.roti.median(), len(x)), include_groups=False)
    bs = []
    for _ in range(2000):
        pick = rng.choice(len(days), len(days)); sel = pd.concat([g[g.day == days[i]] for i in pick[:60]]) if len(days) > 60 else pd.concat([g[g.day == days[i]] for i in pick])
        bs.append(100 * (sel.roti > 0.5).mean())
        if _ >= 400: break
    rows.append(dict(kp_bin=b_, n_sat_windows=len(g), n_days=len(days), n_3h_blocks=g.kp_t.nunique(), pct_roti_gt05=round(100 * (g.roti > 0.5).mean(), 2),
                     ci95=[round(np.percentile(bs, 2.5), 2), round(np.percentile(bs, 97.5), 2)], median_roti=round(g.roti.median(), 3)))
bel = pd.DataFrame(rows); bel.to_csv(T / 'belfast_roti_vs_kp.csv', index=False); print(bel.to_string())
# (c) Starlink hourly with rain + hour-of-day
sl = pd.read_csv(D / 'win/starlink_hourly.csv'); sl = sl[sl.n >= 3000].copy(); sl['t'] = pd.to_datetime(sl.hour + ':00:00', utc=True)
W = ro('localweather.db'); w = pd.read_sql('select ts_utc,precipitation_mm,cloud_cover_pct from weather_hourly', W); w['t'] = pd.to_datetime(w.ts_utc, utc=True)
sl = sl.merge(w[['t', 'precipitation_mm', 'cloud_cover_pct']], on='t', how='left'); sl['kp_t'] = sl.t.dt.floor('3h').dt.tz_localize(None)
sl = sl.merge(kpl[['kp_t', 'kp']], on='kp_t', how='inner').dropna(subset=['precipitation_mm', 'lat_mean'])
sl['storm'] = (sl.kp >= 4.9).astype(int); sl['rain'] = (sl.precipitation_mm >= 0.1).astype(int); sl['hr'] = sl.t.dt.hour; sl['dayk'] = sl.t.dt.date
X = pd.get_dummies(sl.hr, prefix='h', drop_first=True).astype(float); X.insert(0, 'rain', sl.rain); X.insert(0, 'storm', sl.storm); X.insert(0, 'c', 1.0)
def ols(X, y): return np.linalg.lstsq(X.values, y.values, rcond=None)[0]
out = {}
for yname in ['lat_mean', 'drop_mean']:
    y = sl[yname] * (100 if yname == 'drop_mean' else 1); b = ols(X, y); days = sl.dayk.unique(); bs = []
    idx = {d: np.where(sl.dayk.values == d)[0] for d in days}
    for _ in range(1000):
        ii = np.concatenate([idx[d] for d in rng.choice(days, len(days))]); bs.append(ols(X.iloc[ii], y.iloc[ii])[:3])
    bs = np.array(bs)
    out[yname] = dict(storm_effect=round(b[1], 3), storm_ci95=[round(np.percentile(bs[:, 1], 2.5), 3), round(np.percentile(bs[:, 1], 97.5), 3)],
                      rain_effect=round(b[2], 3), rain_ci95=[round(np.percentile(bs[:, 2], 2.5), 3), round(np.percentile(bs[:, 2], 97.5), 3)],
                      units='ms' if yname == 'lat_mean' else 'percentage points of pings dropped')
out['n_hours'] = int(len(sl)); out['n_storm_hours_kp_ge5'] = int(sl.storm.sum()); out['n_rain_hours'] = int(sl.rain.sum())
out['n_hours_kp_ge6.67'] = int((sl.kp >= 6.66).sum()); out['period'] = [str(sl.t.min()), str(sl.t.max())]
json.dump(out, open(T / 'starlink_storm_rain_regression.json', 'w'), indent=1); print(json.dumps(out, indent=1))
sl.to_csv(T / 'starlink_hourly_with_drivers.csv', index=False)
