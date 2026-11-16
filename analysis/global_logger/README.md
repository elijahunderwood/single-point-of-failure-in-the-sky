# global_logger: worldwide GNSS ROTI logger

This program downloads GPS data from permanent GNSS stations around the world. It works out the ionospheric "roughness" index **ROTI** for each station with **the same pipeline used for the home station** in Belfast, and stores the results in one SQLite database. That makes the home station directly comparable with Tromsø, Svalbard, England, the equator and so on, for both past storms and every new day.

It is pure Python, so it runs on a Raspberry Pi (64-bit Raspberry Pi OS), a Mac, Linux or Windows.

---

## 1. Install (once)

```bash
cd global_logger
python3 -m venv .venv && source .venv/bin/activate     # optional but tidy
pip install -r requirements.txt
```

You need Python 3.9 or newer and about 200 MB of free disk space while running. Raw files are deleted after processing unless you set `keep_raw: true`.

## 2. Commands

| Command | What it does |
|---|---|
| `python -m global_logger check --storm may2024` | Asks the archive which stations have data for each storm day. Downloads nothing. |
| `python -m global_logger backfill --storm may2024` | Downloads and processes every station for every day of that storm (listed in `config/storms.yaml`), plus Kp and Dst. |
| `python -m global_logger backfill --storm may2024 --stations TRO1,MORP` | Same, but only for the stations you list. |
| `python -m global_logger daily` | Processes **yesterday** (UTC) for all stations and updates Kp/Dst. This is "live mode". |
| `python -m global_logger daily --date 2026-10-04` | Processes one particular day. |
| `python -m global_logger indices --start 2024-05-01 --end 2024-05-31` | Fetches only Kp (GFZ) and Dst (Kyoto). |
| `python -m global_logger import-home --db /path/to/gnss_tec.db [--start 2026-10-04 --end 2026-10-06]` | Runs **your own station's** database through the same ROTI code. It is stored as station `HOME`. |
| `python -m global_logger plot --storm may2024 --quiet quiet_may2024` | Draws the figure of ROTI against magnetic latitude and time, plus a JSON summary, in `figures/`. |
| `python -m global_logger status` | Shows what has been processed so far. |

**Resume:** each station-day is recorded in the `station_days` table:
- Days marked `ok` or `no_data` are skipped next time, so you can stop the program (Ctrl-C) and restart it safely.
- Days marked `error` are retried automatically next time.
- Add `--force` to redo days that are already done.

**Retry:** every download is tried up to 4 times, waiting 5, 10, 20 and 40 s between tries.

**Logging:** everything is printed and also written to `logs/global_logger.log`.

### Run it every day automatically (Raspberry Pi / Mac)
Type `crontab -e` and add this line. It runs at 06:30 UTC, when yesterday's files are normally in the archive:
```
30 6 * * * cd /home/pi/global_logger && /home/pi/global_logger/.venv/bin/python -m global_logger daily >> logs/cron.log 2>&1
```

## 3. What happens to the data, step by step

1. **Find the file.**
   - The program asks the *Geoscience Australia GNSS Data Repository* (`data.gnss.ga.gov.au`, free, no login) for the station's daily 30-second observation file.
   - The archive answers with a temporary download link, which is downloaded straight away.
   - RINEX 3 is preferred. RINEX 2 is used if that is all there is (e.g. MORP).
2. **Unpack.**
   - Files are "Hatanaka-compressed" (`.crx.gz` / `.d.gz`), a special compression for GNSS data.
   - The `hatanaka` package turns them back into normal RINEX text.
3. **Read the observations.**
   - For each GPS satellite, every 30 s, the program keeps:
     - the carrier phase on L1 (1575.42 MHz) and L2 (1227.60 MHz)
     - the loss-of-lock indicator (LLI)
     - the L1 signal strength
   - From the file header it also reads the station position, receiver type and sampling interval.
4. **Satellite elevations.**
   - The program downloads the IGS broadcast orbit file for that day (`brdcDDD0.YYn`) from the same archive.
   - It computes each satellite's position with the official GPS equations (IS-GPS-200).
   - From that it works out the elevation angle seen from the station: computed every 5 minutes and interpolated in between.
5. **TEC.**
   - TEC = 9.52 × (L1 phase in metres − L2 phase in metres).
   - The distance and clocks are the same on both frequencies and cancel. Only the ionosphere's frequency-dependent delay is left.
6. **Arcs and cycle slips.** A new arc starts when:
   - the receiver sets the loss-of-lock flag, or
   - there is a gap of more than 45 s, or
   - TEC jumps by more than 5 TECU between epochs.
