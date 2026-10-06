"""`comfort-reservation-expiry` business logic (ADR-6, §15, REQ-WRK-001).
Callable directly — no systemd/timer dependency — so it's unit-testable on
its own; `devops` wires this into a systemd timer in Phase-09 (Open
Decision 5).

Runs every 5 minutes in production (§15): releases reservations past their
TTL and moves the corresponding order to EXPIRED. Uses the same mandatory
guarded-release pattern as user/admin cancellation — no exceptions.
"""
from __future__ import annotations

import logging

import asyncpg

from app.domains.commerce.orders import repository as orders_repository
from app.domains.commerce.orders.state_machine import ALLOWED_TRANSITIONS
from app.domains.commerce.reservations import repository as reservations_repository
from app.security.audit import record_audit

logger = logging.getLogger("comfort.worker")


async def run_once(conn: asyncpg.Connection, *, batch_size: int = 100) -> int:
    """Processes up to `batch_size` expired reservations in one call.
    Returns the number actually released (0 if none were due, or if a
    concurrent process already released them all — this call is always
    safe to re-invoke, per the guarded-release no-op contract).

    Each reservation is its own transaction and its own failure domain: a
    row that cannot be released (constraint violation, audit failure) is
    logged and skipped, so it cannot block the rows queued behind it — the
    query orders by `expires_at`, so one poison row at the head would
    otherwise starve every later expiry on every run."""
    expired = await reservations_repository.get_expired_reservations(conn, limit=batch_size)
    released_count = 0

    for reservation in expired:
        try:
            if await _release_one(conn, reservation):
                released_count += 1
        except Exception:  # noqa: BLE001 — isolate the row, keep the batch going
            logger.exception(
                "reservation %s (order %s) could not be released — skipped",
                reservation["id"], reservation["order_id"],
            )

    return released_count


async def _release_one(conn: asyncpg.Connection, reservation: asyncpg.Record) -> bool:
    async with conn.transaction():
        released = await reservations_repository.release_reservation(
            conn, reservation_id=reservation["id"], actor_id=None
        )
        if not released:
            # Already released by a concurrent worker run or a user/
            # admin cancellation that raced this one — no-op, per the
            # mandatory guarded pattern.
            return False

        order = await orders_repository.get_order_for_update(conn, order_id=reservation["order_id"])
        if order is not None and "EXPIRED" in ALLOWED_TRANSITIONS.get(order["status"], set()):
            await orders_repository.transition_status(
                conn, order_id=order["id"], from_statuses=[order["status"]], to_status="EXPIRED"
            )
            await record_audit(
                conn,
                actor_id=None,
                actor_role="SYSTEM",
                action="order.expire",
                entity_type="order",
                entity_id=order["id"],
                old_data={"status": order["status"]},
                new_data={"status": "EXPIRED"},
                metadata={"reservation_id": reservation["id"], "worker": "comfort-reservation-expiry"},
            )
        return True


async def _work(conn: asyncpg.Connection, settings) -> int:
    return await run_once(conn)


def main() -> None:
    """`python -m app.workers.reservation_expiry` — the command
    `comfort-reservation-expiry.service` runs, every 5 minutes (§15)."""
    from app.workers._entrypoint import LOCK_KEY_RESERVATION_EXPIRY, main as _main

    _main("comfort-reservation-expiry", LOCK_KEY_RESERVATION_EXPIRY, _work)


if __name__ == "__main__":
    main()
