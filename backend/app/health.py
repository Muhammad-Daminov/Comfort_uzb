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
  right now (DB reachable)? This is what an external uptime monitor
  (§17.6 — healthchecks.io) and a load balancer's health check should use.

Neither endpoint exposes configuration, secrets, or any internal detail —
only a fixed-shape boolean-ish status body.
"""
from __future__ import annotations

import asyncpg
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.db.pool import get_pool

router = APIRouter(tags=["health"])


@router.get("/health/live")
async def liveness() -> dict:
    return {"status": "ok"}


@router.get("/health/ready")
async def readiness() -> dict:
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
    except (RuntimeError, asyncpg.PostgresError, OSError):
        # RuntimeError: pool not initialized yet (starting up).
        # PostgresError/OSError: DB unreachable right now.
        # Deliberately narrow — an unexpected bug here should still 500
        # through the normal global exception handler, not be silently
        # reported as "database not ready."
        return JSONResponse(status_code=503, content={"status": "not_ready", "database": "unreachable"})
    return {"status": "ok", "database": "ok"}
