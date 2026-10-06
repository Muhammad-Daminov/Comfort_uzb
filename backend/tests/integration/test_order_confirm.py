"""§8.2/§12.6: two admins confirming the same order concurrently — exactly
one must succeed, the other gets a clear error, never a silent
double-decrement. Uses two real, separate asyncpg connections racing via
asyncio.gather, not a simulated/sequential stand-in.
"""
from __future__ import annotations

import asyncio

import pytest

from app.domains.commerce.orders import repository as orders_repository
from app.domains.commerce.orders import service as orders_service
from app.domains.commerce.orders.state_machine import InvalidTransition
from tests.integration import factories

pytestmark = pytest.mark.asyncio


async def _setup_under_review_order(conn, *, stock: int = 5, qty: int = 2):
    user_id = await factories.make_user(conn)
    admin_a_id = await factories.make_user(conn, role="ADMIN")
    admin_b_id = await factories.make_user(conn, role="ADMIN")
    brand_id = await factories.make_brand(conn, name="ConfirmTestBrand")
    product_id = await factories.make_product(conn, brand_id=brand_id, name="Confirm Test Product")
    variant_id = await factories.make_variant(
        conn, product_id=product_id, sku="CONFIRM-SKU-1", price=100_000, stock_on_hand=stock
    )

    order = await orders_service.create_order(
        conn, user_id=user_id, lines=[orders_service.CheckoutLine(variant_id=variant_id, quantity=qty)]
    )
    await conn.execute("UPDATE orders SET status = 'UNDER_REVIEW' WHERE id = $1", order["id"])
    return order["id"], variant_id, admin_a_id, admin_b_id, stock, qty


async def test_parallel_confirm_exactly_one_succeeds(pool, clean_slate):
    async with pool.acquire() as setup_conn:
        order_id, variant_id, admin_a_id, admin_b_id, stock, qty = await _setup_under_review_order(setup_conn)

    async def attempt(admin_id: int):
        async with pool.acquire() as conn:
            try:
                await orders_service.confirm_order(conn, order_id=order_id, actor_id=admin_id, actor_role="ADMIN")
                return "success"
            except (orders_service.ConcurrentConfirmation, InvalidTransition):
                # Two valid shapes for the loser, both correct per §8.2: the
                # `FOR UPDATE` lock usually means the second admin's blocked
                # SELECT observes the already-CONFIRMED row the instant it
                # gets the lock (-> InvalidTransition, caught before the
                # guarded UPDATE is even attempted); ConcurrentConfirmation
                # is the theoretical case where the guarded UPDATE itself is
                # what loses the race. Either way, the second admin never
                # succeeds and never double-decrements stock.
                return "already_confirmed"

    results = await asyncio.gather(attempt(admin_a_id), attempt(admin_b_id))

    assert sorted(results) == ["already_confirmed", "success"]

    async with pool.acquire() as conn:
        variant = await conn.fetchrow(
            "SELECT stock_on_hand, stock_reserved FROM product_variants WHERE id = $1", variant_id
        )
        # Exactly one confirm's worth of decrement, not two.
        assert variant["stock_on_hand"] == stock - qty
        assert variant["stock_reserved"] == 0

        order = await orders_repository.get_order(conn, order_id=order_id)
        assert order["status"] == "CONFIRMED"

        movements = await conn.fetch(
            "SELECT movement_type FROM inventory_movements WHERE variant_id = $1 AND movement_type = 'OUT'",
            variant_id,
        )
        assert len(movements) == 1  # not double-logged either
