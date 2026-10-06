#!/usr/bin/env bash
# COMFORT UZB — one-time host provisioning for the production filesystem
# layout (§17, systemd units in deploy/systemd/).
#
# Fills a gap identified during Phase 09.5 verification: deploy.sh and every
# unit in deploy/systemd/ assume /opt/comfort, /etc/comfort, /var/comfort/*
# and a `comfort` OS user already exist, but nothing in the repo ever
# created them. This script does exactly that and nothing else — it never
# touches application code, never writes .env/backend.env contents, never
# creates secrets, and never overwrites an existing environment file.
#
# Run once as root (or via sudo), on a real VPS during initial server setup
# or against a local machine for a Phase 09.5-style production simulation:
#   sudo bash deploy/scripts/bootstrap.sh
#
# Idempotent: safe to re-run. Every step checks current state before acting.
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "bootstrap.sh: must be run as root (sudo bash deploy/scripts/bootstrap.sh)" >&2
    exit 1
fi

APP_DIR="/opt/comfort"
ENV_DIR="/etc/comfort"
DATA_ROOT="/var/comfort"
UPLOADS_DIR="$DATA_ROOT/uploads"
WEB_DIR="$DATA_ROOT/web"
BACKUP_DIR="$DATA_ROOT/backup"

echo "==> [1/5] comfort system user/group"
if id comfort >/dev/null 2>&1; then
    echo "    comfort user already exists — skipping"
else
    useradd --system --home-dir "$APP_DIR" --create-home --shell /usr/sbin/nologin comfort
    echo "    created system user 'comfort'"
fi

echo "==> [2/5] application directory ($APP_DIR)"
mkdir -p "$APP_DIR"
chown comfort:comfort "$APP_DIR"

echo "==> [3/5] data directories ($DATA_ROOT)"
mkdir -p "$UPLOADS_DIR" "$WEB_DIR" "$BACKUP_DIR"
chown -R comfort:comfort "$DATA_ROOT"
# ADR-14: uploads and the built Mini App are written by `comfort` and READ
# by Nginx (`www-data`) — group ownership is what lets Nginx serve them.
# With comfort:comfort + 0750 (the previous setting) every request to `/`
# and every correctly-signed `/files/...` URL was a 403.
chown comfort:www-data "$UPLOADS_DIR" "$WEB_DIR"
chmod 750 "$UPLOADS_DIR" "$WEB_DIR" "$BACKUP_DIR"
chmod g+s "$UPLOADS_DIR"   # new subdirectories inherit the www-data group

echo "==> [4/5] environment directory ($ENV_DIR)"
mkdir -p "$ENV_DIR"
chown root:root "$ENV_DIR"
chmod 700 "$ENV_DIR"
# Never create or overwrite the env file itself — that's operator-owned
# (real secrets, filled in by hand or by a secrets manager, never by this
# script). Only warn if it's missing so the gap is visible before
# comfort-api.service is started.
if [ -f "$ENV_DIR/backend.env" ]; then
    echo "    $ENV_DIR/backend.env already exists — left untouched"
else
    echo "    $ENV_DIR/backend.env does not exist yet — create it before starting comfort-api.service"
fi

echo "==> [5/5] systemd units"
# Installing the units was the missing link: every unit file in
# deploy/systemd/ existed, but nothing ever copied them to
# /etc/systemd/system or enabled them, so following the documented
# procedure end to end still left comfort-api stopped and every timer
# (backup, health, reservation-expiry, receipt-purge) unscheduled. Found
# by the final hardening pass.
UNIT_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/../systemd" && pwd)"
install -m 0644 "$UNIT_SRC"/*.service "$UNIT_SRC"/*.timer /etc/systemd/system/
systemctl daemon-reload

# Timers are enabled+started here; comfort-api is only ENABLED, never
# started, because it would crash-loop until the operator has written
# /etc/comfort/backend.env (see step [4/5] — this script deliberately
# never creates that file).
systemctl enable comfort-api.service
for timer in "$UNIT_SRC"/*.timer; do
    unit="$(basename "$timer")"
    systemctl enable --now "$unit"
    echo "    enabled $unit"
done

echo "==> done"
echo "    $(id comfort)"
ls -la "$DATA_ROOT"
echo "    timers:"
systemctl list-timers --all 'comfort-*' --no-pager || true
echo
echo "    Next: write $ENV_DIR/backend.env, then: systemctl start comfort-api"
