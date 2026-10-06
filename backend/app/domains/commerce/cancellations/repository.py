"""ADR-017: post-confirmation cancellation requests. Raw asyncpg (ADR-015)."""
from __future__ import annotations

import asyncpg


async def create_request(
    conn: asyncpg.Connection, *, order_id: int, requested_by: int, reason: str
) -> asyncpg.Record:
    return await conn.fetchrow(
        """
        INSERT INTO cancellation_requests (order_id, requested_by, reason)
        VALUES ($1, $2, $3)
        RETURNING id, order_id, requested_by, reason, status, created_at
        """,
        order_id,
        requested_by,
        reason,
    )


async def get_pending_for_order(conn: asyncpg.Connection, *, order_id: int) -> asyncpg.Record | None:
    return await conn.fetchrow(
        "SELECT * FROM cancellation_requests WHERE order_id = $1 AND status = 'PENDING'",
        order_id,
    )


async def get_request_for_update(conn: asyncpg.Connection, *, request_id: int) -> asyncpg.Record | None:
    return await conn.fetchrow(
        "SELECT * FROM cancellation_requests WHERE id = $1 FOR UPDATE",
        request_id,
    )


async def decide(
    conn: asyncpg.Connection,
    *,
    request_id: int,
    approve: bool,
    decided_by: int,
    decision_note: str | None,
) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        UPDATE cancellation_requests
        SET status = $2, decided_by = $3, decision_note = $4, decided_at = now()
        WHERE id = $1 AND status = 'PENDING'
        RETURNING id, order_id, requested_by, reason, status, decided_by, decision_note, decided_at, created_at
        """,
        request_id,
        "APPROVED" if approve else "DENIED",
        decided_by,
        decision_note,
    )


async def list_for_order(conn: asyncpg.Connection, *, order_id: int) -> list[asyncpg.Record]:
    return await conn.fetch(
        "SELECT * FROM cancellation_requests WHERE order_id = $1 ORDER BY created_at DESC",
        order_id,
    )


async def list_pending(conn: asyncpg.Connection, *, limit: int = 50) -> list[asyncpg.Record]:
    return await conn.fetch(
        "SELECT * FROM cancellation_requests WHERE status = 'PENDING' ORDER BY created_at ASC LIMIT $1",
        limit,
    )


async def restore_stock_for_order(
    conn: asyncpg.Connection, *, order_id: int, actor_id: int
) -> None:
    """Restock every line item of a CONFIRMED order being cancelled. There is
    no open reservation left to release (confirm_order consumed it) — this is
    a fresh IN movement, mirroring the OUT movement confirm_order recorded."""
    items = await conn.fetch(
        "SELECT variant_id, quantity FROM order_items WHERE order_id = $1",
        order_id,
    )
    for item in items:
        row = await conn.fetchrow(
            """
            UPDATE product_variants
            SET stock_on_hand = stock_on_hand + $2, updated_at = now()
            WHERE id = $1
            RETURNING stock_on_hand
            """,
            item["variant_id"],
            item["quantity"],
        )
        quantity_after = row["stock_on_hand"]
        quantity_before = quantity_after - item["quantity"]
        await conn.execute(
            """
            INSERT INTO inventory_movements
                (variant_id, movement_type, quantity_change, quantity_before, quantity_after,
                 reason, reference_type, reference_id, actor_id)
            VALUES ($1, 'IN', $2, $3, $4, 'order cancellation restock', 'order', $5, $6)
            """,
            item["variant_id"],
            item["quantity"],
            quantity_before,
            quantity_after,
            order_id,
            actor_id,
        )
