#!/usr/bin/env bash
# COMFORT UZB — comfort-health worker (§17.6: "Disk 80%+ -> comfort-health
# worker -> OWNER ga Telegram"). Fully owned by devops per AGENTS/devops.md
# ("comfort-backup and comfort-health are fully owned by this agent, logic
# included, authored in Phase-09") — infra/ops logic, not application
# business logic, deliberately a standalone script rather than anything
# inside app/ or bot/.
set -euo pipefail

THRESHOLD="${DISK_ALERT_THRESHOLD_PERCENT:-80}"
CHECK_PATH="${DISK_CHECK_PATH:-/var/comfort}"

USAGE_PERCENT=$(df --output=pcent "$CHECK_PATH" | tail -1 | tr -dc '0-9')

if [ -z "$USAGE_PERCENT" ]; then
    echo "comfort-health: could not read disk usage for '$CHECK_PATH'" >&2
    exit 1
fi

echo "comfort-health: $CHECK_PATH is at ${USAGE_PERCENT}% (threshold ${THRESHOLD}%)"

if [ "$USAGE_PERCENT" -lt "$THRESHOLD" ]; then
    exit 0
fi

if [ -z "${BOT_TOKEN:-}" ] || [ -z "${OWNER_TELEGRAM_ID:-}" ]; then
    echo "comfort-health: disk usage is above threshold but BOT_TOKEN/OWNER_TELEGRAM_ID are not set — cannot alert" >&2
    exit 1
fi

MESSAGE="⚠️ COMFORT UZB: disk usage at ${USAGE_PERCENT}% on ${CHECK_PATH} (threshold ${THRESHOLD}%)"

# Plain Telegram Bot API HTTP call — no aiogram/Python dependency needed
# for a single fire-and-forget message, keeps this an infra script with
# zero application-code coupling.
curl -sf -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
    -d "chat_id=${OWNER_TELEGRAM_ID}" \
    --data-urlencode "text=${MESSAGE}" \
    > /dev/null

echo "comfort-health: alert sent to OWNER"
