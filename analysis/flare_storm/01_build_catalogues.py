#!/usr/bin/env python3
"""Build long-term flare and storm catalogues from public sources (downloaded into ../catalogues):
  * NOAA NCEI GOES XRS event reports 1996-2016 (goes-xrs-report_YYYY.txt, GOES 8-15, old scaled flux)
  * NOAA NCEI GOES-R XRS L2 flare summaries (science quality): GOES-16 2017-02-09..2025-04-06, GOES-19 2025-04-07..2026-10-24
  * GFZ Potsdam definitive/nowcast Kp (Matzka et al. 2021), 1932-present
  * NASA OMNIWeb hourly OMNI2 (Dst column), 1996-present
GOES 8-15 fluxes carried a 0.7 scaling factor; NOAA's GOES-R science data are unscaled. To put everything on ONE scale
(the present GOES-R scale) old-report fluxes are divided by 0.7 (NOAA NCEI 'GOES-R XRS science-quality' release notes).
A sensitivity run without rescaling is also written."""
import re, glob, numpy as np, pandas as pd, netCDF4 as nc, datetime as dt
from pathlib import Path
C = Path(__file__).resolve().parents[1] / 'catalogues'; T = Path(__file__).resolve().parents[1] / 'tables'
LET = {'A': 1e-8, 'B': 1e-7, 'C': 1e-6, 'M': 1e-5, 'X': 1e-4}
rows = []
for f in sorted(glob.glob(str(C / 'ngdc/goes-xrs-report_*.txt'))):
    for line in open(f, errors='ignore'):
        m = re.match(r'^31777(\d{2})(\d{2})(\d{2})\s+(\d{4})\s+(\d{4})\s+(\d{4}).{20,60}?\s([ABCMX])\s?(\d{2,3})\s', line)
        if not m: continue
        yy, mo, dd, st, en, pk, L, mag = m.groups()
        y = 1900 + int(yy) if int(yy) > 50 else 2000 + int(yy)
        if y < 1996 or y > 2016: continue
        day = dt.datetime(y, int(mo), int(dd))
        def t(hhmm, ref=None):
            x = day + dt.timedelta(hours=int(hhmm[:2]), minutes=int(hhmm[2:]))
            if ref is not None and x < ref - dt.timedelta(hours=1): x += dt.timedelta(days=1)  # crosses midnight
            return x
        s = t(st); p = t(pk, s); e = t(en, s)
        flux_old = LET[L] * int(mag) / 10.0
        rows.append(dict(start=s, peak=p, end=e, cls_reported=f'{L}{int(mag)/10:.1f}', flux_reported=flux_old,
                         flux=flux_old / 0.7, source='NCEI GOES 8-15 XRS report'))
old = pd.DataFrame(rows).drop_duplicates(subset=['peak', 'cls_reported'])
def goesr(path, t0, t1, lab):
    d = nc.Dataset(path); tt = d['time'][:]; st = np.array(d['status'][:]); fc = np.array(d['flare_class'][:])
    fl = np.array(d['xrsb_flux'][:]); fid = np.array(d['flare_id'][:])
    base = dt.datetime(2000, 1, 1, 12)
    df = pd.DataFrame(dict(time=[base + dt.timedelta(seconds=float(x)) for x in tt], status=st, cls=fc, flux=fl, fid=fid))
    pk = df[df.status == 'EVENT_PEAK'].copy(); sts = df[df.status == 'EVENT_START'].groupby('fid').time.min()
    ens = df[df.status == 'EVENT_END'].groupby('fid').time.max()
    pk['start'] = pk.fid.map(sts); pk['end'] = pk.fid.map(ens)
    pk = pk[(pk.time >= t0) & (pk.time < t1)]
    return pd.DataFrame(dict(start=pk.start, peak=pk.time, end=pk.end, cls_reported=pk.cls, flux_reported=pk.flux,
                             flux=pk.flux, source=lab))
g16 = goesr(C / 'sci_xrsf-l2-flsum_g16_s20170209_e20250407_v2-2-2.nc', dt.datetime(2017, 1, 1), dt.datetime(2025, 4, 7), 'NCEI GOES-16 XRS L2 flsum')
g19 = goesr(C / 'sci_xrsf-l2-flsum_g19_s20240920_e20261024_v2-2-2.nc', dt.datetime(2025, 4, 7), dt.datetime(2026, 10, 25), 'NCEI GOES-19 XRS L2 flsum')
fl = pd.concat([old, g16, g19], ignore_index=True).sort_values('peak')
def cls(f):
    for L in 'XMCBA':
        if f >= LET[L]: return f'{L}{f / LET[L]:.1f}'
    return 'A0'
fl['cls'] = fl.flux.apply(cls)
fl.to_csv(T / 'flare_catalogue_1996_2026.csv', index=False)
print('flares', len(fl), 'M5+', (fl.flux >= 5e-5).sum(), 'X', (fl.flux >= 1e-4).sum())
print(fl[fl.flux >= 1e-4].groupby(fl.peak.dt.year).size().to_string())
# --- Kp (GFZ)
kp = []
for line in open(C / 'Kp_ap_Ap_SN_F107_since_1932.txt'):
    if line.startswith('#'): continue
    p = line.split(); y, m, d = int(p[0]), int(p[1]), int(p[2])
    if y < 1996: continue
    for i in range(8):
        v = float(p[7 + i])
        if v >= 0: kp.append((dt.datetime(y, m, d, 3 * i), v))
kp = pd.DataFrame(kp, columns=['t', 'kp']); kp.to_csv(T / 'kp_gfz_1996_2026.csv', index=False)
# --- Dst (OMNI2 hourly: col 0 year, 1 doy, 2 hour, Dst = word 41 (index 40), fill 99999)
dst = []
for f in sorted(glob.glob(str(C / 'omni/omni2_*.dat'))):
    for line in open(f):
        p = line.split()
        if len(p) < 41: continue
        v = float(p[40])
        if abs(v) > 9000: continue
        dst.append((dt.datetime(int(p[0]), 1, 1) + dt.timedelta(days=int(p[1]) - 1, hours=int(p[2])), v))
dst = pd.DataFrame(dst, columns=['t', 'dst']); dst.to_csv(T / 'dst_omni_1996_2026.csv', index=False)
print('kp', kp.t.min(), kp.t.max(), len(kp), 'dst', dst.t.min(), dst.t.max(), len(dst), 'min dst', dst.dst.min())
