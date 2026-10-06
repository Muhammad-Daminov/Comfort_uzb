"""Shared process entrypoint for the scheduled workers.

Both workers were written as importable `run_once(conn, ...)` coroutines
with no scheduling dependency (see each module's own docstring), which made
them unit-testable but also meant nothing could actually *start* them: a
systemd unit needs a command to run, and there was none. This module is
that command's body, kept in one place so `reservation_expiry` and
`receipt_purge` cannot drift apart in how they handle configuration,
logging, locking and exit codes.

Deliberately NOT wired into `app/main.py`'s lifespan. §15's workers are
separate scheduled processes (ADR-1 keeps *the bot* in the API process
because it shares the Service layer; a periodic batch job shares nothing
and would compete with request handling for the same event loop and pool).
Each run is a short-lived process started by its own systemd timer.

Contract this guarantees for every worker:

* **Idempotent** — `run_once` already promises a guarded no-op on re-entry;
  this wrapper never retries a partial batch in a way that could double-apply.
* **Non-overlapping** — a Postgres session-level advisory lock. systemd's
  `Type=oneshot` already refuses to run two instances of the same unit at
  once, but the lock also covers a manual run racing the timer, and a
  second host pointed at the same database. Failing to take the lock is a
  normal skip (exit 0), not an error.
* **Observable** — one structured JSON log line per outcome, and a non-zero
  exit code on failure so `systemctl` marks the unit failed and
  `journalctl -u <unit>` shows the traceback.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from typing import Awaitable, Callable

import asyncpg

from app.config import Settings
from app.observability import configure_logging

logger = logging.getLogger("comfort.worker")

# Stable, arbitrary keys — only needs to be unique per worker within this
# database. Never reuse a key for a different worker.
LOCK_KEY_RESERVATION_EXPIRY = 8801
LOCK_KEY_RECEIPT_PURGE = 8802

EXIT_OK = 0
EXIT_FAILED = 1


async def run_worker(
    name: str,
    lock_key: int,
    work: Callable[[asyncpg.Connection, Settings], Awaitable[int]],
) -> int:
    """Connect, take the advisory lock, run one batch, report. Returns the
    process exit code."""
    settings = Settings.from_env()
    try:
        conn = await asyncpg.connect(settings.database_url)
    except Exception:
        logger.exception("worker %s could not connect to the database", name)
        return EXIT_FAILED

    try:
        got_lock = await conn.fetchval("SELECT pg_try_advisory_lock($1)", lock_key)
        if not got_lock:
            # Previous run still going. Skipping is correct: the next timer
            # tick picks the work up, and forcing overlap is what would be
            # unsafe.
            logger.info(
                "worker %s skipped — another run holds the lock", name,
                extra={"worker": name, "outcome": "skipped_locked"},
            )
            return EXIT_OK

        try:
            processed = await work(conn, settings)
        except Exception:
            logger.exception(
                "worker %s failed", name, extra={"worker": name, "outcome": "failed"}
            )
            return EXIT_FAILED

        logger.info(
            "worker %s processed %d item(s)", name, processed,
            extra={"worker": name, "outcome": "ok", "processed": processed},
        )
        return EXIT_OK
    finally:
        # Session-level lock is released by the disconnect regardless, but
        # unlocking explicitly keeps the intent obvious.
        try:
            await conn.execute("SELECT pg_advisory_unlock($1)", lock_key)
        except Exception:  # pragma: no cover - best effort on a dying conn
            pass
        await conn.close()


def main(
    name: str,
    lock_key: int,
    work: Callable[[asyncpg.Connection, Settings], Awaitable[int]],
) -> None:
    """Console entrypoint: `python -m app.workers.<worker>`."""
    configure_logging()
    sys.exit(asyncio.run(run_worker(name, lock_key, work)))
