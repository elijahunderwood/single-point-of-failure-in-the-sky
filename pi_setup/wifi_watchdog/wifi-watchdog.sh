#!/bin/bash
# Wi-Fi watchdog for the Raspberry Pi space-weather station (added 2026-10-17).
# Run every 5 min by wifi-watchdog.timer. Never reboots.
# Failure = no default route, or BOTH the gateway and 1.1.1.1 fail to answer ping.
#   >=3 consecutive failures (~15 min): nmcli con up YOUR_WIFI_CONNECTION (at most once per 10 min)
#   >=6 consecutive failures (~30 min): restart NetworkManager (at most once per 60 min)
# Options: DRY_RUN=1 (log actions without doing them), SIMULATE_FAIL=1 (pretend pings failed).
CON="YOUR_WIFI_CONNECTION"
IFACE="wlan0"
STATE_DIR=${STATE_DIR:-/var/lib/wifi-watchdog}
LOG=${LOG:-/var/log/wifi-watchdog.log}
UP_AFTER=3; NM_AFTER=6
UP_MIN_GAP=600; NM_MIN_GAP=3600
DRY_RUN=${DRY_RUN:-0}; SIMULATE_FAIL=${SIMULATE_FAIL:-0}
mkdir -p "$STATE_DIR"
now=$(date +%s)
log(){ echo "$(date '+%Y-%m-%d %H:%M:%S %Z') $*" >> "$LOG"; }
get(){ cat "$STATE_DIR/$1" 2>/dev/null || echo 0; }
put(){ echo "$2" > "$STATE_DIR/$1"; }
run(){ if [ "$DRY_RUN" = 1 ]; then log "DRY_RUN would run: $*"; else log "running: $*"; "$@" >> "$LOG" 2>&1; log "exit code $?"; fi; }

gw=$(ip -4 route show default dev "$IFACE" 2>/dev/null | awk '/default/{print $3; exit}')
ok=0
if [ "$SIMULATE_FAIL" != 1 ]; then
  if [ -n "$gw" ] && ping -c 3 -W 2 -I "$IFACE" "$gw" >/dev/null 2>&1; then ok=1
  elif ping -c 3 -W 3 -I "$IFACE" 1.1.1.1 >/dev/null 2>&1; then ok=1; fi
fi

fails=$(get fails)
if [ "$ok" = 1 ]; then
  [ "$fails" -gt 0 ] && log "OK again (gateway ${gw:-none}) after $fails failed check(s)"
  put fails 0
  [ "$DRY_RUN" = 1 ] && log "DRY_RUN check OK (gateway ${gw:-none})"
  exit 0
fi

fails=$((fails+1)); put fails "$fails"
log "FAIL $fails: no answer from gateway '${gw:-none}' or 1.1.1.1 (simulate=$SIMULATE_FAIL dry=$DRY_RUN)"

if [ "$fails" -ge "$NM_AFTER" ]; then
  last=$(get last_nm_restart)
  if [ $((now-last)) -ge "$NM_MIN_GAP" ]; then
    put last_nm_restart "$now"; run systemctl restart NetworkManager
  else log "NetworkManager restart rate-limited (last $(( (now-last)/60 )) min ago)"; fi
fi
if [ "$fails" -ge "$UP_AFTER" ]; then
  last=$(get last_con_up)
  if [ $((now-last)) -ge "$UP_MIN_GAP" ]; then
    put last_con_up "$now"; run nmcli radio wifi on; run nmcli con up "$CON"
  else log "nmcli con up rate-limited (last $(( (now-last)/60 )) min ago)"; fi
fi
exit 0
