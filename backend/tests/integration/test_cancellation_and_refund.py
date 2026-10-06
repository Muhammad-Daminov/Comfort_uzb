"""ADR-017: post-confirmation cancellation requests + independent refund
lifecycle, exercised against a real DB — closes OPEN-4/OPEN-6."""
from __future__ import annotations

import asyncio

import pytest

from app.domains.commerce.cancellations import service as cancellations_service
from app.domains.commerce.orders import service as orders_service
from app.domains.commerce.refunds import service as refunds_service
from tests.integration import factories

pytestmark = pytest.mark.asyncio


async def _confirmed_paid_order(conn, *, price: int = 100_000, qty: int = 1, stock: int = 5):
    user_id = await factories.make_user(conn)
    admin_id = await factories.make_user(conn, role="ADMIN")
    brand_id = await factories.make_brand(conn, name="CancelRefundBrand")
    product_id = await factories.make_product(conn, brand_id=brand_id, name="Cancel Refund Product")
    variant_id = await factories.make_variant(
        conn, product_id=product_id, sku="CANCELREFUND-SKU-1", price=price, stock_on_hand=stock
    )
    order = await orders_service.create_order(
        conn, user_id=user_id, lines=[orders_service.CheckoutLine(variant_id=variant_id, quantity=qty)]
    )
    await conn.execute("UPDATE orders SET status = 'UNDER_REVIEW' WHERE id = $1", order["id"])
    await orders_service.confirm_order(conn, order_id=order["id"], actor_id=admin_id, actor_role="ADMIN")
    await conn.execute(
        "UPDATE orders SET paid_amount = total_amount, remaining_amount = 0 WHERE id = $1", order["id"]
    )
    paid = await conn.fetchval("SELECT paid_amount FROM orders WHERE id = $1", order["id"])
    # Read back the real paid_amount rather than assuming it equals
    # price * qty — a discount active from another test's fixture (the
    # `discounts` table is deliberately not truncated between tests, see
    # tests/integration/conftest.py) can lower total_amount below the
    # variant's raw price, and this helper must stay correct either way.
    return order["id"], variant_id, user_id, admin_id, stock, qty, paid


async def test_user_can_request_cancellation_of_confirmed_order(conn, clean_slate):
    order_id, _variant_id, user_id, _admin_id, _stock, _qty, _paid = await _confirmed_paid_order(conn)

    request = await cancellations_service.request_cancellation(
        conn, order_id=order_id, user_id=user_id, reason="wrong color, want to return it"
    )
    assert request["status"] == "PENDING"


async def test_second_pending_request_on_same_order_is_rejected(conn, clean_slate):
    order_id, _variant_id, user_id, _admin_id, _stock, _qty, _paid = await _confirmed_paid_order(conn)

    await cancellations_service.request_cancellation(
        conn, order_id=order_id, user_id=user_id, reason="first request, changed my mind"
    )
    with pytest.raises(cancellations_service.RequestAlreadyOpen):
        await cancellations_service.request_cancellation(
            conn, order_id=order_id, user_id=user_id, reason="second request, still changed my mind"
        )


async def test_admin_approval_cancels_order_and_restocks(conn, clean_slate):
    order_id, variant_id, user_id, admin_id, stock, qty, _paid = await _confirmed_paid_order(conn, stock=5, qty=2)

    before = await conn.fetchrow("SELECT stock_on_hand FROM product_variants WHERE id = $1", variant_id)

    request = await cancellations_service.request_cancellation(
        conn, order_id=order_id, user_id=user_id, reason="defective item, want a refund"
    )
    decided = await cancellations_service.decide_cancellation(
        conn, request_id=request["id"], approve=True, decision_note="confirmed defective", actor_id=admin_id, actor_role="ADMIN",
    )
    assert decided["status"] == "APPROVED"

    order = await conn.fetchrow("SELECT status FROM orders WHERE id = $1", order_id)
    assert order["status"] == "CANCELLED"

    after = await conn.fetchrow("SELECT stock_on_hand FROM product_variants WHERE id = $1", variant_id)
    assert after["stock_on_hand"] == before["stock_on_hand"] + qty

    movement = await conn.fetchrow(
        "SELECT movement_type, quantity_change FROM inventory_movements "
        "WHERE variant_id = $1 AND reference_type = 'order' AND reference_id = $2 AND movement_type = 'IN'",
        variant_id, order_id,
    )
    assert movement["quantity_change"] == qty


