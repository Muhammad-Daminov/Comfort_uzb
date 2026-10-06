"""Reservation create/release primitives (ADR-6, §9). Every stock mutation
here uses an atomic guarded UPDATE (never SELECT-then-UPDATE from Python) so
concurrent callers serialize correctly at the row level — Postgres MVCC
plus the `WHERE` guard is what makes "last unit, two buyers" resolve to
exactly one winner without an explicit application-level lock.
"""
from __future__ import annotations

from datetime import timedelta

import asyncpg

RESERVATION_TTL = timedelta(hours=24)


class InsufficientStock(Exception):
    pass


async def reserve_stock(
    conn: asyncpg.Connection, *, order_id: int, variant_id: int, quantity: int, actor_id: int | None
) -> int:
    """Atomically increments `stock_reserved` only if enough is available,
    creates the `stock_reservations` row, and logs the RESERVE movement.
    Raises InsufficientStock if the guarded UPDATE affects zero rows —
    someone else took the remaining stock first. Returns the reservation id.
    Caller is responsible for the surrounding transaction."""
    row = await conn.fetchrow(
        """
        UPDATE product_variants
        SET stock_reserved = stock_reserved + $2, updated_at = now()
        WHERE id = $1 AND stock_on_hand - stock_reserved >= $2
        RETURNING stock_on_hand, stock_reserved
        """,
        variant_id,
        quantity,
    )
    if row is None:
        raise InsufficientStock(f"variant {variant_id} does not have {quantity} available")

    quantity_after = row["stock_reserved"]
    quantity_before = quantity_after - quantity

    reservation = await conn.fetchrow(
        """
        INSERT INTO stock_reservations (order_id, variant_id, quantity, expires_at)
        VALUES ($1, $2, $3, now() + $4)
        RETURNING id
        """,
        order_id,
        variant_id,
        quantity,
        RESERVATION_TTL,
    )

    await conn.execute(
        """
        INSERT INTO inventory_movements
            (variant_id, movement_type, quantity_change, quantity_before, quantity_after,
             reference_type, reference_id, actor_id)
        VALUES ($1, 'RESERVE', $2, $3, $4, 'order', $5, $6)
        """,
        variant_id,
        quantity,
        quantity_before,
        quantity_after,
        order_id,
        actor_id,
    )

    return reservation["id"]


async def release_reservation(
    conn: asyncpg.Connection, *, reservation_id: int, actor_id: int | None
) -> bool:
    """The mandatory guarded release pattern (AGENTS/backend-commerce.md,
    Phase 02 acceptance audit finding). Returns True if this call actually
    released the reservation, False if it was already released (a no-op —
    the caller must NOT decrement stock in that case)."""
    released = await conn.fetchrow(
        """
        UPDATE stock_reservations
        SET released_at = now()
        WHERE id = $1 AND released_at IS NULL
        RETURNING variant_id, quantity
        """,
        reservation_id,
    )
    if released is None:
        return False

    variant_id = released["variant_id"]
    quantity = released["quantity"]

    row = await conn.fetchrow(
        """
        UPDATE product_variants
        SET stock_reserved = stock_reserved - $2, updated_at = now()
        WHERE id = $1
        RETURNING stock_on_hand, stock_reserved
        """,
        variant_id,
        quantity,
    )
    quantity_after = row["stock_reserved"]
    quantity_before = quantity_after + quantity

    await conn.execute(
        """
        INSERT INTO inventory_movements
            (variant_id, movement_type, quantity_change, quantity_before, quantity_after,
             reference_type, reference_id, actor_id)
        VALUES ($1, 'RELEASE', $2, $3, $4, 'stock_reservation', $5, $6)
        """,
        variant_id,
        -quantity,
        quantity_before,
        quantity_after,
        reservation_id,
        actor_id,
    )
    return True


async def consume_reservations_for_order(conn: asyncpg.Connection, *, order_id: int) -> int:
    """Order confirm: the reserved units have just been deducted from
    `stock_on_hand` AND `stock_reserved` in one statement (§8.2), so the
    reservation rows are closed *without* touching stock again — a release
    here would decrement `stock_reserved` twice. Guarded on `released_at IS
    NULL` so it is a no-op on replay. Returns the number of rows closed."""
    result = await conn.execute(
        "UPDATE stock_reservations SET released_at = now() WHERE order_id = $1 AND released_at IS NULL",
        order_id,
    )
    return int(result.split()[-1])


async def get_active_reservations_for_order(conn: asyncpg.Connection, *, order_id: int) -> list[asyncpg.Record]:
    return await conn.fetch(
        "SELECT id, variant_id, quantity FROM stock_reservations WHERE order_id = $1 AND released_at IS NULL",
        order_id,
    )


async def get_expired_reservations(conn: asyncpg.Connection, *, limit: int = 100) -> list[asyncpg.Record]:
    # A CONFIRMED order's stock has already left `stock_on_hand`; releasing
    # its reservation would decrement `stock_reserved` a second time.
    # `consume_reservations_for_order` closes those rows at confirm time, so
    # this join is a backstop for rows confirmed before that existed.
    return await conn.fetch(
        """
        SELECT r.id, r.order_id, r.variant_id, r.quantity
        FROM stock_reservations r
        JOIN orders o ON o.id = r.order_id
        WHERE r.released_at IS NULL AND r.expires_at < now() AND o.status <> 'CONFIRMED'
        ORDER BY r.expires_at
        LIMIT $1
        """,
        limit,
    )
