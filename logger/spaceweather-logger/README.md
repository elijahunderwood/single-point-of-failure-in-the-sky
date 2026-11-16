# Space Weather Logger

Fetches NOAA SWPC geomagnetic and solar-wind data into `spaceweather.db`, with
UTC timestamps in the same format as the Starlink logger so the two join cleanly.

## What it records

| Table | Cadence | Columns |
|-------|---------|---------|
| `kp_index` | 3-hourly | `ts_utc`, `kp`, `a_running`, `station_count` |
| `dst_index` | hourly | `ts_utc`, `dst` (nT) |
| `solar_wind_plasma` | ~1 min | `ts_utc`, `density`, `speed_kms`, `temperature` |
| `solar_wind_mag` | ~1 min | `ts_utc`, `bt`, `bx_gsm`, `by_gsm`, `bz_gsm` |
| `fetch_log` | per poll | `id`, `ts_utc`, `source`, `rows_new`, `status` |

**For your project:** `kp` defines storm onsets (Kp >= 5 = storm), `dst` measures
storm intensity, `speed_kms` reveals the 27-day recurrence from coronal holes, and
`bz_gsm` is the coupling driver (strong southward/negative Bz drives activity).

## Requirements

None beyond Python 3 — this logger uses only the standard library (no pip
installs). It reuses the same virtual-env python as the Starlink logger purely
for consistency.

## Quick test

```bash
~/starlink-venv/bin/python3 spaceweather_logger.py --db ./spaceweather.db --once --verbose
```
You should see `+N new` for each of kp, dst, plasma, mag. Then check:
```bash
sqlite3 -header -column ./spaceweather.db \
  "SELECT ts_utc, kp FROM kp_index ORDER BY ts_utc DESC LIMIT 5;"
```

## Deploy as a service

```bash
mkdir -p ~/spaceweather-logger
mv ~/Downloads/spaceweather_logger.py ~/spaceweather-logger/
# edit paths / user in the unit first
sudo cp spaceweather-logger.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now spaceweather-logger
journalctl -u spaceweather-logger -f
```

Polls every 15 minutes. Each feed returns a rolling window (1 day for solar wind,
weeks for Kp), so a 15-minute cadence captures everything with overlap; duplicate
timestamps are ignored.

## Health check

```bash
# newest fetch per source, and any failures
sqlite3 -header -column ~/spaceweather-logger/spaceweather.db \
  "SELECT source, MAX(ts_utc) AS last_ok, SUM(rows_new) AS total_rows
   FROM fetch_log WHERE status='ok' GROUP BY source;"

sqlite3 -header -column ~/spaceweather-logger/spaceweather.db \
  "SELECT ts_utc, source, status FROM fetch_log WHERE status<>'ok' ORDER BY id DESC LIMIT 20;"
```

## Joining with the Starlink data (the whole point)

The two databases are separate files, joined at analysis time with `ATTACH`.
Because both use the same ISO-8601 UTC timestamp format, you can line them up
directly. Example: average Starlink latency per 3-hour Kp window.

```bash
sqlite3 ~/starlink-logger/starlink_history.db
```
```sql
ATTACH '~/spaceweather-logger/spaceweather.db' AS sw;

-- Kp value alongside Starlink performance in the same 3-hour window
SELECT k.ts_utc AS window_start,
       k.kp,
       ROUND(AVG(h.ping_latency_ms), 1) AS avg_latency_ms,
       ROUND(AVG(h.ping_drop_rate)*100, 3) AS pct_dropped,
       COUNT(*) AS seconds
FROM sw.kp_index k
JOIN main.history h
  ON h.ts_utc >= k.ts_utc
 AND h.ts_utc <  datetime(k.ts_utc, '+3 hours')
GROUP BY k.ts_utc
ORDER BY k.ts_utc;
```

That query is, in miniature, your whole experiment: link quality as a function of
geomagnetic activity. Swap `k.kp` for `sw.solar_wind_mag.bz_gsm` or
`speed_kms` (joined on the nearest minute) to test the solar-wind drivers.

## Notes

* All data is public NOAA SWPC output. When you write up or present, cite NOAA
  SWPC as the source; the Dst index is courtesy of the World Data Center for
  Geomagnetism, Kyoto.
* Solar-wind gaps (occasional `null` rows) are stored as NULL, not dropped, so
  your completeness audit stays honest.
