# A Single Point of Failure in the Sky

Space weather as a common-mode threat to satellite navigation and satellite broadband.

This repository holds the measurement and analysis code for Elijah Underwood's Sentinus Young Innovators project (entry YI0046; finals 26 November 2026, Ulster University, Belfast). The work uses a u-blox ZED-F9P Global Navigation Satellite System (GNSS) receiver on a simpleRTK2B board in Belfast, together with public space-weather and GNSS archives.

The published site location is **Belfast, approximately 54.6°N, 5.9°W**. Exact receiver coordinates are not included.

Private configuration was removed before publication: mailbox addresses, mail passwords, the email-command personal identification number (PIN), cloud-backup tokens, local network addresses and hostnames, and exact home coordinates. See `config.example.env` for the placeholders that a new deployment should set.

## What is measured, what is published, and what is argued

Keep these categories separate when you use or cite the work.

- **Measured** here: total electron content (TEC) and the rate of TEC index (ROTI) from the Belfast receiver; carrier-to-noise density and related GNSS observables; a timing-holdover log from the same receiver; local weather and nearby meteorological aerodrome reports (METAR); downloaded space-weather indices; flare-window extracts; and, where a low Earth orbit (LEO) broadband dish is present, dish throughput and delay statistics. The 10 October 2026 storm recorded at the home receiver is a measured case.
- **Published** (used, not collected by this project): planetary K index (Kp) from the Helmholtz Centre Potsdam GFZ and from the United States National Oceanic and Atmospheric Administration Space Weather Prediction Center (NOAA SWPC); disturbance storm time (Dst) from the Kyoto World Data Centre; Geostationary Operational Environmental Satellite (GOES) X-ray flares; International GNSS Service (IGS) Receiver Independent Exchange (RINEX) records via the Geoscience Australia archive; EMBRACE scintillation data from Brazil's National Institute for Space Research (INPE). A logistic fit of “disturbed” ROTI against Kp for the Belfast-latitude band gives a 50 per cent threshold of about **Kp 7.7**, with a bootstrap 95 per cent interval of about **7.4–8.0** (see `analysis/results/kp_threshold.json`).
- **Argued or illustrative**, not measured: cascade diagrams; how long a mobile-network mast's backup clock would hold time after GNSS timing is lost; any claim that 4G or 5G masts fail in a storm (no direct 5G study is cited, and no mast outage was measured). Timing-risk arguments should be labelled as such.

Kp is quasi-logarithmic. The ROTI cut-off of 0.5 TECU/min used as “disturbed” is a conventional threshold applied to these data, not a quantity measured from them.

## Repository layout

