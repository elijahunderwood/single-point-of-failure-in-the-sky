#!/usr/bin/env python3
"""Same overlap test with the project's own-pipeline ROTI archive (global_roti.db, 30 s data, 5-min windows).
Only two overlap storms (May 2024: X5.8 at 01:23 on 11 May; 10 Oct 2026: M6.6 at 15:10) and one flare-free control storm
of similar size (Apr 2023, Kp 8.33) are in the archive, so this is descriptive (n too small for inference)."""
import sqlite3, numpy as np, pandas as pd, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent)); import ionex as X
B = Path(__file__).resolve().parents[1]; T = B / 'tables'
c = sqlite3.connect(f"file:{B / 'data/global_roti.db'}?mode=ro", uri=True)
st = pd.read_sql('select station,lat,lon,geomag_lat from stations', c)
net = pd.read_sql('select window_start,station,roti_2nd,frac_gt05 from roti_network', c); net['t'] = pd.to_datetime(net.window_start).dt.tz_localize(None)
def sza(t, lat, lon):
    g = X.sza_grid(t); i = int(round((87.5 - lat) / 2.5)); j = int(round((lon + 180) / 5)); return g[min(max(i, 0), 70), min(max(j, 0), 72)]
def band(m):
    m = abs(m); return 'high (>60°)' if m >= 60 else 'sub-auroral (45-60°)' if m >= 45 else 'mid (20-45°)' if m >= 20 else 'low (<20°)'
EV = [('overlap', 'May 2024 G5 + X5.8', pd.Timestamp('2024-05-10 15:00'), pd.Timestamp('2024-05-11 01:23')),
      ('overlap', '10 Oct 2026 G3 + M6.6', pd.Timestamp('2026-10-10 15:00'), pd.Timestamp('2026-10-10 15:10')),
      ('storm-only control', 'Apr 2023 G4 (no flare > M1.7), same phase as May 2024', pd.Timestamp('2023-04-23 18:00'), pd.Timestamp('2023-04-23 18:00') + pd.Timedelta(hours=10.38)),
      ('storm-only control', 'Apr 2023 G4, same phase as Oct 2026', pd.Timestamp('2023-04-23 18:00'), pd.Timestamp('2023-04-23 18:10'))]
rows = []
for kind, lab, onset, tf in EV:
    for _, s in st.iterrows():
        z = sza(tf, s.lat, s.lon)
        x = net[(net.station == s.station)]
        pre = x[(x.t >= tf - pd.Timedelta(minutes=45)) & (x.t < tf - pd.Timedelta(minutes=15))]; post = x[(x.t >= tf) & (x.t < tf + pd.Timedelta(minutes=30))]
        whole = x[(x.t >= onset) & (x.t < onset + pd.Timedelta(hours=12))]
        if len(pre) < 3 or len(post) < 3: continue
        rows.append(dict(kind=kind, event=lab, station=s.station, maglat=round(s.geomag_lat, 1), band=band(s.geomag_lat), sza_deg=round(z, 1), dayside=z < 80,
                         pct_gt05_pre=round(100 * pre.frac_gt05.mean(), 1), pct_gt05_post=round(100 * post.frac_gt05.mean(), 1),
                         jump_pct_points=round(100 * (post.frac_gt05.mean() - pre.frac_gt05.mean()), 1), roti2_jump=round(post.roti_2nd.mean() - pre.roti_2nd.mean(), 3),
                         storm12h_pct_gt05=round(100 * whole.frac_gt05.mean(), 1) if len(whole) > 50 else np.nan))
R = pd.DataFrame(rows); R.to_csv(T / 'overlap_roti_archive_metrics.csv', index=False)
print(R[R.dayside].to_string())
print(R[R.dayside].groupby(['event', 'band']).jump_pct_points.agg(['mean', 'count']).round(1).to_string())
