# Starlink History Logger

Polls the LEO satellite broadband dish's local gRPC API and stores its per-second performance
history in a SQLite database, with UTC timestamps ready to correlate against
GNSS/ionosphere data and space-weather indices.

## What it records

**`history`** — one row per second (the core data):

| column            | meaning                                             |
|-------------------|-----------------------------------------------------|
| `ts_utc`          | ISO-8601 UTC timestamp (primary key)                |
| `counter`         | dish sample counter (resets on reboot; for provenance) |
| `ping_drop_rate`  | 0.0 = perfect second, 1.0 = full outage that second |
| `ping_latency_ms` | round-trip latency (NULL during a full-drop second) |
| `downlink_bps`    | download throughput, bits/s                         |
| `uplink_bps`      | upload throughput, bits/s                           |
| `power_w`         | dish power draw, watts                              |

**`status_snapshot`** — one row per poll: `fraction_obstructed` and
`currently_obstructed` (your obstruction confounder), plus current state,
uptime and throughput.

**`poll_log`** — one row per poll for health/completeness auditing (how many
samples each poll captured, and any errors).

> Note: `snr`, `scheduled` and `obstructed` were removed from the dish's bulk
> history by a later dish firmware, so per-second SNR is not available. Obstruction is
> still captured as a per-poll snapshot in `status_snapshot`.

## Requirements

* Python 3
* [sparky8512/starlink-grpc-tools](https://github.com/sparky8512/starlink-grpc-tools)
  cloned locally
* The three Python packages `grpcio`, `protobuf`, `yagrc`
* The logging machine on the same LAN as the dish (must be able to reach
  `DISH_GRPC_HOST`, typical port 9200). Verify:
  ```bash
  grpcurl -plaintext -d '{"get_device_info":{}}' "${DISH_GRPC_HOST:-DISH_GRPC_HOST}:9200" \
      SpaceX.API.Device.Device/Handle
  ```

## Setup (use a virtual environment)

Recent Raspberry Pi OS / Debian block `pip3 install ...` into the system Python
with an **externally-managed-environment** error. The fix is a virtual
environment — an isolated Python that you own. The included `setup.sh` does the
whole thing:

```bash
chmod +x setup.sh
./setup.sh
```

That creates the venv at `~/starlink-venv`, installs the three dependencies into
it, and clones `starlink-grpc-tools` if you don't already have it.

<details>
<summary>Or do it by hand</summary>

```bash
sudo apt install -y python3-venv git
python3 -m venv ~/starlink-venv
~/starlink-venv/bin/pip install grpcio protobuf yagrc
git clone --depth 1 https://github.com/sparky8512/starlink-grpc-tools.git ~/starlink-grpc-tools
```
</details>

**Key idea:** you never need to `source .../activate`. Everywhere you'd run
`python3`, run the venv's copy instead — `~/starlink-venv/bin/python3`. The
service file and cron line below already do this.

## Quick test (foreground)

```bash
# venv python + PYTHONPATH pointing at your starlink-grpc-tools checkout
PYTHONPATH=/home/pi/starlink-grpc-tools \
  ~/starlink-venv/bin/python3 starlink_logger.py \
  --db ./starlink_history.db --interval 300 --verbose
```

On the first poll it grabs the entire buffer the dish is holding (often a few
hours), then only new samples after that. Leave it a couple of minutes, Ctrl-C,
and check it worked:

```bash
sqlite3 starlink_history.db \
  "SELECT COUNT(*), MIN(ts_utc), MAX(ts_utc) FROM history;"
```

## Deploy as a service (recommended)

Runs on boot and restarts itself after a crash, reboot, or dish outage.

```bash
# edit the paths / user at the top of the unit first — note ExecStart must
# point at ~/starlink-venv/bin/python3, NOT /usr/bin/python3
sudo cp starlink-logger.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now starlink-logger
journalctl -u starlink-logger -f          # watch it run
```

## Alternative: cron (one poll per run)

The `--once` flag does a single fetch-and-store and exits; the database itself
holds the resume point, so cron is crash-safe too.

```cron
*/5 * * * * PYTHONPATH=/home/pi/starlink-grpc-tools /home/pi/starlink-venv/bin/python3 \
  /home/pi/starlink-logger/starlink_logger.py --once \
  --db /home/pi/starlink-logger/starlink_history.db
```

Because the dish buffers hours of history, a 5-minute cadence never loses data.

## Example analysis queries

Daily availability and typical latency:

```sql
SELECT substr(ts_utc,1,10) AS day,
       ROUND(AVG(ping_drop_rate)*100, 3) AS pct_dropped,
       ROUND(AVG(ping_latency_ms), 1)    AS avg_latency_ms,
       COUNT(*)                          AS seconds_logged
FROM history
GROUP BY day ORDER BY day;
```

Worst latency minutes (candidate storm windows), excluding obstruction:

```sql
SELECT h.ts_utc, h.ping_latency_ms, h.ping_drop_rate, s.fraction_obstructed
FROM history h
LEFT JOIN status_snapshot s
       ON s.ts_utc = strftime('%Y-%m-%dT%H:%M:00+00:00', h.ts_utc)
WHERE h.ping_latency_ms IS NOT NULL
ORDER BY h.ping_latency_ms DESC
LIMIT 50;
```

Data completeness audit (gaps show as missing seconds):

```sql
SELECT COUNT(*) AS ok_polls,
       SUM(samples_fetched) AS total_samples,
       MIN(ts_utc) AS first_poll, MAX(ts_utc) AS last_poll
FROM poll_log WHERE status='ok';
```

## How resume / reboot handling works

Each poll resumes from the previous poll's `end_counter`, so only new samples
are fetched. The dish's sample counter resets to 0 on reboot; the underlying
library detects this and returns the current buffer, and because the `history`
table is keyed on UTC timestamp (not the counter), post-reboot samples never
collide with pre-reboot ones. This was verified offline with a simulated dish
(`test_logger.py`), including the reboot case.
