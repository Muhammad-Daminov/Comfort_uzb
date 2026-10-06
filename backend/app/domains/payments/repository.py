from __future__ import annotations

from datetime import timedelta

import asyncpg

RECEIPT_RETENTION = timedelta(days=30)  # ADR-9: upload + 30 days, minimum retention


async def create_payment(conn: asyncpg.Connection, *, order_id: int, amount: int) -> asyncpg.Record:
    return await conn.fetchrow(
        """
        INSERT INTO payments (order_id, amount, method, status)
        VALUES ($1, $2, 'CARD_TRANSFER', 'PENDING')
        RETURNING id, order_id, amount, method, status, submitted_at
        """,
        order_id,
        amount,
    )


async def list_payments(conn: asyncpg.Connection, *, status: str | None = None, limit: int = 20) -> list[asyncpg.Record]:
    """Phase 06 addition — the P0 Admin Payments screen has no way to see
    what's pending without this; Phase 03 only ever built single-payment
    lookups (review/receipt by id)."""
    if status is not None:
        return await conn.fetch(
            "SELECT id, order_id, amount, method, status, submitted_at, reviewed_at "
            "FROM payments WHERE status = $1 ORDER BY submitted_at DESC LIMIT $2",
            status,
            limit,
        )
    return await conn.fetch(
        "SELECT id, order_id, amount, method, status, submitted_at, reviewed_at "
        "FROM payments ORDER BY submitted_at DESC LIMIT $1",
        limit,
    )


async def get_pending_payment_for_order(conn: asyncpg.Connection, *, order_id: int) -> asyncpg.Record | None:
    return await conn.fetchrow(
        "SELECT id, order_id, amount, method, status, submitted_at "
        "FROM payments WHERE order_id = $1 AND status = 'PENDING' ORDER BY submitted_at DESC LIMIT 1",
        order_id,
    )


async def get_payment(conn: asyncpg.Connection, *, payment_id: int) -> asyncpg.Record | None:
    return await conn.fetchrow(
        "SELECT id, order_id, amount, method, status, submitted_at, reviewed_at, reviewed_by, rejection_reason "
        "FROM payments WHERE id = $1",
        payment_id,
    )


async def create_receipt(
    conn: asyncpg.Connection, *, payment_id: int, storage_path: str
) -> asyncpg.Record:
    return await conn.fetchrow(
        """
        INSERT INTO payment_receipts (payment_id, storage_path, visibility_status, retention_until)
        VALUES ($1, $2, 'VISIBLE', now() + $3)
        RETURNING id, payment_id, storage_path, visibility_status, retention_until
        """,
        payment_id,
        storage_path,
        RECEIPT_RETENTION,
    )


async def get_receipt_for_payment(conn: asyncpg.Connection, *, payment_id: int) -> asyncpg.Record | None:
    return await conn.fetchrow(
        "SELECT id, payment_id, storage_path, visibility_status, hidden_at, retention_until, "
        "file_purged_at, reviewed_at, review_result "
        "FROM payment_receipts WHERE payment_id = $1 ORDER BY created_at DESC LIMIT 1",
        payment_id,
    )


async def review_payment(
    conn: asyncpg.Connection, *, payment_id: int, actor_id: int, approve: bool, rejection_reason: str | None
) -> asyncpg.Record | None:
    """REQ-BIZ-008: an APPROVED payment never reverts to PENDING — enforced
    here by the guarded `WHERE status = 'PENDING'` (matches the reasoning in
    migration 0009_payments' design notes: application-enforced one-way
    transition, not a DB trigger)."""
    new_status = "APPROVED" if approve else "REJECTED"
    return await conn.fetchrow(
        """
        UPDATE payments
        SET status = $2, reviewed_at = now(), reviewed_by = $3, rejection_reason = $4
        WHERE id = $1 AND status = 'PENDING'
        RETURNING id, order_id, amount, method, status
        """,
        payment_id,
        new_status,
        actor_id,
        rejection_reason,
    )


async def mark_receipt_reviewed(conn: asyncpg.Connection, *, payment_id: int, approve: bool) -> None:
    await conn.execute(
        """
        UPDATE payment_receipts
        SET reviewed_at = now(), review_result = $2
        WHERE payment_id = $1 AND reviewed_at IS NULL
        """,
        payment_id,
        "APPROVED" if approve else "REJECTED",
    )


async def get_receipts_due_for_purge(conn: asyncpg.Connection, *, limit: int = 100) -> list[asyncpg.Record]:
    """Backs `comfort-receipt-purge` (ADR-9). Uses the partial index on
    (retention_until) WHERE file_purged_at IS NULL created alongside this
    table in migration 0009_payments — built for exactly this query."""
    return await conn.fetch(
        "SELECT id, storage_path FROM payment_receipts "
        "WHERE retention_until < now() AND file_purged_at IS NULL "
        "ORDER BY retention_until LIMIT $1",
        limit,
    )


async def mark_receipt_purged(conn: asyncpg.Connection, *, receipt_id: int) -> bool:
    """Guarded like every other one-way state stamp in this codebase — a
    second, concurrent purge run for the same row is a safe no-op, not a
    double-delete attempt."""
    row = await conn.fetchrow(
        "UPDATE payment_receipts SET file_purged_at = now() WHERE id = $1 AND file_purged_at IS NULL RETURNING id",
        receipt_id,
    )
    return row is not None
