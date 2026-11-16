#!/usr/bin/env python3
"""Superposed-epoch flare study at Belfast (own ZED-F9P + Starlink) for the 20 strongest Belfast-sunlit flares
(C5 and above) with receiver data, plus 3 M flares in Belfast darkness as a 'should be nothing' check.
For every flare: window T-60..T+90 min (T = GOES X-ray peak) and two controls without a flare:
  ctrl_day = same UTC window 24 h earlier; ctrl_sid = 23 h 56 min earlier (same GPS geometry, so same multipath).
Metrics (per event, per window):
  dTEC  : vertical TEC change. Phase TEC per satellite arc (elevation >= 30 deg), 2nd-order polynomial fitted to
          T-60..T-10 and T+40..T+90 only, residual converted to vertical with a 350 km thin shell; network median.
          'jump' = max of the network median in T-10..T+20 minus median of T-30..T-10.
  C/N0  : mean L1/L2 C/N0 (elev >= 30) in T-5..T+15 minus T-60..T-10.
  pairs : GPS L1/L2 pairs tracked per epoch, same windows.   slips : cycle-slip flags per 10 min, same windows.
  Starlink: latency (ms) and ping-drop (%) in T-5..T+20 minus T-60..T-10.
Flare effect = flare-window change minus control-window change; median over events, bootstrap 95% CI of the median."""
import numpy as np, pandas as pd, json
from pathlib import Path
B = Path(__file__).resolve().parents[1]; D = B / 'data' / 'win'; T = B / 'tables'; F = B / 'figures'
rng = np.random.default_rng(1)
ev = pd.read_csv(B / 'data/belfast_flare_events.csv'); ev['flare_id'] = ev.flare_id.astype(str)
night = pd.DataFrame(dict(flare_id=['202609021857', '202610051835', '202610060538'], **{'class': ['M3.0', 'M1.0', 'M1.4']},
                          peak_utc=['2026-09-02T19:20:00+00:00', '2026-10-05T18:48:00+00:00', '2026-10-06T06:10:00+00:00'],
                          peak_flux=[3.0e-5, 1.0e-5, 1.4e-5], belfast_sza_deg=[91.4, 98.9, 94.1]))
ev['group'] = 'sunlit'; night['group'] = 'night'; ev = pd.concat([ev, night], ignore_index=True)
OFF = {'flare': 0, 'ctrl_day': 86400, 'ctrl_sid': 86164}
g = pd.read_csv(D / 'gnss10s.csv', dtype={'flare_id': str}); e = pd.read_csv(D / 'epoch10s.csv', dtype={'flare_id': str})
s = pd.read_csv(D / 'starlink10s.csv', dtype={'flare_id': str})
for df in (g, e, s): df['t'] = pd.to_datetime(df['bin'] + '0', utc=True)
peak = dict(zip(ev.flare_id, pd.to_datetime(ev.peak_utc, utc=True)))
def rel(df):
    df['tm'] = [(t - (peak[f] - pd.Timedelta(seconds=OFF[w]))).total_seconds() / 60 for t, f, w in zip(df.t, df.flare_id, df.win)]
    return df
g, e, s = rel(g), rel(e), rel(s)
RE, H = 6371.0, 350.0
def vmap(el):  # slant->vertical factor
    z = np.radians(90 - el); return np.sqrt(1 - (RE * np.sin(z) / (RE + H)) ** 2)
def dtec_series(sub):
    out = []
    for sv, a in sub[sub.elev >= 30].groupby('sv'):
        a = a.sort_values('tm')
        brk = (a.slips > 0) | (a.tm.diff() > 1.0); a = a.assign(arc=brk.cumsum())
        for _, b in a.groupby('arc'):
            fit = b[((b.tm >= -60) & (b.tm <= -10)) | ((b.tm >= 40) & (b.tm <= 90))]
            if len(fit) < 60 or fit.tm.min() > -40 or fit.tm.max() < 50: continue   # need both sides of the gap
            c = np.polyfit(fit.tm, fit.phase_tec, 2); r = (b.phase_tec - np.polyval(c, b.tm)) * vmap(b.elev)
            rf = (fit.phase_tec - np.polyval(c, fit.tm)) * vmap(fit.elev)
            if rf.std() > 0.5: continue          # reject badly fitted / slip-contaminated arcs (quality rule fixed before looking at flares)
            out.append(pd.DataFrame(dict(tm=b.tm.round(3), sv=sv, d=r.values)))
    if not out: return None
    x = pd.concat(out); gg = x.groupby('tm').d; m = gg.median(); return m[gg.size() >= 2]
