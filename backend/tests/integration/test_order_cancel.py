"""§8.4 cancellation + the mandatory guarded reservation-release pattern
(AGENTS/backend-commerce.md) exercised through the real order-cancel path,
not just the isolated DB-layer test in tests/db/test_schema.py."""
from __future__ import annotations

import pytest

from app.domains.commerce.orders import service as orders_service
from tests.integration import factories

pytestmark = pytest.mark.asyncio


async def test_cancel_releases_reservation_and_requires_reason(conn, clean_slate):
    user_id = await factories.make_user(conn)
    brand_id = await factories.make_brand(conn, name="CancelTestBrand")
    product_id = await factories.make_product(conn, brand_id=brand_id, name="Cancel Test Product")
    variant_id = await factories.make_variant(
        conn, product_id=product_id, sku="CANCEL-SKU-1", price=10_000, stock_on_hand=5
    )
    order = await orders_service.create_order(
        conn, user_id=user_id, lines=[orders_service.CheckoutLine(variant_id=variant_id, quantity=2)]
    )

    with pytest.raises(ValueError):
        await orders_service.cancel_order(
            conn, order_id=order["id"], reason="short", actor_id=user_id, actor_role="USER"
        )

    updated = await orders_service.cancel_order(
        conn, order_id=order["id"], reason="changed my mind about this order", actor_id=user_id, actor_role="USER"
    )
    assert updated["status"] == "CANCELLED"

    variant = await conn.fetchrow("SELECT stock_reserved FROM product_variants WHERE id = $1", variant_id)
    assert variant["stock_reserved"] == 0

    reservation = await conn.fetchrow("SELECT released_at FROM stock_reservations WHERE order_id = $1", order["id"])
    assert reservation["released_at"] is not None


async def test_confirmed_order_cannot_be_cancelled(conn, clean_slate):
    """ADR-017: a CONFIRMED order must go through cancellation_requests +
    admin decision, never the direct cancel_order endpoint — even though
    the state machine table itself now permits CONFIRMED -> CANCELLED for
    that dedicated path (see app/domains/commerce/cancellations/service.py)."""
    user_id = await factories.make_user(conn)
    admin_id = await factories.make_user(conn, role="ADMIN")
    brand_id = await factories.make_brand(conn, name="ConfirmedCancelBrand")
    product_id = await factories.make_product(conn, brand_id=brand_id, name="Confirmed Cancel Product")
    variant_id = await factories.make_variant(
        conn, product_id=product_id, sku="CONFCANCEL-SKU-1", price=10_000, stock_on_hand=5
    )
    order = await orders_service.create_order(
        conn, user_id=user_id, lines=[orders_service.CheckoutLine(variant_id=variant_id, quantity=1)]
    )
    await conn.execute("UPDATE orders SET status = 'UNDER_REVIEW' WHERE id = $1", order["id"])
    await orders_service.confirm_order(conn, order_id=order["id"], actor_id=admin_id, actor_role="ADMIN")

    with pytest.raises(orders_service.OrderHasApprovedPayment):
        await orders_service.cancel_order(
            conn, order_id=order["id"], reason="too late, already confirmed", actor_id=user_id, actor_role="USER"
        )
