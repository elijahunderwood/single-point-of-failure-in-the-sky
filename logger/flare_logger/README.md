# flare_logger: solar flares and Belfast's ionosphere

This logger records solar-flare X-rays from the GOES satellites and checks whether each big flare made the
total electron content (TEC) above Belfast jump, using the home GNSS receiver (`~/gnss-logger/gnss_tec.db`).
Optionally it runs the same check on the global_logger stations that were on the sunlit side of the Earth.

The idea comes from **Bekker, Milligan & Ryakhovsky (2024), "The Influence of Different Phases of a Solar Flare
on Changes in the Total Electron Content in the Earth's Ionosphere", arXiv:2407.14287**. A flare's X-ray and EUV
light ionises the sunlit ionosphere about a minute after it arrives. They removed the slow daily change in TEC
with a parabola fitted around the flare and measured what was left over (dTEC), finding about 0.2 TECU on average
from the EUV late phase alone.

## Files
| Path | What it is |
|---|---|
| `flare_logger.py` | everything (fetching, analysis, plots); `--help` lists the commands |
| `flare.db` | SQLite database (tables below) |
| `figures/strongest_event.png` | X-ray flux (top) over dTEC per satellite (bottom) for the strongest analysed daytime flare (`plot --flare ID` writes `figures/flare_<ID>.png`) |
| `figures/summary_scatter.png` | mean peak dTEC vs X-ray peak flux for every daytime M/X flare, with control windows |
| `logs/flare_logger.log` | log (also in the journal: `journalctl -u flare-logger`) |
| `flare-logger.service/.timer`, `flare-global.service/.timer` | copies of the systemd units in /etc/systemd/system |
| `venv/` | Python environment (numpy, pandas, matplotlib, netCDF4, hatanaka, PyYAML) |

## How it runs
* **`flare-logger.timer`** runs `flare_logger.py poll` every 10 minutes. It:
  1. downloads NOAA SWPC `json/goes/primary/xrays-1-day.json` (1-minute flux, 0.05-0.4 nm and 0.1-0.8 nm) and
     `xray-flares-7-day.json` (flare start, peak, end, class);
  2. works out the solar zenith angle (SZA) at Belfast (54.6 N, 5.9 W) at each flare's peak (sunlit if SZA < 90);
  3. analyses every M1-or-bigger flare once the home TEC data covers its whole window (about 1 hour after it ends).
* **`flare-global.timer`** runs `flare_logger.py global` daily at 09:30 UTC (see "Global stations").
* The watchdog (`~/db_watchdog.sh`) emails if `xray_flux` has no record newer than 1 hour.
* Email control: `PI <PIN> RESTART flare` runs a poll straight away; `PI <PIN> LOGS flare` sends the last 30 log lines.

## Commands
```bash
cd ~/flare_logger
./venv/bin/python flare_logger.py status                 # counts and latest results
./venv/bin/python flare_logger.py poll                   # what the timer runs
./venv/bin/python flare_logger.py backfill [--start 2026-07-30] [--end 2026-10-16] [--redo]
./venv/bin/python flare_logger.py analyse [--redo]       # re-run the Belfast analysis for all M/X flares
./venv/bin/python flare_logger.py global [--min-class M5] [--flare 202610101458] [--max 3] [--redo]
./venv/bin/python flare_logger.py plot [--flare ID]      # default: strongest analysed daytime flare
```
`backfill` uses the NOAA/NCEI GOES-19 science archive (`xrsf-l2-flsum_science` daily flare lists and
`xrsf-l2-avg1m_science` 1-minute flux), because the real-time flare list only covers 7 days. When the same flare is in
both, the science-archive version is kept.

## The analysis (per flare, per satellite)
1. **Window:** 30 min before the flare starts to 90 min after it starts (longer for long flares: end + 30 min).
2. Only GPS satellites **above 30° elevation** are used (lower ones have more multipath noise and longer paths).
3. Phase TEC is split into continuous arcs (new arc on the receiver's slip flag, a gap > 10 s, or a jump > 1 TECU in 1 s).
4. **Trend:** one parabola in time, plus a separate offset for each arc, is fitted by least squares to the data
   **outside the flare period** (flare start - 2 min to flare end + 15 min is left out). A satellite needs at least
   10 minutes of clean data both before and after the flare period, otherwise it is skipped.
5. **dTEC** = TEC minus that trend, averaged into 30-second bins. "Noise" = the standard deviation of dTEC outside the flare period.
6. A satellite **responded** if, inside the flare period, its peak dTEC **and** its rise above the level in the 8
   minutes before the flare are both at least max(3 x noise, 0.10 TECU). The rise test stops slow, older trends
   (e.g. travelling ionospheric disturbances on storm days) counting as flare responses.
7. A flare is **detected** at a station if at least 2 satellites, and at least half of the usable ones, responded.
8. **Control:** every analysis is repeated on the same clock times 24 hours earlier (kind = `control`). That
   gives a false-alarm rate: if controls "detect" as often as flares do, the detections aren't real.

Unit reminder: 1 TECU = 10^16 electrons per m^2, which adds about 16 cm of delay on GPS L1.

## Global stations (`global`)
`global_roti.db` stores only ROTI, not per-epoch TEC, so it can't be used directly. Instead, for each M/X flare
`global` re-downloads the 30-second RINEX file for that day from the Geoscience Australia archive for every
global_logger station that was sunlit at the flare peak. It converts it to phase TEC with the global_logger's own
code (`rinex.py`, `roti.py`), runs the same analysis (30-s data: new arc on loss-of-lock, gap > 45 s or jump > 5 TECU)
and deletes the file. Night-side stations are stored as `night` without downloading. GA files appear the day
after, so flares are only processed once they are 30 hours old. Each station-day takes roughly a minute on the Pi.

## Tables in flare.db
* `xray_flux(ts_utc, flux_short, flux_long, satellite, source)`: 1-minute flux, W/m^2. short = 0.05-0.4 nm, long = 0.1-0.8 nm.
* `flares(flare_id, begin_utc, peak_utc, end_utc, class, peak_flux, satellite, source, belfast_sza_deg, belfast_sunlit, updated_utc)`.
* `flare_response(flare_id, station, kind, sza_deg, sunlit, status, n_sats_used, n_sats_responded, peak_dtec,
  median_peak_dtec, mean_peak_dtec_all, time_to_peak_min, lag_after_xray_peak_min, noise_tecu, detected, message, updated_utc)`.
  station = `HOME` (Belfast) or a global_logger code; status = ok / waiting / no_data / night / error.
* `flare_response_sat`: the same for each satellite.
* `fetch_log`: every download and whether it worked.

## Limitations (worth putting in the report)
* The home receiver records GPS only, so above a 30° mask a 2-hour window usually has only 2-5 usable satellites.
* On storm days, travelling ionospheric disturbances can be as big as a flare response (0.1-0.5 TECU). The rise test
  and the 24-hour controls are there to catch this, but a few false or missed detections are still possible.
* Belfast is at 54.6 N, so the Sun is never high (SZA at least ~31° in June, ~58° at noon in mid-October). Flare
  effects are weaker at a high SZA, so a mid-latitude winter station expects small responses.
* The GOES flare list's start and end times come from NOAA's automatic algorithm; the EUV late phase that Bekker
  et al. studied can carry on after the listed "end", which is why the fit leaves out 15 extra minutes.
