from __future__ import annotations

import asyncpg


async def adjust_stock(
    conn: asyncpg.Connection, *, variant_id: int, quantity_change: int, reason: str, actor_id: int
) -> asyncpg.Record:
    """§9: manual ADJUST requires a reason and is always logged. Guarded
    UPDATE — the `stock_on_hand >= 0` CHECK is the final backstop, but this
    also fails cleanly with a clear error instead of a raw constraint
    violation when the adjustment would go negative."""
    if not reason or len(reason.strip()) == 0:
        raise ValueError("reason is required for a manual stock adjustment")

    row = await conn.fetchrow(
        """
        UPDATE product_variants
        SET stock_on_hand = stock_on_hand + $2, updated_at = now()
        WHERE id = $1 AND stock_on_hand + $2 >= stock_reserved
        RETURNING stock_on_hand, stock_reserved
        """,
        variant_id,
        quantity_change,
    )
    if row is None:
        raise ValueError("adjustment would take stock_on_hand below stock_reserved or negative")

    quantity_after = row["stock_on_hand"]
    quantity_before = quantity_after - quantity_change

    return await conn.fetchrow(
        """
        INSERT INTO inventory_movements
            (variant_id, movement_type, quantity_change, quantity_before, quantity_after, reason, actor_id)
        VALUES ($1, 'ADJUST', $2, $3, $4, $5, $6)
        RETURNING id, variant_id, quantity_change, quantity_before, quantity_after
        """,
        variant_id,
        quantity_change,
        quantity_before,
        quantity_after,
        reason,
        actor_id,
    )
