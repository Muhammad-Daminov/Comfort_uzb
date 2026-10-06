#!/usr/bin/env bash
# COMFORT UZB — deterministic deploy procedure (§17.5).
#
#   git pull -> pip install -> alembic upgrade head -> build frontend
#            -> systemctl restart -> /health check
#
# Run as the `comfort` user (never root) from /opt/comfort. Requires
# MIGRATION_DATABASE_URL to be exported in the calling shell for the one
# migration step (comfort_migrate's DSN — never stored in the app's own
# running .env, see .env.example's note on this).
#
# This script has been written and reviewed but NOT executed against a
# real server — no VPS exists for this project yet (see the Phase 09
# report). It documents the exact, reviewable procedure so the first real
# deploy follows a script instead of ad-hoc commands.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/comfort}"
BACKEND_DIR="$APP_DIR/backend"
MINIAPP_DIR="$APP_DIR/miniapp"
WEB_ROOT="/var/comfort/web"

echo "==> [1/8] pulling latest code"
cd "$APP_DIR"
git pull --ff-only

echo "==> [2/8] installing backend dependencies"
cd "$BACKEND_DIR"
.venv/bin/pip install -q -r requirements.txt

echo "==> [3/8] pre-migration backup (safety net before any schema change)"
"$APP_DIR/deploy/scripts/backup.sh"

echo "==> [4/8] running migrations as comfort_migrate"
: "${MIGRATION_DATABASE_URL:?MIGRATION_DATABASE_URL must be set to the comfort_migrate DSN for this step only}"
# Migration 0002 seeds the single OWNER from this variable and refuses to
# run without it — on a first deploy that aborted the whole script here
# with a Python traceback. Fail early with a message instead. (Idempotent
# afterwards: the row already exists, the value is ignored.)
: "${OWNER_TELEGRAM_ID:?OWNER_TELEGRAM_ID must be exported (the OWNER Telegram user id, see .env.example) — migration 0002 needs it}"
DATABASE_URL="$MIGRATION_DATABASE_URL" .venv/bin/alembic upgrade head

echo "==> [5/8] building frontend"
cd "$MINIAPP_DIR"
npm ci
npm run build
mkdir -p "$WEB_ROOT"
rsync -a --delete dist/ "$WEB_ROOT/"

echo "==> [6/8] restarting services"
sudo systemctl restart comfort-api

echo "==> [7/8] verifying health"
sleep 2
for i in 1 2 3 4 5; do
    if curl -sf http://127.0.0.1:8001/health/ready > /dev/null; then
        echo "    /health/ready OK"
        break
    fi
    if [ "$i" -eq 5 ]; then
        echo "    /health/ready FAILED after 5 attempts — deploy did not verify cleanly, check 'journalctl -u comfort-api'" >&2
        exit 1
    fi
    sleep 2
done

echo "==> [8/8] deploy complete"