async def test_admin_denial_leaves_order_confirmed(conn, clean_slate):
    order_id, _variant_id, user_id, admin_id, _stock, _qty, _paid = await _confirmed_paid_order(conn)

    request = await cancellations_service.request_cancellation(
        conn, order_id=order_id, user_id=user_id, reason="changed my mind about the order"
    )
    decided = await cancellations_service.decide_cancellation(
        conn, request_id=request["id"], approve=False, decision_note="already shipped", actor_id=admin_id, actor_role="ADMIN",
    )
    assert decided["status"] == "DENIED"

    order = await conn.fetchrow("SELECT status FROM orders WHERE id = $1", order_id)
    assert order["status"] == "CONFIRMED"


async def test_deciding_an_already_decided_request_is_rejected(conn, clean_slate):
    order_id, _variant_id, user_id, admin_id, _stock, _qty, _paid = await _confirmed_paid_order(conn)

    request = await cancellations_service.request_cancellation(
        conn, order_id=order_id, user_id=user_id, reason="want to cancel this order please"
    )
    await cancellations_service.decide_cancellation(
        conn, request_id=request["id"], approve=True, decision_note=None, actor_id=admin_id, actor_role="ADMIN",
    )
    with pytest.raises(cancellations_service.RequestNotPending):
        await cancellations_service.decide_cancellation(
            conn, request_id=request["id"], approve=True, decision_note=None, actor_id=admin_id, actor_role="ADMIN",
        )


async def test_refund_cannot_exceed_paid_amount(conn, clean_slate):
    order_id, _variant_id, _user_id, admin_id, _stock, _qty, paid = await _confirmed_paid_order(conn, price=100_000, qty=1)

    with pytest.raises(refunds_service.InvalidRefundAmount):
        await refunds_service.record_refund(
            conn, order_id=order_id, payment_id=None, amount=paid + 1, method="CASH",
            reason="refunding more than was ever paid", actor_id=admin_id, actor_role="ADMIN",
        )


async def test_refund_lifecycle_create_then_complete(conn, clean_slate):
    order_id, _variant_id, _user_id, admin_id, _stock, _qty, paid = await _confirmed_paid_order(conn, price=100_000, qty=1)

    refund = await refunds_service.record_refund(
        conn, order_id=order_id, payment_id=None, amount=paid, method="CASH",
        reason="customer returned the item in person", actor_id=admin_id, actor_role="ADMIN",
    )
    assert refund["status"] == "PENDING"

    completed = await refunds_service.complete_refund(
        conn, refund_id=refund["id"], provider_reference="cash-receipt-42", actor_id=admin_id, actor_role="ADMIN",
    )
    assert completed["status"] == "COMPLETED"
    assert completed["completed_by"] == admin_id


async def test_duplicate_refund_beyond_paid_amount_is_rejected(conn, clean_slate):
    order_id, _variant_id, _user_id, admin_id, _stock, _qty, paid = await _confirmed_paid_order(conn, price=100_000, qty=1)

    first = await refunds_service.record_refund(
        conn, order_id=order_id, payment_id=None, amount=paid, method="CASH",
        reason="full refund for damaged packaging", actor_id=admin_id, actor_role="ADMIN",
    )
    await refunds_service.complete_refund(
        conn, refund_id=first["id"], provider_reference=None, actor_id=admin_id, actor_role="ADMIN",
    )

    # The full paid amount is already refunded and COMPLETED; any further
    # refund would exceed what was actually paid — must be rejected.
    with pytest.raises(refunds_service.InvalidRefundAmount):
        await refunds_service.record_refund(
            conn, order_id=order_id, payment_id=None, amount=1, method="CASH",
            reason="second refund attempt exceeding paid amount", actor_id=admin_id, actor_role="ADMIN",
        )


async def test_completing_an_already_completed_refund_is_rejected(conn, clean_slate):
    order_id, _variant_id, _user_id, admin_id, _stock, _qty, paid = await _confirmed_paid_order(conn, price=100_000, qty=1)

    refund = await refunds_service.record_refund(
        conn, order_id=order_id, payment_id=None, amount=paid, method="CARD",
        reason="admin-attested manual card reversal", actor_id=admin_id, actor_role="ADMIN",
    )
    await refunds_service.complete_refund(
        conn, refund_id=refund["id"], provider_reference="manual-1", actor_id=admin_id, actor_role="ADMIN",
    )
    with pytest.raises(refunds_service.RefundNotPending):
        await refunds_service.complete_refund(
            conn, refund_id=refund["id"], provider_reference="manual-2", actor_id=admin_id, actor_role="ADMIN",
        )


