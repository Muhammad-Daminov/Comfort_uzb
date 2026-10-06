"""Phase 08: genuine concurrency test for `POST /admin/inventory/adjust`'s
underlying repository call — two real connections, two real concurrent
UPDATEs on the same variant, not a sequential simulation. The guarded
single-statement UPDATE (`app/domains/commerce/inventory/repository.py`)
was already correct by construction (Postgres row-level locking serializes
concurrent UPDATEs to the same row) — this proves it, rather than assuming
it from code review alone.
"""
from __future__ import annotations

import asyncio

import pytest

from app.domains.commerce.inventory import repository as inventory_repository
from tests.integration import factories

pytestmark = pytest.mark.asyncio


async def test_concurrent_adjustments_both_apply_no_lost_update(pool, clean_slate):
    async with pool.acquire() as setup_conn:
        brand_id = await factories.make_brand(setup_conn, name="ConcurrentAdjustBrand")
        product_id = await factories.make_product(setup_conn, brand_id=brand_id, name="Concurrent Adjust Product")
        variant_id = await factories.make_variant(
            setup_conn, product_id=product_id, sku="CONCADJ-SKU-1", price=10_000, stock_on_hand=100
        )
        actor_id = await factories.make_user(setup_conn, role="ADMIN")

    async def adjust(delta: int):
        async with pool.acquire() as conn:
            await inventory_repository.adjust_stock(
                conn, variant_id=variant_id, quantity_change=delta, reason="concurrent adjust test", actor_id=actor_id
            )

    # Two genuinely concurrent connections adjusting the same variant in
    # opposite directions — if the UPDATE weren't atomic (e.g. a naive
    # read-then-write), one delta would be lost.
    await asyncio.gather(adjust(30), adjust(-10))

    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT stock_on_hand FROM product_variants WHERE id = $1", variant_id)
        movements = await conn.fetch(
            "SELECT quantity_change FROM inventory_movements WHERE variant_id = $1 AND movement_type = 'ADJUST' ORDER BY id",
            variant_id,
        )

    assert row["stock_on_hand"] == 100 + 30 - 10  # both deltas applied, neither lost
    assert sorted(m["quantity_change"] for m in movements) == [-10, 30]  # both logged, exactly once each


async def test_concurrent_adjustment_below_zero_is_rejected_not_raced(pool, clean_slate):
    async with pool.acquire() as setup_conn:
        brand_id = await factories.make_brand(setup_conn, name="ConcurrentAdjustBrand2")
        product_id = await factories.make_product(setup_conn, brand_id=brand_id, name="Concurrent Adjust Product 2")
        variant_id = await factories.make_variant(
            setup_conn, product_id=product_id, sku="CONCADJ-SKU-2", price=10_000, stock_on_hand=10
        )
        actor_id = await factories.make_user(setup_conn, role="ADMIN")

    async def adjust(delta: int) -> str:
        async with pool.acquire() as conn:
            try:
                await inventory_repository.adjust_stock(
                    conn, variant_id=variant_id, quantity_change=delta, reason="concurrent negative test", actor_id=actor_id
                )
                return "ok"
            except ValueError:
                return "rejected"

    # Two concurrent -8 adjustments against a stock of 10 — only one can
    # succeed (10-8=2 >= 0), the other must be cleanly rejected, not driven
    # negative by a race.
    results = await asyncio.gather(adjust(-8), adjust(-8))

    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT stock_on_hand FROM product_variants WHERE id = $1", variant_id)

    assert row["stock_on_hand"] >= 0
    assert sorted(results) == ["ok", "rejected"]
    assert row["stock_on_hand"] == 2
