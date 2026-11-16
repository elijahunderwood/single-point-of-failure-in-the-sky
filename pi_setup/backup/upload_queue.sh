#!/bin/bash
# Upload queue for the nightly backup (added 2026-11-01 for a slow, unreliable
# home internet link). Every pending file in ~/backups/YYYY-MM-DD[-full]/ is
# uploaded to Google Drive on its own, smallest first, with its own time limit.
# A file is deleted locally only after rclone has uploaded and verified it, so
# whatever is still in those folders is exactly what still needs uploading and
# is retried on the next run. Large files follow small ones within the budget;
# a throttled API probe must not permanently starve weekly full backups.
# Exit codes: 0 = nothing left to upload, 1 = some files still pending, 2 = another upload is running.
# DRY=1 only prints the queue.
set -u
WORK_ROOT=~/backups
REMOTE_ROOT="${RCLONE_REMOTE:-gdrive:YOUR_BACKUP_FOLDER}"
LOG="$WORK_ROOT/backup.log"
ALERT_TO="${ALERT_EMAIL:?Set ALERT_EMAIL to the address that should receive alerts}"
BUDGET=${BUDGET:-12600}                 # total seconds per run (3.5 h)
BIG=104857600                           # 100 MB
RCLONE_FLAGS=(--transfers 1 --checkers 1 --drive-chunk-size 8M --contimeout 20s --timeout 120s --retries 3 --retries-sleep 15s --low-level-retries 10 --tpslimit 1 --tpslimit-burst 1 --drive-pacer-min-sleep 1s --drive-pacer-burst 1 --checksum --immutable --stats 60s --stats-one-line)
log() { echo "[$(date -u +%FT%TZ)] $*" >> "$LOG"; }

queue() {
  find "$WORK_ROOT" -mindepth 2 -maxdepth 2 -type f \
    -regex '.*/20[0-9][0-9]-[0-9][0-9]-[0-9][0-9]\(-full\)?/[^/]*\.\(gz\|sql\|db\)' \
    -printf '%s\t%p\n' | sort -n
}

if [ "${DRY:-0}" = "1" ]; then queue; exit 0; fi

exec 9>"$WORK_ROOT/.upload.lock"
flock -n 9 || { log "upload queue: another upload is already running"; exit 2; }

mapfile -t Q < <(queue)
drive_ok() { [ ! -f "$WORK_ROOT/.last_ok" ] || cp "$WORK_ROOT/.last_ok" "$WORK_ROOT/.last_drive_ok"; }
if [ ${#Q[@]} -eq 0 ]; then drive_ok; log "upload queue: empty"; exit 0; fi

log "upload queue: ${#Q[@]} file(s) pending; API backoff enabled, no speed-test gating"

start=$SECONDS; ok=0; failed=0; deferred=0
for line in "${Q[@]}"; do
  size=${line%%$'\t'*}; f=${line#*$'\t'}
  dir=$(basename "$(dirname "$f")"); name=$(basename "$f")
  left=$((BUDGET-(SECONDS-start)))
  if [ $left -lt 120 ]; then deferred=$((deferred+1)); continue; fi
  to=$((300 + size/10000)); [ $to -gt 14400 ] && to=14400; [ $to -gt $left ] && to=$left
  t0=$SECONDS
  success=0
  for attempt in 1 2 3; do
    left=$((BUDGET-(SECONDS-start)))
    [ $left -ge 120 ] || break
    [ $to -le $left ] || to=$left
    # Retry whole command: old rclone does not retry Drive initialisation 403s.
    if timeout --kill-after=30 "$to" rclone copyto "$f" "$REMOTE_ROOT/$dir/$name" "${RCLONE_FLAGS[@]}" >> "$LOG" 2>&1 \
       && timeout --kill-after=10 180 rclone check "$(dirname "$f")" "$REMOTE_ROOT/$dir" --one-way --include "/$name" "${RCLONE_FLAGS[@]}" >> "$LOG" 2>&1; then
      success=1; break
    fi
    log "  attempt $attempt failed (local file retained): $dir/$name"
    [ $attempt = 3 ] || sleep $((attempt*30))
  done
  if [ $success = 1 ]; then
    rm -f "$f"; ok=$((ok+1)); failed=0
    log "  uploaded and checksum verified: $dir/$name ($((size/1048576)) MB, $((SECONDS-t0))s)"
  else
    failed=$((failed+1)); log "  upload/verification failed (will retry next run): $dir/$name"
    [ $failed -lt 3 ] || break
  fi
done
find "$WORK_ROOT" -mindepth 1 -maxdepth 1 -type d -regex '.*/20[0-9][0-9]-[0-9][0-9]-[0-9][0-9]\(-full\)?' -empty -delete 2>/dev/null

mapfile -t P < <(queue)
if [ ${#P[@]} -eq 0 ]; then drive_ok; log "upload queue: all uploaded ($ok file(s))"; exit 0; fi

# warn only when the backlog is getting old (3+ days), so a slow night is not noisy
oldest=$(ls -d "$WORK_ROOT"/20[0-9][0-9]-[0-9][0-9]-[0-9][0-9]* 2>/dev/null | head -1 | xargs -r basename | cut -c1-10)
age=0; [ -n "$oldest" ] && age=$(( ( $(date -u +%s) - $(date -u -d "$oldest" +%s) ) / 86400 ))
log "upload queue: ${#P[@]} file(s) still pending (oldest folder $oldest, ${age} days); uploaded $ok this run"
if [ $age -ge 3 ] && [ "${NO_ALERT:-0}" != 1 ]; then
  printf "Subject: Pi backup backlog (%s days)\n\n%s backup file(s) are still waiting to upload to Google Drive; the oldest is from %s.\nThey are safe on the Pi in %s. The internet link is probably too slow.\nSee the end of %s.\n" "$age" "${#P[@]}" "$oldest" "$WORK_ROOT" "$LOG" | msmtp "$ALERT_TO" >> "$LOG" 2>&1 || true
fi
exit 1
