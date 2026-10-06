"""ADR-017: refunds are independent of orders.status/cancellation_requests.status."""
from __future__ import annotations

import asyncpg


async def create_refund(
    conn: asyncpg.Connection,
    *,
    order_id: int,
    payment_id: int | None,
    amount: int,
    method: str,
    reason: str,
    created_by: int,
) -> asyncpg.Record:
    return await conn.fetchrow(
        """
        INSERT INTO refunds (order_id, payment_id, amount, method, reason, created_by)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING *
        """,
        order_id,
        payment_id,
        amount,
        method,
        reason,
        created_by,
    )


async def get_refund_for_update(conn: asyncpg.Connection, *, refund_id: int) -> asyncpg.Record | None:
    return await conn.fetchrow("SELECT * FROM refunds WHERE id = $1 FOR UPDATE", refund_id)


async def mark_status(
    conn: asyncpg.Connection,
    *,
    refund_id: int,
    status: str,
    completed_by: int | None,
    provider_reference: str | None,
) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        UPDATE refunds
        SET status = $2,
            completed_by = CASE WHEN $2 = 'COMPLETED' THEN $3 ELSE completed_by END,
            completed_at = CASE WHEN $2 = 'COMPLETED' THEN now() ELSE completed_at END,
            provider_reference = COALESCE($4, provider_reference),
            updated_at = now()
        WHERE id = $1 AND status = 'PENDING'
        RETURNING *
        """,
        refund_id,
        status,
        completed_by,
        provider_reference,
    )


async def list_for_order(conn: asyncpg.Connection, *, order_id: int) -> list[asyncpg.Record]:
    return await conn.fetch("SELECT * FROM refunds WHERE order_id = $1 ORDER BY created_at DESC", order_id)


async def total_paid_for_order(conn: asyncpg.Connection, *, order_id: int) -> int:
    row = await conn.fetchrow(
        "SELECT id, paid_amount FROM orders WHERE id = $1",
        order_id,
    )
    return row["paid_amount"] if row else 0


async def total_refunded_for_order(conn: asyncpg.Connection, *, order_id: int) -> int:
    row = await conn.fetchrow(
        "SELECT COALESCE(SUM(amount), 0) AS total FROM refunds WHERE order_id = $1 AND status = 'COMPLETED'",
        order_id,
    )
    return row["total"]
