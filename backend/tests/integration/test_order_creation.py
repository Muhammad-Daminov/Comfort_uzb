"""§7.3 checkout re-validation and the parallel-last-unit-purchase test
(§8.2/§12.6: two users, one remaining unit, exactly one order succeeds)."""
from __future__ import annotations

import asyncio

import pytest

from app.domains.commerce.orders import service as orders_service
from app.domains.commerce.reservations.repository import InsufficientStock
from tests.integration import factories

pytestmark = pytest.mark.asyncio


async def test_stale_client_price_is_rejected_with_409_style_error(conn, clean_slate):
    user_id = await factories.make_user(conn)
    brand_id = await factories.make_brand(conn, name="PriceTestBrand")
    product_id = await factories.make_product(conn, brand_id=brand_id, name="Price Test Product")
    variant_id = await factories.make_variant(
        conn, product_id=product_id, sku="PRICE-SKU-1", price=50_000, stock_on_hand=10
    )

    with pytest.raises(orders_service.PriceMismatch) as excinfo:
        await orders_service.create_order(
            conn,
            user_id=user_id,
            lines=[
                orders_service.CheckoutLine(variant_id=variant_id, quantity=1, client_unit_price=1)
            ],  # frontend believes a stale/wrong price
        )
    assert excinfo.value.mismatches[0].expected_unit_price == 50_000

    # Nothing was written — no order, no reservation, no stock movement.
    count = await conn.fetchval("SELECT count(*) FROM orders WHERE user_id = $1", user_id)
    assert count == 0


async def test_insufficient_stock_is_rejected(conn, clean_slate):
    user_id = await factories.make_user(conn)
    brand_id = await factories.make_brand(conn, name="StockTestBrand")
    product_id = await factories.make_product(conn, brand_id=brand_id, name="Stock Test Product")
    variant_id = await factories.make_variant(
        conn, product_id=product_id, sku="STOCK-SKU-1", price=10_000, stock_on_hand=1
    )

    with pytest.raises(orders_service.InsufficientStock):
        await orders_service.create_order(
            conn, user_id=user_id, lines=[orders_service.CheckoutLine(variant_id=variant_id, quantity=5)]
        )


async def test_inactive_variant_is_rejected(conn, clean_slate):
    user_id = await factories.make_user(conn)
    brand_id = await factories.make_brand(conn, name="InactiveTestBrand")
    product_id = await factories.make_product(conn, brand_id=brand_id, name="Inactive Test Product")
    variant_id = await factories.make_variant(
        conn, product_id=product_id, sku="INACTIVE-SKU-1", price=10_000, stock_on_hand=10, status="ARCHIVED"
    )

    with pytest.raises(orders_service.VariantNotActive):
        await orders_service.create_order(
            conn, user_id=user_id, lines=[orders_service.CheckoutLine(variant_id=variant_id, quantity=1)]
        )


async def test_successful_checkout_writes_snapshot_and_reservation(conn, clean_slate):
    user_id = await factories.make_user(conn)
    brand_id = await factories.make_brand(conn, name="SnapshotTestBrand")
    product_id = await factories.make_product(conn, brand_id=brand_id, name="Snapshot Test Product")
    variant_id = await factories.make_variant(
        conn, product_id=product_id, sku="SNAP-SKU-1", price=25_000, stock_on_hand=10
    )

    order = await orders_service.create_order(
        conn, user_id=user_id, lines=[orders_service.CheckoutLine(variant_id=variant_id, quantity=3)]
    )

    assert order["total_amount"] == 75_000
    assert order["status"] == "CREATED"

    item = await conn.fetchrow("SELECT * FROM order_items WHERE order_id = $1", order["id"])
    assert item["unit_price"] == 25_000
    assert item["quantity"] == 3
    assert item["sku_snapshot"] == "SNAP-SKU-1"

    variant = await conn.fetchrow("SELECT stock_reserved FROM product_variants WHERE id = $1", variant_id)
    assert variant["stock_reserved"] == 3

    reservation = await conn.fetchrow("SELECT * FROM stock_reservations WHERE order_id = $1", order["id"])
    assert reservation["released_at"] is None
    assert reservation["quantity"] == 3

    audit_row = await conn.fetchrow(
        "SELECT * FROM audit_logs WHERE entity_type = 'order' AND entity_id = $1 AND action = 'order.create'",
        order["id"],
    )
    assert audit_row is not None


async def test_parallel_last_unit_purchase_exactly_one_succeeds(pool, clean_slate):
    async with pool.acquire() as setup_conn:
        user_a_id = await factories.make_user(setup_conn)
        user_b_id = await factories.make_user(setup_conn)
        brand_id = await factories.make_brand(setup_conn, name="LastUnitBrand")
        product_id = await factories.make_product(setup_conn, brand_id=brand_id, name="Last Unit Product")
        variant_id = await factories.make_variant(
            setup_conn, product_id=product_id, sku="LASTUNIT-SKU-1", price=15_000, stock_on_hand=1
        )

    async def attempt(user_id: int):
        async with pool.acquire() as conn:
            try:
                await orders_service.create_order(
                    conn, user_id=user_id, lines=[orders_service.CheckoutLine(variant_id=variant_id, quantity=1)]
                )
                return "success"
            except InsufficientStock:
                return "insufficient_stock"

    results = await asyncio.gather(attempt(user_a_id), attempt(user_b_id))

    assert sorted(results) == ["insufficient_stock", "success"]

    async with pool.acquire() as conn:
        variant = await conn.fetchrow(
            "SELECT stock_on_hand, stock_reserved FROM product_variants WHERE id = $1", variant_id
        )
        assert variant["stock_reserved"] == 1  # not 2 — no overselling
        order_count = await conn.fetchval(
            "SELECT count(*) FROM orders WHERE user_id = ANY($1::bigint[])", [user_a_id, user_b_id]
        )
        assert order_count == 1