rows, curves = [], {}
for fid in ev.flare_id:
    for w in OFF:
        r = dict(flare_id=fid, win=w); sub = g[(g.flare_id == fid) & (g.win == w)]
        ser = dtec_series(sub)
        if ser is not None and len(ser) > 300:
            base = ser[(ser.index >= -30) & (ser.index < -10)].median()
            r['dtec_jump'] = ser[(ser.index >= -10) & (ser.index <= 20)].max() - base
            r['dtec_noise'] = ser[(ser.index >= -60) & (ser.index < -10)].std()
            r['n_sats_dtec'] = sub[(sub.elev >= 30)].sv.nunique(); curves[(fid, w)] = ser
            r['detected'] = int(r['dtec_jump'] > max(3 * r['dtec_noise'], 0.1))
            pk = ser[(ser.index >= -10) & (ser.index <= 20)]; tpk = pk.idxmax(); r['t_peak_min'] = tpk
            after = ser[(ser.index > tpk)]; half = base + (pk.max() - base) / 2
            dn = after[after <= half]; r['decay_to_half_min'] = (dn.index[0] - tpk) if len(dn) else np.nan
        hi = sub[sub.elev >= 30]
        pre, dur = hi[(hi.tm >= -60) & (hi.tm < -10)], hi[(hi.tm >= -5) & (hi.tm < 15)]
        r['dcno_l1'] = dur.cno_l1.mean() - pre.cno_l1.mean(); r['dcno_l2'] = dur.cno_l2.mean() - pre.cno_l2.mean()
        ee = e[(e.flare_id == fid) & (e.win == w)]
        r['dpairs'] = ee[(ee.tm >= -5) & (ee.tm < 15)].num_pairs.mean() - ee[(ee.tm >= -60) & (ee.tm < -10)].num_pairs.mean()
        r['min_pairs_flare'] = ee[(ee.tm >= -5) & (ee.tm < 15)].num_pairs.min()
        r['slips_per10min_dur'] = sub[(sub.tm >= -5) & (sub.tm < 15)].slips.sum() / 2.0
        r['slips_per10min_pre'] = sub[(sub.tm >= -60) & (sub.tm < -10)].slips.sum() / 5.0
        ss = s[(s.flare_id == fid) & (s.win == w)]
        if len(ss) > 200:
            r['dlat_ms'] = ss[(ss.tm >= -5) & (ss.tm < 20)].lat.mean() - ss[(ss.tm >= -60) & (ss.tm < -10)].lat.mean()
            r['ddrop_pct'] = 100 * (ss[(ss.tm >= -5) & (ss.tm < 20)]['drop'].mean() - ss[(ss.tm >= -60) & (ss.tm < -10)]['drop'].mean())
        rows.append(r)
R = pd.DataFrame(rows).merge(ev, on='flare_id'); R.to_csv(T / 'belfast_flare_event_metrics.csv', index=False)
def boot(x):
    x = np.asarray(x, float); x = x[~np.isnan(x)]
    if len(x) < 3: return [np.median(x) if len(x) else np.nan, np.nan, np.nan, len(x)]
    bs = [np.median(rng.choice(x, len(x))) for _ in range(5000)]; return [np.median(x), np.percentile(bs, 2.5), np.percentile(bs, 97.5), len(x)]
summ = []
for grp, sel in [('M flares, sunlit', (ev.group == 'sunlit') & (ev.peak_flux >= 1e-5)), ('C5-C9 flares, sunlit', (ev.group == 'sunlit') & (ev.peak_flux < 1e-5)),
                 ('M6+ flares, sunlit (8 & 10 Oct)', ev.peak_flux >= 6e-5), ('M flares, Belfast in darkness', ev.group == 'night')]:
    ids = set(ev[sel].flare_id)
    for m in ['detected', 'dtec_jump', 'dcno_l1', 'dcno_l2', 'dpairs', 'slips_per10min_dur', 'dlat_ms', 'ddrop_pct']:
        fl = R[(R.flare_id.isin(ids)) & (R.win == 'flare')].set_index('flare_id')[m]
        for cw in ('ctrl_sid', 'ctrl_day'):
            ct = R[(R.flare_id.isin(ids)) & (R.win == cw)].set_index('flare_id')[m]
            diff = (fl - ct).dropna(); b = boot(diff)
            summ.append(dict(group=grp, metric=m, control=cw, flare_median=round(fl.median(), 3), control_median=round(ct.median(), 3), flare_mean=round(fl.mean(), 3), control_mean=round(ct.mean(), 3),
                             effect_median_of_differences=round(b[0], 3), ci95_lo=round(b[1], 3), ci95_hi=round(b[2], 3), n_events=b[3]))
S = pd.DataFrame(summ); S.to_csv(T / 'belfast_flare_effects_summary.csv', index=False)
print(S[S.control == 'ctrl_sid'].to_string())
print(R[R.win == 'flare'][['flare_id', 'class', 'belfast_sza_deg', 'dtec_jump', 'dtec_noise', 'detected', 't_peak_min', 'decay_to_half_min', 'dcno_l1', 'dpairs', 'dlat_ms', 'ddrop_pct']].round(3).to_string())
import pickle; pickle.dump(curves, open(B / 'data/belfast_dtec_curves.pkl', 'wb'))
