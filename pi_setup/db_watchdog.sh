#!/bin/bash
ALERT="${ALERT_EMAIL:?Set ALERT_EMAIL to the address that should receive alerts}"
STATE="/home/YOUR_USER/.watchdog_state"
mkdir -p "$STATE"
now=$(date +%s)
msg=""
# --test: send one clearly-marked TEST email to show the format/footer
[ "$1" = "--test" ] && msg+="TEST: this is a test watchdog email - nothing is wrong.\\n"

# check newest RECORD inside the db (reads WAL), not file mtime
check () {  # name  db  "sql"  max_age_seconds
  local name="$1" db="$2" sql="$3" max="$4"
  local flag="$STATE/$name.down"
  local ts rec age
  ts=$(sqlite3 "$db" "$sql" 2>/dev/null)
  if [ -z "$ts" ]; then rec=0; else rec=$(date -d "$ts" +%s 2>/dev/null || echo 0); fi
  age=$(( now - rec ))
  if [ "$rec" -eq 0 ] || [ "$age" -gt "$max" ]; then
    [ ! -f "$flag" ] && { msg+="STALLED: $name — newest record $((age/60)) min old (limit $((max/60)))\n"; touch "$flag"; }
  else
    [ -f "$flag" ] && { msg+="RECOVERED: $name — fresh data again\n"; rm -f "$flag"; }
  fi
}

# GNSS/Starlink are high-rate; the three feeds update ~15-60 min, so generous limits
check gnss         ~/gnss-logger/gnss_tec.db            "SELECT MAX(ts_utc) FROM tec;"               1200
check starlink     ~/starlink-logger/starlink_history.db "SELECT MAX(ts_utc) FROM history;"           1800
check spaceweather ~/spaceweather-logger/spaceweather.db "SELECT MAX(ts_utc) FROM solar_wind_mag;"    3600
check metar        ~/weather-logger/metar.db            "SELECT MAX(ts_utc) FROM metar;"              7200
check weather      ~/weather-logger/localweather.db     "SELECT MAX(ts_utc) FROM weather_current;"    3600
# global logger runs once a day (07:45), so allow 30 h before alerting
check global_logger ~/global_logger/data/global_roti.db "SELECT MAX(updated_utc) FROM station_days WHERE status='ok';" 108000
# flare logger polls NOAA GOES X-rays every 10 min; the 1-min feed lags a few minutes, so allow 1 h
check flare        ~/flare_logger/flare.db              "SELECT MAX(ts_utc) FROM xray_flux;"         3600
# 20 Hz scintillation (added 2026-10-22): processed hourly at HH:08, so allow 3 h
check scint        ~/gnss-scint/scint.db                "SELECT MAX(ts_utc) FROM scint;"             10800
# 20 Hz raw UBX tee written by gnss_logger.py: some raw_*.ubx must have grown in the last 10 min
rflag="$STATE/gnss_raw.down"
if [ -n "$(find ~/gnss_raw -path ~/gnss_raw/keep -prune -o -name 'raw_*.ubx' -mmin -10 -print -quit 2>/dev/null)" ]; then
  [ -f "$rflag" ] && { msg+="RECOVERED: gnss_raw - 20 Hz raw files growing again\n"; rm -f "$rflag"; }
else
  [ ! -f "$rflag" ] && { msg+="STALLED: gnss_raw - no new 20 Hz raw bytes in 10 min (~/gnss_raw)\n"; touch "$rflag"; }
fi

# nightly Drive backup (pi-backup.timer 03:30): .last_drive_ok holds the UTC start
# time of the last fully successful run; alert if older than 36 h (one missed night)
bflag="$STATE/backup.down"
bts=$(cat ~/backups/.last_drive_ok 2>/dev/null)
brec=0; [ -n "$bts" ] && brec=$(date -d "${bts}Z" +%s 2>/dev/null || echo 0)
bage=$(( now - brec ))
if [ "$brec" -eq 0 ] || [ "$bage" -gt 129600 ]; then
  [ ! -f "$bflag" ] && { msg+="BACKUP STALE: last successful Drive backup $((bage/3600)) h ago (${bts:-never}) — see ~/backups/backup.log\n"; touch "$bflag"; }
else
  [ -f "$bflag" ] && { msg+="RECOVERED: Drive backup succeeded again (${bts})\n"; rm -f "$bflag"; }
fi

freeG=$(df --output=avail -BG / | tail -1 | tr -dc '0-9')
dflag="$STATE/disk.down"
if [ "$freeG" -lt 10 ]; then
  [ ! -f "$dflag" ] && { msg+="LOW DISK: only ${freeG} GB free on /\n"; touch "$dflag"; }
else
  [ -f "$dflag" ] && { msg+="RECOVERED: disk space OK (${freeG} GB)\n"; rm -f "$dflag"; }
fi

if [ -n "$msg" ]; then
  footer=$(python3 -c "import sys,os; sys.path.insert(0, os.path.expanduser('~/mail_control')); import pilib; print(pilib.FOOTER)" 2>/dev/null)
  subj="Pi logger ALERT"; [ "$1" = "--test" ] && subj="TEST - Pi logger ALERT (test only)"
  printf "Subject: %s\n\n%b\nChecked: $(date)\n\n%s\n" "$subj" "$msg" "$footer" | msmtp "$ALERT"
fi
