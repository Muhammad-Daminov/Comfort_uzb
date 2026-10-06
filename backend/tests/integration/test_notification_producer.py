"""Regression coverage for the real notification producer (app/notifications.py),
wired into orders/service.py::confirm_order/cancel_order and
payments/service.py::review_payment per the 2026-10-06 ADR-016 addendum.

Unlike test_notification_delivery.py (which proves the poller/consumer side
by manually inserting a row), every test here drives the *real* domain
transition and asserts the notification row that transition is supposed to
produce — then, for the representative end-to-end case, hands that real row
to the real, unmodified poller to prove the whole chain:

    domain state transition -> notification row -> existing poller
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import asyncpg
import pytest

from app import notifications
from app.domains.commerce.orders import service as orders_service
from app.domains.commerce.orders.state_machine import InvalidTransition
from app.domains.payments import service as payments_service
from bot.notifications.poller import poll_loop
from tests.integration import factories

pytestmark = pytest.mark.asyncio


async def _setup_under_review_order(conn, *, stock: int = 5, qty: int = 1, price: int = 50_000):
    user_id = await factories.make_user(conn)
    admin_id = await factories.make_user(conn, role="ADMIN")
    brand_id = await factories.make_brand(conn, name="NotifProducerBrand")
    product_id = await factories.make_product(conn, brand_id=brand_id, name="Notif Producer Product")
    variant_id = await factories.make_variant(
        conn, product_id=product_id, sku=f"NOTIF-{qty}-{price}", price=price, stock_on_hand=stock
    )
    order = await orders_service.create_order(
        conn, user_id=user_id, lines=[orders_service.CheckoutLine(variant_id=variant_id, quantity=qty)]
    )
    await conn.execute("UPDATE orders SET status = 'UNDER_REVIEW' WHERE id = $1", order["id"])
    return order["id"], user_id, admin_id


async def _notification_for_order(conn, order_id: int) -> asyncpg.Record | None:
    return await conn.fetchrow(
        "SELECT * FROM notifications WHERE entity_type = 'order' AND entity_id = $1 ORDER BY id DESC LIMIT 1",
        order_id,
    )


# ---------------------------------------------------------------------------
# Order confirm
# ---------------------------------------------------------------------------


async def test_confirm_order_creates_a_notification_for_the_order_owner(conn, clean_slate):
    order_id, user_id, admin_id = await _setup_under_review_order(conn)

    await orders_service.confirm_order(conn, order_id=order_id, actor_id=admin_id, actor_role="ADMIN")

    row = await _notification_for_order(conn, order_id)
    assert row is not None
    assert row["user_id"] == user_id  # recipient is the order's owner, not the admin who acted
    assert row["type"] == "order.confirmed"
    assert row["entity_type"] == "order"
    assert row["entity_id"] == order_id
    assert row["telegram_sent_at"] is None  # not yet picked up by the poller


async def test_confirm_order_notification_is_delivered_by_the_real_poller(conn, clean_slate):
    """The full chain, end to end: a real confirm_order call produces a
    real notifications row, and the existing, unmodified poller delivers
    it — no manually-inserted row anywhere in this test."""
    order_id, user_id, admin_id = await _setup_under_review_order(conn)

    await orders_service.confirm_order(conn, order_id=order_id, actor_id=admin_id, actor_role="ADMIN")

    bot = MagicMock()
    bot.send_message = AsyncMock()

    sent = await poll_loop(conn, bot)

    assert sent == 1
    bot.send_message.assert_awaited_once()
    sent_telegram_id, sent_text = bot.send_message.await_args.args
    assert "tasdiqlandi" in sent_text  # the real Uzbek copy, not a test placeholder

    row = await _notification_for_order(conn, order_id)
    assert row["telegram_sent_at"] is not None


async def test_confirming_an_already_confirmed_order_does_not_create_a_second_notification(conn, clean_slate):
    order_id, user_id, admin_id = await _setup_under_review_order(conn)

    await orders_service.confirm_order(conn, order_id=order_id, actor_id=admin_id, actor_role="ADMIN")

    with pytest.raises(InvalidTransition):
        await orders_service.confirm_order(conn, order_id=order_id, actor_id=admin_id, actor_role="ADMIN")

    count = await conn.fetchval(
        "SELECT count(*) FROM notifications WHERE entity_type = 'order' AND entity_id = $1", order_id
    )
    assert count == 1


async def test_rolled_back_confirm_leaves_no_notification_row(conn, clean_slate, monkeypatch):
    """Phase 4: a notification must not survive when the state transition
    that caused it was rolled back. Forces a failure *after* the real
    INSERT has executed but before the enclosing transaction commits —
    the strongest version of this guarantee, not just "the code path never
    reached the insert"."""
    order_id, user_id, admin_id = await _setup_under_review_order(conn)

    real_create = notifications.create_notification

    async def boom(conn_arg, **kwargs):
        await real_create(conn_arg, **kwargs)
        raise RuntimeError("simulated failure after the notification insert")

    monkeypatch.setattr(orders_service.notifications, "create_notification", boom)

    with pytest.raises(RuntimeError):
        await orders_service.confirm_order(conn, order_id=order_id, actor_id=admin_id, actor_role="ADMIN")

    order_row = await conn.fetchrow("SELECT status FROM orders WHERE id = $1", order_id)
    assert order_row["status"] == "UNDER_REVIEW"  # the transition itself rolled back too

    row = await _notification_for_order(conn, order_id)
    assert row is None


