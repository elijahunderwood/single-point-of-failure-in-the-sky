#!/usr/bin/env python3
"""Runs ON THE PI (read-only): hourly Starlink and GNSS-epoch summaries over the whole record."""
import os, sqlite3, csv
S = sqlite3.connect('file:' + os.path.expanduser(os.environ.get('LEO_DB', '~/starlink-logger/starlink_history.db')) + '?mode=ro', uri=True)
w = csv.writer(open('/tmp/fsa2/starlink_hourly.csv', 'w'))
w.writerow(['hour','n','lat_mean','lat_med_proxy','drop_mean','outage_s','dl_mean'])
for r in S.execute("""select substr(ts_utc,1,13) h, count(*), avg(ping_latency_ms), null, avg(ping_drop_rate),
                      sum(case when ping_drop_rate>=1 then 1 else 0 end), avg(downlink_bps) from history group by h"""):
    w.writerow(r)
w = csv.writer(open('/tmp/fsa2/starlink_obstruction_hourly.csv', 'w')); w.writerow(['hour','n','obstructed_frac'])
for r in S.execute("select substr(ts_utc,1,13) h, count(*), avg(fraction_obstructed) from status_snapshot group by h"): w.writerow(r)
G = sqlite3.connect('file:' + os.path.expanduser(os.environ.get('GNSS_TEC_DB', '~/gnss-logger/gnss_tec.db')) + '?mode=ro', uri=True)
w = csv.writer(open('/tmp/fsa2/gnss_epoch_hourly.csv', 'w')); w.writerow(['hour','epochs','pairs_mean','pairs_min'])
for r in G.execute("select substr(ts_utc,1,13) h, count(*), avg(num_pairs), min(num_pairs) from epoch_log group by h"): w.writerow(r)
print('hourly done')
