from pathlib import Path as _RepoPath
import os as _repo_os
REPO_ROOT = _RepoPath(_repo_os.environ.get('REPO_ROOT', _RepoPath(__file__).resolve().parents[2]))
# C/N0 dips at flare peaks in home 1 Hz data (sidereal-day comparison)
import sqlite3, pandas as pd, numpy as np, json
H = sqlite3.connect('file:' + _repo_os.environ.get('GNSS_TEC_DB', str(_RepoPath.home() / 'gnss-logger' / 'gnss_tec.db')) + '?mode=ro', uri=True)
F = sqlite3.connect('file:' + _repo_os.environ.get('FLARE_DB', str(_RepoPath.home() / 'flare_logger' / 'flare.db')) + '?mode=ro', uri=True)
fl = pd.read_sql("select flare_id, begin_utc, peak_utc, end_utc, class from flares where class like 'M%' or class like 'X%'", F)
SID = pd.Timedelta(seconds=86164.09)
out = []
for _, f in fl.iterrows():
    p = pd.Timestamp(f.peak_utc); w0, w1 = p - pd.Timedelta(minutes=40), p + pd.Timedelta(minutes=40)
    def load(a, b):
        d = pd.read_sql("select ts_utc, sv, elev_deg, cno_l1, cno_l2 from tec where ts_utc>=? and ts_utc<?", H,
                        params=(a.strftime('%Y-%m-%dT%H:%M:%S'), b.strftime('%Y-%m-%dT%H:%M:%S')))
        d['t'] = pd.to_datetime(d.ts_utc, utc=True, format='ISO8601'); return d
    d = load(w0, w1)
    if d.empty: continue
    ref = load(w0 - SID, w1 - SID); ref['t'] = ref.t + SID
    res = {'flare_id': f.flare_id, 'class': f['class'], 'peak': f.peak_utc, 'n_sv': int(d.sv.nunique()), 'ref_available': not ref.empty}
    for band in ('cno_l1', 'cno_l2'):
        if d[band].isna().all(): continue
        dd = d[d.elev_deg >= 20].copy(); dd['m'] = ((dd.t - p).dt.total_seconds() // 60).astype(int)
        s = dd.groupby(['m', 'sv'])[band].mean().groupby('m').mean()   # mean over sats per minute
        near = s[(s.index >= -5) & (s.index <= 10)]; pre = s[(s.index >= -40) & (s.index < -10)]
        res[band + '_pre_mean'] = float(pre.mean()); res[band + '_pre_sd'] = float(pre.std())
        res[band + '_min_near_peak'] = float(near.min()); res[band + '_dip_db'] = float(pre.mean() - near.min())
        if not ref.empty and not ref[band].isna().all():
            rr = ref[ref.elev_deg >= 20].copy(); rr['m'] = ((rr.t - p).dt.total_seconds() // 60).astype(int)
            m = dd.merge(rr[['m', 'sv', band]], on=['m', 'sv'], suffixes=('', '_ref'))
            diff = m.assign(dl=m[band] - m[band + '_ref']).groupby('m').dl.mean()
            res[band + '_sidereal_diff_near_peak_min'] = float(diff[(diff.index >= -5) & (diff.index <= 10)].min()) if len(diff) else None
            res[band + '_sidereal_diff_pre_sd'] = float(diff[diff.index < -10].std()) if len(diff) else None
    out.append(res)
print(json.dumps(out, indent=1))
json.dump(out, open('cno_check.json', 'w'), indent=1)