async def test_concurrent_confirm_attempts_produce_exactly_one_notification(pool, clean_slate):
    """Same race shape as test_order_confirm.py's parallel-confirm test,
    extended to prove the notification side too: two real connections,
    two real concurrent confirm_order calls, only the winner's transaction
    ever reaches the notification insert."""
    async with pool.acquire() as setup_conn:
        order_id, user_id, admin_id = await _setup_under_review_order(setup_conn)
        admin_b_id = await factories.make_user(setup_conn, role="ADMIN")

    async def attempt(actor_id: int):
        async with pool.acquire() as conn:
            try:
                await orders_service.confirm_order(conn, order_id=order_id, actor_id=actor_id, actor_role="ADMIN")
                return "success"
            except (orders_service.ConcurrentConfirmation, InvalidTransition):
                return "already_confirmed"

    results = await asyncio.gather(attempt(admin_id), attempt(admin_b_id))
    assert sorted(results) == ["already_confirmed", "success"]

    async with pool.acquire() as check_conn:
        count = await check_conn.fetchval(
            "SELECT count(*) FROM notifications WHERE entity_type = 'order' AND entity_id = $1", order_id
        )
    assert count == 1


# ---------------------------------------------------------------------------
# Order cancel
# ---------------------------------------------------------------------------


async def test_admin_cancel_notifies_the_order_owner(conn, clean_slate):
    order_id, user_id, admin_id = await _setup_under_review_order(conn)
    await conn.execute("UPDATE orders SET status = 'CREATED' WHERE id = $1", order_id)

    await orders_service.cancel_order(
        conn, order_id=order_id, reason="Admin tomonidan bekor qilindi", actor_id=admin_id, actor_role="ADMIN"
    )

    row = await _notification_for_order(conn, order_id)
    assert row is not None
    assert row["type"] == "order.cancelled"
    assert row["user_id"] == user_id
    assert "Admin tomonidan bekor qilindi" in row["body"]


async def test_self_cancel_by_the_user_does_not_create_a_notification(conn, clean_slate):
    """The user already knows when they cancel their own order — no
    pointless self-notification."""
    order_id, user_id, admin_id = await _setup_under_review_order(conn)
    await conn.execute("UPDATE orders SET status = 'CREATED' WHERE id = $1", order_id)

    await orders_service.cancel_order(
        conn, order_id=order_id, reason="Fikrimdan qaytdim shu kerak emas", actor_id=user_id, actor_role="USER"
    )

    row = await _notification_for_order(conn, order_id)
    assert row is None


# ---------------------------------------------------------------------------
# Payment review
# ---------------------------------------------------------------------------


async def _setup_payment(conn):
    user_id = await factories.make_user(conn)
    admin_id = await factories.make_user(conn, role="ADMIN")
    brand_id = await factories.make_brand(conn, name="NotifPaymentBrand")
    product_id = await factories.make_product(conn, brand_id=brand_id, name="Notif Payment Product")
    variant_id = await factories.make_variant(
        conn, product_id=product_id, sku="NOTIF-PAY-SKU-1", price=60_000, stock_on_hand=5
    )
    order = await orders_service.create_order(
        conn, user_id=user_id, lines=[orders_service.CheckoutLine(variant_id=variant_id, quantity=1)]
    )
    payment = await payments_service.submit_payment(conn, order_id=order["id"], actor_id=user_id, actor_role="USER")
    return order, payment, user_id, admin_id


async def test_payment_approval_notifies_the_order_owner(conn, clean_slate):
    order, payment, user_id, admin_id = await _setup_payment(conn)

    await payments_service.review_payment(
        conn, payment_id=payment["id"], approve=True, rejection_reason=None, actor_id=admin_id, actor_role="ADMIN"
    )

    row = await _notification_for_order(conn, order["id"])
    assert row is not None
    assert row["type"] == "payment.approved"
    assert row["user_id"] == user_id


async def test_payment_rejection_notifies_the_order_owner_with_the_reason(conn, clean_slate):
    order, payment, user_id, admin_id = await _setup_payment(conn)

    await payments_service.review_payment(
        conn,
        payment_id=payment["id"],
        approve=False,
        rejection_reason="Kvitansiya noaniq, qaytadan yuboring",
        actor_id=admin_id,
        actor_role="ADMIN",
    )

    row = await _notification_for_order(conn, order["id"])
    assert row is not None
    assert row["type"] == "payment.rejected"
    assert row["user_id"] == user_id
    assert "Kvitansiya noaniq, qaytadan yuboring" in row["body"]


async def test_payment_review_notification_is_delivered_by_the_real_poller(conn, clean_slate):
    order, payment, user_id, admin_id = await _setup_payment(conn)

    await payments_service.review_payment(
        conn, payment_id=payment["id"], approve=True, rejection_reason=None, actor_id=admin_id, actor_role="ADMIN"
    )

    bot = MagicMock()
    bot.send_message = AsyncMock()

    sent = await poll_loop(conn, bot)

    assert sent == 1
    row = await _notification_for_order(conn, order["id"])
    assert row["telegram_sent_at"] is not None


async def test_reviewing_an_already_reviewed_payment_does_not_create_a_second_notification(conn, clean_slate):
    order, payment, user_id, admin_id = await _setup_payment(conn)

    await payments_service.review_payment(
        conn, payment_id=payment["id"], approve=True, rejection_reason=None, actor_id=admin_id, actor_role="ADMIN"
    )

    with pytest.raises(ValueError):
        await payments_service.review_payment(
            conn, payment_id=payment["id"], approve=False, rejection_reason="trying to revert",
            actor_id=admin_id, actor_role="ADMIN",
        )

    count = await conn.fetchval(
        "SELECT count(*) FROM notifications WHERE entity_type = 'order' AND entity_id = $1", order["id"]
    )
    assert count == 1
