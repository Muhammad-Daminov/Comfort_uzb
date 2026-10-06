#!/usr/bin/env bash
# COMFORT UZB — restore a pg_dump backup into a database. Used both for a
# real disaster recovery and for the mandatory monthly restore drill
# (§17.3: "Sinovdan o'tmagan backup — backup emas" — an untested backup is
# not a backup).
#
# Deliberately restores into a NEW, separate database name, never directly
# over the live one — a restore drill must never touch production data,
# and even a real disaster recovery is safer as "stand up a fresh target,
# verify it, then cut over" than "overwrite in place and hope."
#
# Usage: ./restore.sh <path-to-db-dump.sql.gz> <target-database-name>
set -euo pipefail

DUMP_FILE="${1:?Usage: restore.sh <dump.sql.gz> <target-database-name>}"
TARGET_DB="${2:?Usage: restore.sh <dump.sql.gz> <target-database-name>}"
PGHOST="${DATABASE_HOST:-/var/run/postgresql}"
PGSUPERUSER="${PGSUPERUSER:-postgres}"

if [ ! -f "$DUMP_FILE" ]; then
    echo "restore.sh: dump file '$DUMP_FILE' not found" >&2
    exit 1
fi

echo "restore.sh: creating target database '$TARGET_DB'..."
createdb -h "$PGHOST" -U "$PGSUPERUSER" "$TARGET_DB"

echo "restore.sh: restoring '$DUMP_FILE' into '$TARGET_DB'..."
gunzip -c "$DUMP_FILE" | psql -h "$PGHOST" -U "$PGSUPERUSER" -d "$TARGET_DB" -v ON_ERROR_STOP=1 -q

echo "restore.sh: verifying row counts on a few core tables..."
psql -h "$PGHOST" -U "$PGSUPERUSER" -d "$TARGET_DB" -c "
    SELECT 'users' AS table_name, count(*) FROM users
    UNION ALL SELECT 'products', count(*) FROM products
    UNION ALL SELECT 'orders', count(*) FROM orders
    UNION ALL SELECT 'audit_logs', count(*) FROM audit_logs;
"

echo "restore.sh: done. '$TARGET_DB' is a standalone verification target —"
echo "drop it once you've confirmed the restore is good:"
echo "    dropdb -h $PGHOST -U $PGSUPERUSER $TARGET_DB"
