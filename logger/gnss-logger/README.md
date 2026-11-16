# GNSS / TEC Logger

The scientific centrepiece. Reads raw dual-frequency measurements from the
ZED-F9P (simpleRTK2B) and derives ionospheric **Total Electron Content (TEC)**
for each GPS satellite, into `gnss_tec.db`, UTC-aligned with the other loggers.

## The science, briefly

Ionospheric delay scales as 1/f², so receiving the same satellite on two
frequencies (GPS L1 and L2) and differencing isolates the ionosphere:

```
STEC [TECU]  ≈  9.52 × (P_L2 − P_L1)      (P = pseudorange, metres)
```

Two estimates are stored per satellite per epoch:

- **`code_tec`** — from pseudoranges. Absolute-ish but noisy (metre-level) and
  biased by hardware delays (DCBs). Good for magnitude.
- **`phase_tec`** — from carrier phase. Very smooth, but carries an unknown
  constant offset per continuous phase-lock arc. **This is the input for ROTI**
  (Rate of TEC Index) — the offset cancels when you differentiate, so it doesn't
  matter. `slip=1` marks the start of a new arc / a suspected cycle slip, so
  analysis knows where not to differentiate across.

Satellite **elevation** (from NAV-SAT) is stored too, so analysis can apply an
elevation mask (cut low-elevation multipath, typically <20–30°) and compute
ionospheric pierce points to match the sky sector your Starlink dish uses.

Only GPS L1 C/A + L2C pairs are logged (the F9P is a dual-band L1/L2 receiver).
Not every GPS satellite broadcasts L2C, so you'll see a subset each epoch.

## Requirements

```bash
~/starlink-venv/bin/pip install pyubx2 pyserial
```

## One-time: stop ModemManager grabbing the port

Linux ships **ModemManager**, which probes new serial devices as if they might be
dial-up modems — it will poke `/dev/ttyACM0` and corrupt the raw binary stream.
Since this Pi has no cellular modem, the clean fix is to disable it:

```bash
sudo systemctl disable --now ModemManager
```

<details>
<summary>Prefer to keep ModemManager? Use a udev rule instead</summary>

```bash
echo 'ATTRS{idVendor}=="1546", ATTRS{idProduct}=="01a9", ENV{ID_MM_DEVICE_IGNORE}="1"' \
  | sudo tee /etc/udev/rules.d/99-ublox.rules
sudo udevadm control --reload-rules && sudo udevadm trigger
```
(1546:01a9 is the u-blox GNSS receiver, from your `dmesg`.)
</details>

## Step 1 — configure + verify (run once)

```bash
~/starlink-venv/bin/python3 gnss_configure.py --port /dev/ttyACM0
```
This enables raw output (saved to flash) and listens ~15 s. Success looks like:
```
  sample: SV5  elev=40  code_TEC=28.ul TECU  (6 GPS L1/L2 pairs this epoch)
RXM-RAWX epochs received: 15
✅ Raw dual-frequency data confirmed. Ready to run the logger.
```
If it reports raw epochs but no pairs yet, give the antenna a few minutes of open
sky to acquire L2C, then retry.

## Step 2 — test-run the logger

```bash
~/starlink-venv/bin/python3 gnss_logger.py --port /dev/ttyACM0 \
  --db ./gnss_tec.db --verbose
```
You'll see one line per second: `epoch: N meas, M GPS L1/L2 pairs`. Ctrl-C, then
check the data:
```bash
sqlite3 -header -column ./gnss_tec.db \
  "SELECT ts_utc, sv, elev_deg, ROUND(code_tec,1) code, ROUND(phase_tec,1) phase, slip
   FROM tec ORDER BY id DESC LIMIT 10;"
```

## Step 3 — run as a service

```bash
# edit paths / user in the unit first
sudo cp gnss-logger.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now gnss-logger
journalctl -u gnss-logger -f
```

## Data

`tec` — one row per GPS satellite per epoch (~1 Hz):
`ts_utc` (system UTC, aligns with other loggers), `rcv_tow` (receiver time-of-week
in s — use this for precise Δt in ROT), `gps_week`, `sv`, `elev_deg`, `azim_deg`,
`code_tec`, `phase_tec`, `cno_l1`, `cno_l2`, `locktime_l2`, `slip`.

`epoch_log` — one row per epoch: `num_meas`, `num_pairs`, `status` (health/gaps).

## Next: ROTI

ROTI isn't computed here — it's a short analysis step over the stored `phase_tec`:
per satellite, along each continuous arc (between `slip=1` rows), compute
ROT = Δphase_tec / Δ(rcv_tow) in TECU/min, then take its standard deviation over
5-minute windows. That's the scintillation proxy you correlate against Starlink
and the space-weather indices. Ask and I'll write the ROTI analysis script once
you have a few hours of data.
