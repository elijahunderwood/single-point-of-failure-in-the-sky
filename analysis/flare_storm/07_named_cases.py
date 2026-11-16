#!/usr/bin/env python3
"""Named events checked against the catalogues built in 01 (largest flare within onset-3 d .. end+3 d, max Kp, min Dst)."""
import pandas as pd
from pathlib import Path
B = Path(__file__).resolve().parents[1]; T = B / 'tables'
fl = pd.read_csv(T / 'flare_catalogue_1996_2026.csv', parse_dates=['peak']); kp = pd.read_csv(T / 'kp_gfz_1996_2026.csv', parse_dates=['t'])
dst = pd.read_csv(T / 'dst_omni_1996_2026.csv', parse_dates=['t'])
CASES = [('Bastille Day 2000', '2000-07-12', '2000-07-17'), ('Halloween 2003', '2003-10-26', '2003-11-01'), ('Nov 2004', '2004-11-05', '2004-11-11'),
         ('Jan 2005', '2005-01-17', '2005-01-23'), ('Dec 2006', '2006-12-04', '2006-12-16'), ('Mar 2012', '2012-03-05', '2012-03-10'),
         ('Oct 2014 (big flares, no big storm)', '2014-10-18', '2014-10-31'), ('St Patrick 2015', '2015-03-14', '2015-03-19'),
         ('Sep 2017', '2017-09-04', '2017-09-12'), ('Feb 2022 (minor storm, satellites lost)', '2022-01-29', '2022-02-05'),
         ('Apr 2023 (G4 from M1.7)', '2023-04-20', '2023-04-25'), ('May 2024 Gannon', '2024-05-07', '2024-05-15'), ('Oct 2024', '2024-10-03', '2024-10-12'),
         ('Nov 2025', '2025-11-09', '2025-11-14'), ('Jan 2026', '2026-01-17', '2026-01-22'), ('Oct 2026 (own data)', '2026-10-07', '2026-10-12')]
rows = []
for n, a, b in CASES:
    f = fl[(fl.peak >= a) & (fl.peak < b)]; k = kp[(kp.t >= a) & (kp.t < b)]; d = dst[(dst.t >= a) & (dst.t < b)]
    big = f.sort_values('flux', ascending=False).head(3)
    rows.append(dict(event=n, window_utc=f'{a} to {b}', n_X_flares_reported_scale=int((f.flux_reported >= 1e-4).sum()), n_M5plus_reported=int((f.flux_reported >= 5e-5).sum()),
                     largest_flares_as_reported='; '.join(f"{r.cls_reported} {r.peak:%d %b %H:%M}" for _, r in big.iterrows()),
                     max_kp_gfz=k.kp.max(), first_time_kp_ge_7minus=str(k[k.kp >= 6.66].t.min()) if (k.kp >= 6.66).any() else 'never',
                     min_dst_nT=d.dst.min() if len(d) else None))
pd.DataFrame(rows).to_csv(T / 'named_cases_from_catalogues.csv', index=False); print(pd.DataFrame(rows).to_string())