async def test_concurrent_admin_decisions_only_one_wins(pool, clean_slate):
    """Two admins racing to decide the same cancellation request — exactly
    one succeeds (mirrors the confirm_order concurrency pattern, §8.2)."""
    async with pool.acquire() as setup_conn:
        order_id, _variant_id, user_id, admin_a_id, _stock, _qty, _paid = await _confirmed_paid_order(setup_conn)
        admin_b_id = await factories.make_user(setup_conn, role="ADMIN")
        request = await cancellations_service.request_cancellation(
            setup_conn, order_id=order_id, user_id=user_id, reason="racing admins decide this one"
        )

    async def attempt(admin_id: int, approve: bool):
        async with pool.acquire() as conn:
            try:
                await cancellations_service.decide_cancellation(
                    conn, request_id=request["id"], approve=approve, decision_note=None,
                    actor_id=admin_id, actor_role="ADMIN",
                )
                return "success"
            except cancellations_service.RequestNotPending:
                return "already_decided"

    results = await asyncio.gather(attempt(admin_a_id, True), attempt(admin_b_id, False))
    assert results.count("success") == 1
    assert results.count("already_decided") == 1


async def test_two_pending_full_refunds_only_one_can_ever_complete(conn, clean_slate):
    """record_refund's ceiling only counts *completed* refunds (documented
    in refunds/service.py), so two PENDING full-amount refunds on the same
    order can both be created — but complete_refund re-checks the ceiling
    at completion time, so only one of them can ever actually complete.
    This is the fix for the gap concurrent completion would otherwise hit."""
    order_id, _variant_id, _user_id, admin_id, _stock, _qty, paid = await _confirmed_paid_order(
        conn, price=100_000, qty=1
    )

    first = await refunds_service.record_refund(
        conn, order_id=order_id, payment_id=None, amount=paid, method="CASH",
        reason="first full refund, not yet completed", actor_id=admin_id, actor_role="ADMIN",
    )
    second = await refunds_service.record_refund(
        conn, order_id=order_id, payment_id=None, amount=paid, method="CASH",
        reason="second full refund, not yet completed", actor_id=admin_id, actor_role="ADMIN",
    )

    await refunds_service.complete_refund(
        conn, refund_id=first["id"], provider_reference=None, actor_id=admin_id, actor_role="ADMIN",
    )
    with pytest.raises(refunds_service.InvalidRefundAmount):
        await refunds_service.complete_refund(
            conn, refund_id=second["id"], provider_reference=None, actor_id=admin_id, actor_role="ADMIN",
        )

    still_pending = await conn.fetchrow("SELECT status FROM refunds WHERE id = $1", second["id"])
    assert still_pending["status"] == "PENDING"  # rejected completion leaves it PENDING, not silently COMPLETED


async def test_concurrent_completion_of_two_full_refunds_only_one_wins(pool, clean_slate):
    """Same scenario as above, but genuinely concurrent — the order-row
    lock in complete_refund must serialize the two completions so the
    second one's re-check always sees the first one's already-completed
    amount, never a stale read."""
    async with pool.acquire() as setup_conn:
        order_id, _variant_id, _user_id, admin_id, _stock, _qty, paid = await _confirmed_paid_order(
            setup_conn, price=100_000, qty=1
        )
        first = await refunds_service.record_refund(
            setup_conn, order_id=order_id, payment_id=None, amount=paid, method="CASH",
            reason="concurrent completion candidate 1", actor_id=admin_id, actor_role="ADMIN",
        )
        second = await refunds_service.record_refund(
            setup_conn, order_id=order_id, payment_id=None, amount=paid, method="CASH",
            reason="concurrent completion candidate 2", actor_id=admin_id, actor_role="ADMIN",
        )

    async def attempt(refund_id: int):
        async with pool.acquire() as conn:
            try:
                await refunds_service.complete_refund(
                    conn, refund_id=refund_id, provider_reference=None, actor_id=admin_id, actor_role="ADMIN",
                )
                return "completed"
            except refunds_service.InvalidRefundAmount:
                return "rejected"

    results = await asyncio.gather(attempt(first["id"]), attempt(second["id"]))
    assert results.count("completed") == 1
    assert results.count("rejected") == 1

    async with pool.acquire() as conn:
        total_completed = await conn.fetchval(
            "SELECT COALESCE(SUM(amount), 0) FROM refunds WHERE order_id = $1 AND status = 'COMPLETED'", order_id,
        )
    assert total_completed == paid  # never double-refunded, regardless of race outcome
