# Pi email alerts and remote control

You get two kinds of email from your Pi, and you can control the Pi by email. Everything is sent and received with your own Gmail account. The app password stays in `~/.msmtprc` and is never written anywhere else.

## 1. Storm alerts (`~/storm_alert/`)
- **When it runs:** `storm-alert.timer` runs `storm_alert.py` every 3 hours, at 00:10, 03:10, 06:10 … UK time.
- **What it checks:** three free NOAA Space Weather Prediction Center products:
  - the 3-day forecast (`3-day-forecast.txt`): any 3-hour block forecast at Kp ≥ 7 (G3 or stronger);
  - the alerts feed (`alerts.json`): a G3+ **watch** from the last 72 h, or a **warning/alert** of K-index ≥ 7 from the last 36 h;
  - observed planetary Kp (`noaa-planetary-k-index.json`): Kp ≥ 7 in the last 24 h.
- **The email:** subject `Storm ALERT: G3 …`, with:
  - every item found, with times in UK local time;
  - the source links;
  - the status of every logger (service running? how old is the newest record in each database?).
- **No repeats:** `state.json` remembers the level last emailed. You are only emailed again if the level goes **up** (e.g. G3 → G4), or if more than 72 h have passed (a new storm).
- **If NOAA is down:** it only writes a line to `storm_alert.log`. No email.
- **Test it:** `python3 ~/storm_alert/storm_alert.py --test` sends a clearly marked TEST email.

## 2. Watchdog (`~/db_watchdog.sh`, unchanged logic)
- Every 15 min. It emails when a logger stalls, recovers, or the disk gets low.
- The emails now end with the remote-control help footer.
- `bash ~/db_watchdog.sh --test` sends a TEST email.
- The previous version is backed up in `~/backups/pre_alerts_*/`.

## 3. Remote control by email (`~/mail_control/`)
`mail-control.timer` runs `mail_control.py` every 2 minutes. It logs into Gmail by IMAP and looks for **unread** messages whose subject is:

```
PI <PIN> <COMMAND>          e.g.   PI 123456 STATUS
```

Send it **from your Gmail to yourself** (phone or web). Your PIN is in `~/mail_control/pin` (only you can read it: `cat ~/mail_control/pin`). Never put the PIN in anything you forward. The Pi's replies never contain it.

| Command | What happens |
|---|---|
| `STATUS` | every logger service, newest record age per database, free disk, uptime, CPU temperature, global_logger status |
| `RESTART gnss` (or starlink, spaceweather, metar, weather, flare, all) | restarts only those systemd services, then sends status |
| `RUN GLOBAL` | starts the global_logger daily job now; a second email arrives when it finishes |
| `CHECK` | runs `db_watchdog.sh` and reports the current picture |
| `LOGS gnss` (or starlink, spaceweather, metar, weather, flare, watchdog, storm, control) | last 30 lines of that service's journal |
| `DISK` | free disk space (`df -h`) |
| `REBOOT` | replies first, then reboots |
| `HELP` | the command list |

### Why a stranger can't control your Pi
A command only runs if **all** of these are true:
1. The subject starts with `PI ` and the mail is unread.
2. The From address is exactly the MAIL_ADDRESS environment variable.
3. Gmail proves it really came from your account, in one of two ways:
   - Gmail's own server added `dkim=pass` for gmail.com (a cryptographic signature). Anyone can type your address into "From"; nobody else can make that signature.
   - Gmail labelled it **Sent**. Mail you send to yourself never goes through Gmail's incoming servers, so it carries no DKIM result. Instead Gmail files it under Sent, which can only happen if it was sent while logged in to your account.
4. The 6-digit PIN matches. It is compared in constant time, so its digits can't be guessed by timing.
5. The command is on the fixed list above. There is no way to run any other shell command.
6. No more than 10 commands have run in the past hour.

Each processed mail is marked as read, so it is never run twice. Every attempt, accepted or rejected, is written to `~/mail_control/commands.log` (the PIN is never logged). Rejected mail gets no reply.

### Changing the PIN
```
python3 -c "import secrets;print(f'{secrets.randbelow(10**6):06d}')" > ~/mail_control/pin && chmod 600 ~/mail_control/pin
```

### Useful checks
```
systemctl list-timers storm-alert.timer mail-control.timer db-watchdog.timer
journalctl -u mail-control -n 20        tail ~/mail_control/commands.log
journalctl -u storm-alert -n 20         tail ~/storm_alert/storm_alert.log
sudo systemctl disable --now mail-control.timer     # switch remote control off
```


## flare logger (added 17 Oct 2026)
`flare` = `flare-logger.service`, a oneshot run every 10 min by `flare-logger.timer`. `RESTART flare` runs one poll straight away; STATUS shows the timer state. See ~/flare_logger/README.md.
