#!/usr/bin/env python3
"""Summarise the flare logger's worldwide flare-response table (flare.db: flare_response) by solar zenith angle and class.
Detection rule is the logger's own (written before this analysis). 'Credible' adds: dTEC peak 0-15 min after the X-ray
peak and SZA < 85 deg. Polar-cap stations (NYA1, THU2, MCM4) and noisy station-flares (noise > 0.2 TECU) are flagged."""
import sqlite3, numpy as np, pandas as pd
from pathlib import Path
B = Path(__file__).resolve().parents[1]; T = B / 'tables'
c = sqlite3.connect(f"file:{B / 'data/flare.db'}?mode=ro", uri=True)
fr = pd.read_sql("select r.*, f.class, f.peak_flux from flare_response r join flares f using(flare_id) where r.status='ok'", c)
fr['cbin'] = pd.cut(fr.peak_flux, [1e-5, 2e-5, 5e-5, 1e-4], labels=['M1-M2', 'M2-M5', 'M5-M9'], right=False)
fr['szabin'] = pd.cut(fr.sza_deg, [0, 50, 70, 85, 90], labels=['<50', '50-70', '70-85', '85-90'])
fr['quality'] = (fr.noise_tecu <= 0.2) & ~fr.station.isin(['NYA1', 'THU2', 'MCM4'])
fr['credible'] = (fr.detected == 1) & fr.lag_after_xray_peak_min.between(0, 15) & (fr.sza_deg < 85)
fr.to_csv(T / 'global_flare_station_responses.csv', index=False)
def wilson(k, n, z=1.96):
    if n == 0: return (np.nan, np.nan)
    p = k / n; d = 1 + z * z / n; c0 = (p + z * z / (2 * n)) / d; h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d; return (round(100 * (c0 - h), 1), round(100 * (c0 + h), 1))
rows = []
for (kind, by), g in [(('flare', 'class'), fr[(fr.kind == 'flare') & fr.quality].groupby('cbin', observed=True)),
                      (('flare', 'sza'), fr[(fr.kind == 'flare') & fr.quality].groupby('szabin', observed=True)),
                      (('control', 'all'), fr[(fr.kind == 'control')].groupby('kind'))]:
    for k, x in g:
        n = len(x); kc = int(x.credible.sum()); rows.append(dict(kind=kind, grouping=by, bin=str(k), n_station_flares=n, n_credible=kc,
            pct_credible=round(100 * kc / n, 1) if n else np.nan, ci95=wilson(kc, n), median_peak_dtec_credible=round(x[x.credible].median_peak_dtec.median(), 2) if kc else np.nan))
S = pd.DataFrame(rows); S.to_csv(T / 'global_flare_detection_summary.csv', index=False); print(S.to_string())
big = fr[(fr.kind == 'flare') & (fr.peak_flux >= 5e-5) & fr.credible][['flare_id', 'class', 'station', 'sza_deg', 'median_peak_dtec', 'peak_dtec', 'lag_after_xray_peak_min', 'time_to_peak_min', 'noise_tecu']]
big.round(2).to_csv(T / 'global_flare_M5plus_credible.csv', index=False); print(big.round(2).to_string())
