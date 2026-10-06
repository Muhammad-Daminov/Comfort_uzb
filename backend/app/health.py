"""Liveness/readiness endpoints (Phase 09 — §17.7 go-live checklist item
"/health tekshirish", and the deploy flow's own final step, §17.5).

Two separate endpoints, not one, because they answer different questions
an operator (or systemd/Nginx/an external uptime pinger) needs answered
separately:

- `/health/live`  — is the process itself running and able to answer HTTP
  at all? Never touches the database. This is what a process supervisor
  should restart on, not what an uptime pinger should page on (a DB blip
  shouldn't trigger a systemd restart of a perfectly healthy process).
- `/health/ready` — is the process able to actually serve real requests
  right now? §13.4 literally asks for "DB + disk + worker holati" (DB +
  disk + worker status) on one check — folded into this endpoint rather
  than a third one, since all three answer the same "can this deployment
  actually be trusted right now" question an uptime monitor/load balancer
  needs.
  - **disk**: `shutil.disk_usage` on `UPLOADS_ROOT` (the same volume
    `deploy/scripts/health.sh`'s existing disk-alert worker already
    watches, same `DISK_ALERT_THRESHOLD_PERCENT` default of 80 — one
    threshold convention, not two). Degraded (still 200, not 503 — a full
    disk doesn't mean the API can't serve reads) when at/over threshold.
  - **worker**: no worker-run-tracking table exists (adding one is a
    migration — out of this fix's scope), so this infers staleness from
    data the reservation-expiry worker (§15, every 5 minutes) is supposed
    to already be acting on: any `stock_reservations` row still unreleased
    15+ minutes past its own `expires_at` (3x the worker's own interval —
    generous enough that one slow cycle isn't a false alarm) means that
    worker has not run successfully recently. A real, if indirect, signal
    — not a fabricated "always ok".

Neither endpoint exposes configuration, secrets, or any internal detail —
only a fixed-shape, mostly-boolean status body.
"""
from __future__ import annotations

import os
import shutil

import asyncpg
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.config import Settings
from app.db.pool import get_pool

router = APIRouter(tags=["health"])

DEFAULT_DISK_ALERT_THRESHOLD_PERCENT = 80
# 3x the worker's own 5-minute interval (§15) — generous enough that one
# slow/delayed cycle is never mistaken for the worker not running at all.
WORKER_STALE_AFTER_MINUTES = 15


@router.get("/health/live")
async def liveness() -> dict:
    return {"status": "ok"}


def _disk_status() -> dict:
    settings = Settings.from_env()
    threshold = int(os.environ.get("DISK_ALERT_THRESHOLD_PERCENT", DEFAULT_DISK_ALERT_THRESHOLD_PERCENT))
    try:
        usage = shutil.disk_usage(settings.uploads_root)
    except OSError:
        # UPLOADS_ROOT doesn't exist yet (fresh install before first
        # upload) — not a readiness failure, just unmeasurable.
        return {"status": "unknown"}

    percent_used = round((usage.used / usage.total) * 100, 1) if usage.total else 0.0
    return {
        "status": "critical" if percent_used >= threshold else "ok",
        "percent_used": percent_used,
    }


async def _worker_status(conn: asyncpg.Connection) -> dict:
    stale_count = await conn.fetchval(
        """
        SELECT count(*) FROM stock_reservations r
        JOIN orders o ON o.id = r.order_id
        WHERE r.released_at IS NULL
          AND r.expires_at < now() - interval '1 minute' * $1
          AND o.status <> 'CONFIRMED'
        """,
        WORKER_STALE_AFTER_MINUTES,
    )
    return {"status": "stale" if stale_count else "ok", "reservation_expiry_backlog": stale_count}


@router.get("/health/ready")
async def readiness() -> dict:
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
            worker = await _worker_status(conn)
    except (RuntimeError, asyncpg.PostgresError, OSError):
        # RuntimeError: pool not initialized yet (starting up).
        # PostgresError/OSError: DB unreachable right now.
        # Deliberately narrow — an unexpected bug here should still 500
        # through the normal global exception handler, not be silently
        # reported as "database not ready."
        return JSONResponse(status_code=503, content={"status": "not_ready", "database": "unreachable"})

    return {"status": "ok", "database": "ok", "disk": _disk_status(), "worker": worker}
