"""Phase 08: the order state machine's exact named examples from the
hardening brief, each verified as a real service-layer call against a real
order — consolidated in one place for traceability. The underlying guard
(`state_machine.py` + guarded UPDATEs) already existed and is already
covered piecemeal by tests/unit/test_order_state_machine.py and
tests/integration/test_order_{confirm,cancel}.py; this file adds nothing
structurally new, it verifies the brief's specific examples explicitly.
"""
from __future__ import annotations

import pytest

from app.domains.commerce.orders import service as orders_service
from app.domains.commerce.orders.state_machine import InvalidTransition
from tests.integration import factories

pytestmark = pytest.mark.asyncio


async def _make_order(conn, *, status: str | None = None):
    user_id = await factories.make_user(conn)
    admin_id = await factories.make_user(conn, role="ADMIN")
    brand_id = await factories.make_brand(conn, name="StateMachineBrand")
    product_id = await factories.make_product(conn, brand_id=brand_id, name="State Machine Product")
    variant_id = await factories.make_variant(conn, product_id=product_id, sku="SM-SKU-1", price=10_000, stock_on_hand=10)
    order = await orders_service.create_order(
        conn, user_id=user_id, lines=[orders_service.CheckoutLine(variant_id=variant_id, quantity=1)]
    )
    if status is not None:
        await conn.execute("UPDATE orders SET status = $1 WHERE id = $2", status, order["id"])
    return order["id"], user_id, admin_id


async def test_cancelled_cannot_be_confirmed(conn, clean_slate):
    order_id, user_id, admin_id = await _make_order(conn)
    await orders_service.cancel_order(conn, order_id=order_id, reason="changed my mind entirely", actor_id=user_id, actor_role="USER")

    with pytest.raises((InvalidTransition, orders_service.ConcurrentConfirmation)):
        await orders_service.confirm_order(conn, order_id=order_id, actor_id=admin_id, actor_role="ADMIN")


async def test_confirmed_cannot_be_cancelled_via_direct_endpoint(conn, clean_slate):
    """ADR-017: CONFIRMED -> CANCELLED exists in the transition table now
    (reachable only via the dedicated cancellations service, see
    test_order_cancel.py::test_confirmed_order_routes_through_cancellation_request),
    but the generic user-facing cancel_order endpoint must still reject a
    CONFIRMED order outright — it raises the more specific
    OrderHasApprovedPayment, not InvalidTransition, since the state machine
    itself no longer forbids the transition."""
    order_id, user_id, admin_id = await _make_order(conn, status="UNDER_REVIEW")
    await orders_service.confirm_order(conn, order_id=order_id, actor_id=admin_id, actor_role="ADMIN")

    with pytest.raises(orders_service.OrderHasApprovedPayment):
        await orders_service.cancel_order(conn, order_id=order_id, reason="too late now, sorry", actor_id=user_id, actor_role="USER")


async def test_already_confirmed_cannot_be_confirmed_again(conn, clean_slate):
    order_id, user_id, admin_id = await _make_order(conn, status="UNDER_REVIEW")
    await orders_service.confirm_order(conn, order_id=order_id, actor_id=admin_id, actor_role="ADMIN")

    with pytest.raises((InvalidTransition, orders_service.ConcurrentConfirmation)):
        await orders_service.confirm_order(conn, order_id=order_id, actor_id=admin_id, actor_role="ADMIN")


async def test_already_cancelled_cannot_be_cancelled_again(conn, clean_slate):
    order_id, user_id, admin_id = await _make_order(conn)
    await orders_service.cancel_order(conn, order_id=order_id, reason="first cancellation reason", actor_id=user_id, actor_role="USER")

    with pytest.raises(InvalidTransition):
        await orders_service.cancel_order(conn, order_id=order_id, reason="second cancellation attempt", actor_id=user_id, actor_role="USER")


async def test_confirm_requires_under_review_not_awaiting_payment(conn, clean_slate):
    """"paid → cancelled" from the brief, interpreted against this schema's
    actual states: a CONFIRMED order (the closest concept to "paid" here,
    since APPROVED payment alone doesn't auto-confirm — admin confirm does,
    §8.2) cannot be cancelled — covered by test_confirmed_cannot_be_cancelled
    above. This test covers the adjacent case: confirm is only valid from
    UNDER_REVIEW, not from an earlier pre-payment state."""
    order_id, user_id, admin_id = await _make_order(conn)  # status stays CREATED

    with pytest.raises(InvalidTransition):
        await orders_service.confirm_order(conn, order_id=order_id, actor_id=admin_id, actor_role="ADMIN")
