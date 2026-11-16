#!/bin/bash
# Nightly backup v2: hybrid full/incremental to Google Drive via rclone.
#
#   Small DBs  -> full gzipped snapshot every night (cheap).
#   Big DBs    -> full gzipped snapshot on Sunday (folder YYYY-MM-DD-full);
#                 other nights, a gzipped SQL dump of rows added since the
#                 last successful LOCAL dump (marker file), so a failed night
#                 just widens the next dump -- no rows are ever skipped.
#   Remote pruning is disabled: existing Drive backups are retained.
#
# Restore: take the newest -full folder (gunzip each *.db.gz), then replay
# each later daily folder's *.sql.gz into the matching DB in date order
# (zcat file.sql.gz | sqlite3 db). For the big GNSS dumps wrap it in one
# transaction or it is very slow:
#   ( echo "BEGIN;"; zcat gnss_tec.sql.gz; echo "COMMIT;" ) | sqlite3 gnss_tec.db
# Dumps overlap slightly with the previous
# run on purpose; the overlapping rows just fail with "UNIQUE constraint"
# errors on replay, which are harmless.
#
# v3 (2026-10-18): full snapshots use "VACUUM INTO" (one consistent read
# snapshot; the old ".backup" restarted every time the logger wrote, so the
# 6.7 GB GNSS DB never finished), output is checked with PRAGMA quick_check,
# and the marker records the run START time so no rows fall in a gap between
# the snapshot and the end of the upload.

set -u
# Serialise complete runs; queued files must never be overwritten.
exec 8>"$HOME/backups/.backup.lock"
flock -n 8 || exit 2
if [ "${UPLOAD_ONLY:-0}" = 1 ]; then
  exec "$HOME/pi-backup/upload_queue.sh"
fi
WORK_ROOT=~/backups            # point at the USB SSD later, e.g. /mnt/ssd/backups
REMOTE_ROOT="${RCLONE_REMOTE:-gdrive:YOUR_BACKUP_FOLDER}"
KEEP_DAILY=14
KEEP_FULL=3                    # each full is ~1.8 GB and growing; Drive quota is 15 GB
RCLONE_FLAGS=(--transfers 1 --drive-chunk-size 128M --timeout 300s --retries 4 --tpslimit 2 --drive-pacer-min-sleep 200ms)
UPLOAD_TIMEOUT=5400            # seconds; a hung upload fails instead of blocking the night (weekly full gets longer, below)
ALERT_TO="${ALERT_EMAIL:?Set ALERT_EMAIL to the address that should receive alerts}"
STAMP=$(date -u +%Y-%m-%d)
DOW=$(date -u +%u)                       # 1=Mon .. 7=Sun
MARKER="$WORK_ROOT/.last_ok"
RUN_START=$(date -u +%Y-%m-%dT%H:%M)    # written to MARKER on success
LOG="$WORK_ROOT/backup.log"
FULL=0
[ "$DOW" = "7" ] && FULL=1
[ "${FORCE_FULL:-0}" = "1" ] && FULL=1

if [ $FULL = 1 ]; then FOLDER="$STAMP-full"; else FOLDER="$STAMP"; fi
WORK="$WORK_ROOT/$FOLDER"
REMOTE="$REMOTE_ROOT/$FOLDER"
if [ -d "$WORK" ] && [ -n "$(ls -A "$WORK")" ]; then
  "$HOME/pi-backup/upload_queue.sh" || exit 1
  [ ! -d "$WORK" ] || [ -z "$(ls -A "$WORK")" ] || exit 1
fi
mkdir -p "$WORK"

SINCE="1970-01-01T00:00"
if [ -f "$MARKER" ]; then SINCE=$(cat "$MARKER"); fi

echo "[$(date -u +%FT%TZ)] backup v3 starting -> $REMOTE (full=$FULL since=$SINCE)" >> "$LOG"

fail=0

snap_full() {  # $1 db path, $2 out name
  if [ -f "$1" ]; then
    local out="$WORK/$2" t0=$SECONDS chk
    rm -f "$out" "$out.gz"
    # VACUUM INTO reads from a single snapshot (WAL lets the loggers keep
    # writing meanwhile) and writes a compact, self-contained copy.
    if nice -n 10 sqlite3 "$1" "VACUUM INTO '$out'" \
       && chk=$(nice -n 10 sqlite3 "$out" "PRAGMA quick_check;") && [ "$chk" = "ok" ] \
       && nice -n 10 gzip -f "$out"; then
      echo "  full ok: $2 ($(du -h "$out.gz" | cut -f1), $((SECONDS-t0))s)" >> "$LOG"
    else echo "  FULL FAILED: $2 (check=${chk:-n/a})" >> "$LOG"; rm -f "$out" "$out.gz"; fail=1; fi
  else echo "  missing: $1" >> "$LOG"; fi
}

dump_day() {  # $1 db path, $2 out prefix, remaining args: tables (with ts_utc col)
  local db="$1" name="$2"; shift 2
  [ -f "$db" ] || { echo "  missing: $db" >> "$LOG"; return; }
  local out="$WORK/$name.sql"
  : > "$out"
  local t
  for t in "$@"; do
    sqlite3 "$db" ".mode insert $t" \
      "SELECT * FROM $t WHERE ts_utc >= '$SINCE';" >> "$out" \
      || { echo "  DUMP FAILED: $name.$t" >> "$LOG"; fail=1; }
  done
  gzip -f "$out" && echo "  dump ok: $name ($(du -h "$out.gz" | cut -f1))" >> "$LOG" || { fail=1; echo "  COMPRESSION FAILED: $name" >> "$LOG"; }
}

# --- small DBs: full every night ---
snap_full ~/spaceweather-logger/spaceweather.db  spaceweather.db
snap_full ~/weather-logger/localweather.db       localweather.db
snap_full ~/weather-logger/metar.db              metar.db

# --- big DBs: weekly full, otherwise day-dump ---
if [ $FULL = 1 ]; then
  snap_full ~/gnss-logger/gnss_tec.db              gnss_tec.db
  snap_full ~/starlink-logger/starlink_history.db  starlink_history.db
  snap_full ~/gnss-scint/scint.db                 scint.db             # 20 Hz S4/sigma-phi (2026-10-22)
else
  dump_day ~/gnss-logger/gnss_tec.db             gnss_tec        tec epoch_log
  dump_day ~/starlink-logger/starlink_history.db starlink_history history status_snapshot
  dump_day ~/gnss-scint/scint.db                 scint           scint processed_files
fi

# --- upload (queued, per file; see upload_queue.sh) ---
# The marker moves forward as soon as the local dumps are safely written, because
# anything not yet uploaded stays queued in $WORK_ROOT and is retried every night.
[ $fail = 0 ] && echo "$RUN_START" > "$MARKER"
"$HOME/pi-backup/upload_queue.sh"; qrc=$?
if [ $qrc != 0 ]; then echo "[$(date -u +%FT%TZ)] upload queue not empty (code $qrc); retries next run" >> "$LOG"; fi

# Remote pruning disabled: retain existing Drive backups; no remote deletions.

# --- tell Elijah if anything failed ---
if [ $fail != 0 ]; then
  printf "Subject: Pi backup FAILED %s\n\nThe nightly backup (%s) did not complete (a local dump or snapshot failed). Local copy kept in %s.\nSee the end of %s.\nThe next night re-covers the gap automatically.\n" "$STAMP" "$FOLDER" "$WORK" "$LOG" | msmtp "$ALERT_TO" >> "$LOG" 2>&1 || true
fi
[ $fail = 0 ] && [ ${qrc:-1} != 0 ] && fail=1
exit $fail
