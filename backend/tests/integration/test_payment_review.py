"""REQ-BIZ-008: an APPROVED payment never reverts to PENDING — provably
one-way, not just "the UI doesn't offer a button for it"."""
from __future__ import annotations

import pytest

from app.domains.commerce.orders import service as orders_service
from app.domains.payments import service as payments_service
from tests.integration import factories

pytestmark = pytest.mark.asyncio


async def _setup_payment(conn):
    user_id = await factories.make_user(conn)
    admin_id = await factories.make_user(conn, role="ADMIN")
    brand_id = await factories.make_brand(conn, name="PaymentTestBrand")
    product_id = await factories.make_product(conn, brand_id=brand_id, name="Payment Test Product")
    variant_id = await factories.make_variant(
        conn, product_id=product_id, sku="PAYTEST-SKU-1", price=40_000, stock_on_hand=5
    )
    order = await orders_service.create_order(
        conn, user_id=user_id, lines=[orders_service.CheckoutLine(variant_id=variant_id, quantity=1)]
    )
    payment = await payments_service.submit_payment(conn, order_id=order["id"], actor_id=user_id, actor_role="USER")
    return order, payment, admin_id


async def test_approved_payment_never_reverts_to_pending(conn, clean_slate):
    order, payment, admin_id = await _setup_payment(conn)

    approved = await payments_service.review_payment(
        conn, payment_id=payment["id"], approve=True, rejection_reason=None, actor_id=admin_id, actor_role="ADMIN"
    )
    assert approved["status"] == "APPROVED"

    # A second review attempt (any outcome) must not succeed against an
    # already-APPROVED payment — the guarded `WHERE status='PENDING'`
    # affects zero rows.
    with pytest.raises(ValueError):
        await payments_service.review_payment(
            conn, payment_id=payment["id"], approve=False, rejection_reason="trying to revert",
            actor_id=admin_id, actor_role="ADMIN",
        )

    still_approved = await conn.fetchrow("SELECT status FROM payments WHERE id = $1", payment["id"])
    assert still_approved["status"] == "APPROVED"


async def test_approving_payment_updates_order_paid_amount(conn, clean_slate):
    order, payment, admin_id = await _setup_payment(conn)

    await payments_service.review_payment(
        conn, payment_id=payment["id"], approve=True, rejection_reason=None, actor_id=admin_id, actor_role="ADMIN"
    )

    updated_order = await conn.fetchrow("SELECT paid_amount, remaining_amount FROM orders WHERE id = $1", order["id"])
    assert updated_order["paid_amount"] == payment["amount"]
    assert updated_order["remaining_amount"] == order["total_amount"] - payment["amount"]


async def test_rejecting_payment_requires_a_reason(conn, clean_slate):
    order, payment, admin_id = await _setup_payment(conn)

    with pytest.raises(ValueError):
        await payments_service.review_payment(
            conn, payment_id=payment["id"], approve=False, rejection_reason=None, actor_id=admin_id, actor_role="ADMIN"
        )