7. **ROT.**
   - Within an arc, take TEC values 30 s apart: ROT = ΔTEC/Δt in TECU per minute.
   - Values above 10 TECU/min are thrown away as leftover slips.
8. **ROTI.**
   - ROTI is the standard deviation of ROT in each 5-minute window, for each satellite above **20°**.
   - A window needs at least 5 ROT values.
9. **Network index.** For every 5-minute window across satellites (at least 3 needed), the program stores:
   - the maximum
   - the **2nd-highest** (two satellites must agree)
   - the median and the mean
   - the number of satellites
   - the fraction of satellites above 0.5 TECU/min
10. **Store.**
    - Results go into `data/global_roti.db`. Table and column names match the home station's Data Dictionary, plus a `station` column.
    - Times are ISO-8601 UTC, e.g. `2024-05-10T22:05:00+00:00`.
11. **Geomagnetic latitude.**
    - Station coordinates are converted to geomagnetic latitude with the IGRF-2025 dipole.
    - That is good to ~1–2°. Near the magnetic equator, "dip latitude" is the better coordinate.
12. **Space weather.**
    - Kp comes from GFZ Potsdam, the official Kp provider.
    - Dst comes from Kyoto WDC. The program uses the final product if it exists, otherwise provisional, otherwise real-time.

All processing settings are in `config/settings.yaml`. They are **identical to the home-station reanalysis** (20° mask, 30-s base, 5-min windows, 0.5 threshold), so results are like-for-like. The home station logs at 1 Hz, so `import-home` uses a 2.5-s gap and a 1-TECU jump limit for its arcs. Everything else is the same.

## 4. Database tables

| Table | Columns |
|---|---|
| `stations` | station, name, lat, lon, height_m, geomag_lat, band, receiver, antenna, interval_s, archive |
| `roti` | window_start, station, sv, roti (TECU/min), n_samples, mean_elev (°) |
| `roti_network` | window_start, station, roti_max, roti_2nd, roti_med, roti_mean, n_sats, frac_gt05 |
| `kp_index` | ts_utc, kp, status (def/nowcast), source |
| `dst_index` | ts_utc, dst (nT), product (final/provisional/realtime) |
| `station_days` | station, day, status (ok/no_data/error), file, n_obs, n_windows, rot_rejected_pct, message, updated_utc |
| `fetch_log` | id, ts_utc, source, status |

Example query: the robust ROTI at Morpeth during the May 2024 storm.
```sql
SELECT window_start, roti_2nd FROM roti_network WHERE station='MORP' AND window_start LIKE '2024-05-10%';
```

## 5. Adding stations or storms
- **Station:** add a line to `config/stations.yaml` with the 4-character IGS code. Run `check` first to see whether the archive has it.
- **Storm:** add an entry to `config/storms.yaml`. Look up Kp at kp.gfz.de and Dst at wdc.kugi.kyoto-u.ac.jp; don't guess.

## 6. Known limitations (be ready to explain these)
- **GPS only.** Galileo and GLONASS are not used yet. That keeps it the same as the home receiver's GPS-only TEC.
- **Broadcast orbits** are used for elevations. They are accurate to a few metres, far better than needed for an elevation angle. Precise orbits are not needed.
- **Very extreme ROT is capped.** In a superstorm, a few genuine ROT values above 10 TECU/min (or TEC jumps above 5 TECU in 30 s) are treated as slips. I tested TRO1 on 11 May 2024: switching this off changed the share of windows above 0.5 by less than 0.1 percentage points, but the top 1 % of ROTI went from 4.6 to 6.6 TECU/min. So peak values are conservative.
- **Different receivers have different noise floors.** Always compare a station with **its own quiet day**, not with another station's raw numbers.
- **One archive.** Geoscience Australia was the only no-login archive reachable from the test machine. BKG (igs.bkg.bund.de) and IGN (igs.ign.fr) are also free but timed out during testing. CDDIS (NASA) needs an Earthdata login. EarthScope/UNAVCO GAGE needs a login.

*AI disclosure:* this software was written with AI assistance (Grok Bot) for Elijah to review, understand and own. Each step is explained above.

## 7. Cross-storm summary
`python -m global_logger summary` does three things:
- redraws every storm figure;
- draws `figures/cross_storm_excess_vs_maglat.png`, which shows each station's worst storm day minus its own season-matched quiet day;
- fits a logistic curve of P(a 3-hour block is disturbed) against Kp and saves the result as `figures/kp_threshold.json` and `kp_threshold_morpeth_home.png`. The 95% confidence interval comes from resampling whole days.

Home data can be added from CSV exports with `import-home --db file1.csv file2.csv ...`.
