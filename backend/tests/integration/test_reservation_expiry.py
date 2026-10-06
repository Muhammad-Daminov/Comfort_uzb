"""`comfort-reservation-expiry` worker logic (ADR-6, §15) — releases expired
reservations and moves the order to EXPIRED, and is safely re-runnable."""
from __future__ import annotations

import pytest

from app.domains.commerce.orders import service as orders_service
from app.workers import reservation_expiry
from tests.integration import factories

pytestmark = pytest.mark.asyncio


async def test_expired_reservation_is_released_and_order_expires(conn, clean_slate):
    user_id = await factories.make_user(conn)
    brand_id = await factories.make_brand(conn, name="ExpiryTestBrand")
    product_id = await factories.make_product(conn, brand_id=brand_id, name="Expiry Test Product")
    variant_id = await factories.make_variant(
        conn, product_id=product_id, sku="EXPIRY-SKU-1", price=10_000, stock_on_hand=5
    )

    order = await orders_service.create_order(
        conn, user_id=user_id, lines=[orders_service.CheckoutLine(variant_id=variant_id, quantity=2)]
    )
    # Force the reservation into the past so the worker picks it up.
    await conn.execute(
        "UPDATE stock_reservations SET expires_at = now() - interval '1 hour' WHERE order_id = $1", order["id"]
    )

    released_count = await reservation_expiry.run_once(conn)
    assert released_count == 1

    variant = await conn.fetchrow("SELECT stock_reserved FROM product_variants WHERE id = $1", variant_id)
    assert variant["stock_reserved"] == 0

    updated_order = await conn.fetchrow("SELECT status FROM orders WHERE id = $1", order["id"])
    assert updated_order["status"] == "EXPIRED"

    reservation = await conn.fetchrow("SELECT released_at FROM stock_reservations WHERE order_id = $1", order["id"])
    assert reservation["released_at"] is not None


async def test_running_worker_twice_is_a_noop_second_time(conn, clean_slate):
    user_id = await factories.make_user(conn)
    brand_id = await factories.make_brand(conn, name="ExpiryTwiceBrand")
    product_id = await factories.make_product(conn, brand_id=brand_id, name="Expiry Twice Product")
    variant_id = await factories.make_variant(
        conn, product_id=product_id, sku="EXPIRY-SKU-2", price=10_000, stock_on_hand=5
    )

    order = await orders_service.create_order(
        conn, user_id=user_id, lines=[orders_service.CheckoutLine(variant_id=variant_id, quantity=1)]
    )
    await conn.execute(
        "UPDATE stock_reservations SET expires_at = now() - interval '1 hour' WHERE order_id = $1", order["id"]
    )

    first_run = await reservation_expiry.run_once(conn)
    second_run = await reservation_expiry.run_once(conn)

    assert first_run == 1
    assert second_run == 0  # the guarded release pattern's no-op contract

    variant = await conn.fetchrow("SELECT stock_reserved FROM product_variants WHERE id = $1", variant_id)
    assert variant["stock_reserved"] == 0  # not decremented twice


async def test_reservation_not_yet_expired_is_left_alone(conn, clean_slate):
    user_id = await factories.make_user(conn)
    brand_id = await factories.make_brand(conn, name="NotExpiredBrand")
    product_id = await factories.make_product(conn, brand_id=brand_id, name="Not Expired Product")
    variant_id = await factories.make_variant(
        conn, product_id=product_id, sku="NOTEXP-SKU-1", price=10_000, stock_on_hand=5
    )

    order = await orders_service.create_order(
        conn, user_id=user_id, lines=[orders_service.CheckoutLine(variant_id=variant_id, quantity=1)]
    )

    released_count = await reservation_expiry.run_once(conn)
    assert released_count == 0

    updated_order = await conn.fetchrow("SELECT status FROM orders WHERE id = $1", order["id"])
    assert updated_order["status"] == "CREATED"