| Folder | What it contains |
| --- | --- |
| `logger/` | Software that runs on the measurement computer (a Raspberry Pi in this project): the GNSS / TEC logger, timing log, scintillation processing, space-weather logger, weather and METAR loggers, flare logger, optional LEO broadband dish logger, and the EMBRACE downloader. |
| `analysis/global_logger/` | Pipeline that downloads RINEX from a set of IGS-class stations, computes ROTI, and produces storm summaries and the Kp-threshold fit. |
| `analysis/storm_20261010/` | Scripts for the 10 October 2026 storm case. |
| `analysis/flare_storm/` | Solar-flare and geomagnetic-storm catalogue analysis, including overlap with ROTI. |
| `analysis/reanalysis/` | Reanalysis of the home receiver against weather, high-latitude stations and dish statistics. |
| `analysis/autonomy/` | Scripts linking measured ROTI to positioning tolerances of autonomous platforms, and flare-effect checks. |
| `analysis/archive_scripts/` | Earlier Pi-side export and combined-analysis helpers. |
| `analysis/results/` | Small published results, including `kp_threshold.json`. |
| `simulators/` | Five offline interactive demonstrations, plus a menu page. Open `simulators/index.html` in a browser; no internet connection is required. |
| `dashboard/` | Generator and simple web server for the live status page (reads the logger databases read-only). |
| `pi_setup/` | Example systemd units, crontab, database watchdog, Wi-Fi watchdog, backup scripts and email-command helpers, with secrets removed. |
| `data/sample/` | Tiny public or derived samples (Kp, Dst, a quiet-versus-storm hourly ROTI table, and the dashboard's typical-day ROTI profile). The full databases are not in this repository. |
| `config.example.env` | Placeholders for private settings. Copy to a gitignored `.env` or a systemd `EnvironmentFile`. |

On the measurement Pi the loggers were installed under the account's home directory with the original folder names (`gnss-logger`, `flare_logger`, and so on). The copies here keep those names inside `logger/` so that paths in the scripts stay recognisable. Adjust `YOUR_USER` in the example units before reuse.

## Data sources actually used in the code

- NOAA SWPC: near-real-time space weather, planetary K index, alerts, three-day forecast, and GOES X-ray flux (`services.swpc.noaa.gov`).
- NOAA National Centers for Environmental Information: GOES L2 X-ray archives (`data.ngdc.noaa.gov`).
- GFZ Potsdam: official Kp (`kp.gfz.de`).
- Kyoto World Data Centre: Dst (`wdc.kugi.kyoto-u.ac.jp`).
- Geoscience Australia GNSS Data Repository: RINEX for the global station set (`data.gnss.ga.gov.au`). This project does not download from the NASA Crustal Dynamics Data Information System (CDDIS) in the published code.
- Open-Meteo: local weather forecasts and historical weather (`api.open-meteo.com`).
- United States Aviation Weather Center: METAR (`aviationweather.gov`).
- EMBRACE / INPE: scintillation station files (`embracedata.inpe.br`).
- The home u-blox ZED-F9P / simpleRTK2B receiver in Belfast.

## How to run

**Simulators.** Open `simulators/index.html`. Keys 1–5 select a demo, F toggles full screen, and the arrow keys or `+`/`-` adjust the main control (including a USB knob in arrow-key mode).

**Python environment.** Python 3.10 or later is recommended. From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Global ROTI pipeline** (needs network access to the archives above):

```bash
cd analysis/global_logger
python -m global_logger daily --date 2024-05-11
python -m global_logger plot --storm may2024 --quiet quiet_may2024
```

See `analysis/global_logger/README.md` for the station list, processing settings and storm catalogue.

**Home GNSS logger** (hardware required): connect the ZED-F9P, then run `logger/gnss-logger/gnss_logger.py` as in `pi_setup/systemd/gnss-logger.service`. The other loggers follow the same pattern. Example units under `pi_setup/systemd/` use `User=YOUR_USER` and `/home/YOUR_USER/...`.

**Live dashboard.** `dashboard/generate.py` reads the logger SQLite databases read-only and writes `www/index.html`. `dashboard/server.py` serves that folder (the measurement Pi used port 8080). It will not do anything useful unless those databases exist.

**Analysis scripts.** Point `REPO_ROOT` (or accept the default, which walks up from the script) and, where needed, `SPACE_WEATHER_DATA` at a local data folder. The full storm databases and RINEX files are not included; `data/sample/` only illustrates the formats.

The LEO broadband logger imports `starlink_grpc` from the third-party [starlink-grpc-tools](https://github.com/sparky8512/starlink-grpc-tools) repository. That name is a code identifier. The dish address is not published; set `DISH_GRPC_HOST` if you run this logger.

The public repository is <https://github.com/elijahunderwood/single-point-of-failure-in-the-sky>.

## How to cite

Please cite this software. A `CITATION.cff` file is included. Once a frozen copy is archived on Zenodo, replace the placeholder digital object identifier (DOI) in that file and cite the DOI, for example:

> Underwood, E. (2026). *A Single Point of Failure in the Sky: Space weather as a common-mode threat to satellite navigation and satellite broadband* (Version 1.0.0). Zenodo. https://doi.org/10.5281/zenodo.XXXXXXXX

## Licence

The project code is released under the MIT Licence (see `LICENSE`). Third-party tools such as starlink-grpc-tools remain under their own licences. Public data archives remain under their own terms of use.
