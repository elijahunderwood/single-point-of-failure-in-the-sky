#!/usr/bin/env python3
"""Runs ON THE PI (read-only). For each flare peak time T, extracts 10-second binned
GNSS (per satellite) + epoch counts + Starlink metrics for three windows:
  flare    : T-60 min .. T+90 min
  ctrl_day : same window 24 h earlier (same UTC time)
  ctrl_sid : same window 23 h 56 min 4 s earlier (GPS geometry repeats -> same multipath)
Output: /tmp/fsa2/*.csv  (opened with mode=ro URIs, nothing is written to the live DBs)."""
import os, sqlite3, csv, sys, datetime as dt
EV = [l.strip().split(',') for l in open('/tmp/fsa2/events.csv')][1:]
G = sqlite3.connect('file:' + os.path.expanduser(os.environ.get('GNSS_TEC_DB', '~/gnss-logger/gnss_tec.db')) + '?mode=ro', uri=True)
S = sqlite3.connect('file:' + os.path.expanduser(os.environ.get('LEO_DB', '~/starlink-logger/starlink_history.db')) + '?mode=ro', uri=True)
fmt = lambda t: t.strftime('%Y-%m-%dT%H:%M:%S')
OFF = {'flare': dt.timedelta(0), 'ctrl_day': dt.timedelta(days=1), 'ctrl_sid': dt.timedelta(seconds=86164)}
wg = csv.writer(open('/tmp/fsa2/gnss10s.csv', 'w')); wg.writerow(['flare_id','win','bin','sv','elev','phase_tec','cno_l1','cno_l2','slips','n'])
we = csv.writer(open('/tmp/fsa2/epoch10s.csv', 'w')); we.writerow(['flare_id','win','bin','num_pairs','num_meas','n'])
ws = csv.writer(open('/tmp/fsa2/starlink10s.csv', 'w')); ws.writerow(['flare_id','win','bin','lat','drop','drop_max','dl','n'])
for fid, peak in [(e[0], e[1]) for e in EV]:
    T = dt.datetime.fromisoformat(peak.replace('+00:00', ''))
    for win, off in OFF.items():
        a, b = fmt(T - off - dt.timedelta(minutes=60)), fmt(T - off + dt.timedelta(minutes=90))
        q = """select substr(ts_utc,1,18) bn, sv, avg(elev_deg), avg(phase_tec), avg(cno_l1), avg(cno_l2), sum(slip), count(*)
               from tec where ts_utc>=? and ts_utc<? group by bn, sv"""
        for r in G.execute(q, (a, b)): wg.writerow([fid, win] + list(r))
        for r in G.execute("select substr(ts_utc,1,18) bn, avg(num_pairs), avg(num_meas), count(*) from epoch_log where ts_utc>=? and ts_utc<? group by bn", (a, b)):
            we.writerow([fid, win] + list(r))
        for r in S.execute("select substr(ts_utc,1,18) bn, avg(ping_latency_ms), avg(ping_drop_rate), max(ping_drop_rate), avg(downlink_bps), count(*) from history where ts_utc>=? and ts_utc<? group by bn", (a, b)):
            ws.writerow([fid, win] + list(r))
    print(fid, 'done', flush=True)
