from __future__ import annotations

from dataclasses import dataclass

import asyncpg


@dataclass(frozen=True)
class OrderLineInput:
    variant_id: int
    quantity: int
    product_name_snapshot: str
    variant_label_snapshot: str | None
    sku_snapshot: str
    unit_price: int
    discount_amount: int
    required_initial_payment: int
    cost_price_snapshot: int | None = None


async def create_order(
    conn: asyncpg.Connection, *, user_id: int, order_number: str, lines: list[OrderLineInput]
) -> asyncpg.Record:
    total_amount = sum(line.unit_price * line.quantity - line.discount_amount for line in lines)
    required_initial_amount = sum(line.required_initial_payment * line.quantity for line in lines)

    order = await conn.fetchrow(
        """
        INSERT INTO orders (order_number, user_id, status, total_amount, required_initial_amount,
                             paid_amount, remaining_amount)
        VALUES ($1, $2, 'CREATED', $3, $4, 0, $3)
        RETURNING id, order_number, user_id, status, total_amount, required_initial_amount,
                  paid_amount, remaining_amount, created_at
        """,
        order_number,
        user_id,
        total_amount,
        required_initial_amount,
    )

    for line in lines:
        line_total = line.unit_price * line.quantity - line.discount_amount
        await conn.execute(
            """
            INSERT INTO order_items
                (order_id, variant_id, product_name_snapshot, variant_label_snapshot, sku_snapshot,
                 unit_price, discount_amount, quantity, required_initial_payment, line_total,
                 cost_price_snapshot)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            """,
            order["id"],
            line.variant_id,
            line.product_name_snapshot,
            line.variant_label_snapshot,
            line.sku_snapshot,
            line.unit_price,
            line.discount_amount,
            line.quantity,
            line.required_initial_payment,
            line_total,
            line.cost_price_snapshot,
        )

    return order


async def get_order(conn: asyncpg.Connection, *, order_id: int) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        SELECT id, order_number, user_id, status, total_amount, required_initial_amount,
               paid_amount, remaining_amount, cancellation_reason, confirmed_at, confirmed_by,
               cancelled_at, cancelled_by, created_at, updated_at
        FROM orders WHERE id = $1
        """,
        order_id,
    )


async def get_order_by_number(conn: asyncpg.Connection, *, order_number: str) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        SELECT id, order_number, user_id, status, total_amount, required_initial_amount,
               paid_amount, remaining_amount, cancellation_reason, confirmed_at, confirmed_by,
               cancelled_at, cancelled_by, created_at, updated_at
        FROM orders WHERE order_number = $1
        """,
        order_number,
    )


async def get_order_for_update(conn: asyncpg.Connection, *, order_id: int) -> asyncpg.Record | None:
    """§8.2's `SELECT ... FOR UPDATE` row lock — must be called inside an
    open transaction on `conn`. Includes `paid_amount` for ADR-017's
    cancel_order guard (an order with an approved payment cannot go through
    the direct cancel path) without a second round-trip. Includes `user_id`/
    `order_number` so callers that notify the order's owner on this same
    transition (app/notifications.py) don't need a second lookup."""
    return await conn.fetchrow(
        "SELECT id, user_id, order_number, status, paid_amount FROM orders WHERE id = $1 FOR UPDATE", order_id
    )


async def get_order_items(conn: asyncpg.Connection, *, order_id: int) -> list[asyncpg.Record]:
    return await conn.fetch(
        "SELECT id, order_id, variant_id, quantity, unit_price, discount_amount, line_total "
        "FROM order_items WHERE order_id = $1 ORDER BY id",
        order_id,
    )


async def list_orders_for_user(conn: asyncpg.Connection, *, user_id: int, limit: int = 20) -> list[asyncpg.Record]:
    # §P1-2: the order-history screen needs product/quantity and payment
    # status per row, which the plain `orders` columns don't carry — no new
    # endpoint needed, this existing one just needs a richer SELECT.
    # `items` is pre-aggregated server-side (json_agg over a correlated
    # subquery) rather than N+1 queries per order or joining and
    # deduplicating in Python.
    return await conn.fetch(
        """
        SELECT o.id, o.order_number, o.status, o.total_amount, o.paid_amount, o.remaining_amount,
               o.created_at,
               (SELECT p.status FROM payments p WHERE p.order_id = o.id ORDER BY p.submitted_at DESC LIMIT 1)
                   AS latest_payment_status,
               (
                   SELECT json_agg(json_build_object(
                       'product_name', oi.product_name_snapshot,
                       'quantity', oi.quantity
                   ) ORDER BY oi.id)
                   FROM order_items oi WHERE oi.order_id = o.id
               ) AS items
        FROM orders o
        WHERE o.user_id = $1
        ORDER BY o.created_at DESC
        LIMIT $2
        """,
        user_id,
        limit,
    )


async def list_all_orders(conn: asyncpg.Connection, *, status: str | None = None, limit: int = 20) -> list[asyncpg.Record]:
    if status is not None:
        return await conn.fetch(
            "SELECT id, order_number, user_id, status, total_amount, paid_amount, remaining_amount, created_at "
            "FROM orders WHERE status = $1 ORDER BY created_at DESC LIMIT $2",
            status,
            limit,
        )
    return await conn.fetch(
        "SELECT id, order_number, user_id, status, total_amount, paid_amount, remaining_amount, created_at "
        "FROM orders ORDER BY created_at DESC LIMIT $1",
        limit,
    )


async def transition_status(
    conn: asyncpg.Connection,
    *,
    order_id: int,
    from_statuses: list[str],
    to_status: str,
    extra_set_sql: str = "",
    extra_params: list | None = None,
) -> asyncpg.Record | None:
    """Guarded transition: UPDATE only succeeds if the row's *current*
    status is one of `from_statuses` (§8.1: 'Ruxsat etilgan o'tishlar kodda
    aniq jadval' — the allowed-transitions table lives in code, this
    function is that guard). Call after `get_order_for_update` has already
    taken the row lock within the same transaction for the concurrency-
    sensitive paths (confirm); simple paths (cancel from CREATED) don't need
    the extra lock since a single guarded UPDATE is already atomic."""
    params: list = [order_id, to_status, from_statuses]
    set_clause = "status = $2" + (f", {extra_set_sql}" if extra_set_sql else "")
    if extra_params:
        params.extend(extra_params)
    return await conn.fetchrow(
        f"""
        UPDATE orders
        SET {set_clause}, updated_at = now()
        WHERE id = $1 AND status = ANY($3)
        RETURNING id, status
        """,
        *params,
    )
