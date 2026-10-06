#!/usr/bin/env bash
# COMFORT UZB — daily backup (§17.3). Run by systemd (comfort-backup.timer,
# daily 03:00) or manually before a risky deploy.
#
# Three things happen: a logical pg_dump (comfort_backup role — read-only,
# §12.2), a tar of the uploads directory, and (only if configured) an
# off-server copy via rclone. Local retention is 7 days — off-server
# retention is whatever the remote (e.g. Cloudflare R2) is configured to
# keep, not this script's concern.
#
# flock prevents two overlapping runs (a slow backup plus a manually
# triggered one) from corrupting each other's output — same discipline
# AGENTS/devops.md requires for every worker.
set -euo pipefail

BACKUP_ROOT="${BACKUP_ROOT:-/var/comfort/backup}"
UPLOADS_DIR="${UPLOADS_ROOT:-/var/comfort/uploads}"
LOCK_FILE="/run/lock/comfort-backup.lock"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-7}"

exec 200>"$LOCK_FILE"
flock -n 200 || { echo "comfort-backup: another run is already in progress, exiting" >&2; exit 1; }

mkdir -p "$BACKUP_ROOT"
DATE="$(date +%F)"

if [ -z "${DATABASE_NAME:-}" ]; then
    echo "comfort-backup: DATABASE_NAME is not set — refusing to guess which database to dump" >&2
    exit 1
fi

echo "comfort-backup: dumping database '$DATABASE_NAME' as comfort_backup..."
PGPASSWORD="${COMFORT_BACKUP_PASSWORD:-}" pg_dump \
    -U comfort_backup \
    -h "${DATABASE_HOST:-/var/run/postgresql}" \
    "$DATABASE_NAME" \
    | gzip > "$BACKUP_ROOT/db-$DATE.sql.gz"

echo "comfort-backup: archiving uploads directory..."
if [ -d "$UPLOADS_DIR" ]; then
    tar czf "$BACKUP_ROOT/files-$DATE.tar.gz" -C "$(dirname "$UPLOADS_DIR")" "$(basename "$UPLOADS_DIR")"
else
    echo "comfort-backup: WARNING — uploads directory '$UPLOADS_DIR' does not exist, skipping files archive" >&2
fi

if [ -n "${RCLONE_REMOTE:-}" ]; then
    echo "comfort-backup: copying to off-server remote '$RCLONE_REMOTE'..."
    rclone copy "$BACKUP_ROOT/" "$RCLONE_REMOTE"
else
    echo "comfort-backup: RCLONE_REMOTE not set — skipping off-server copy (local-only backup, §17.3's Layer 1 is NOT satisfied without an off-server copy; set RCLONE_REMOTE once R2/equivalent is provisioned)"
fi

echo "comfort-backup: pruning local backups older than $RETENTION_DAYS days..."
find "$BACKUP_ROOT" -mtime "+$RETENTION_DAYS" -name '*.gz' -delete

echo "comfort-backup: done — $BACKUP_ROOT/db-$DATE.sql.gz"
