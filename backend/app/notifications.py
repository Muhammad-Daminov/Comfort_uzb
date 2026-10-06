"""Notification producer helper.

ADR-016 (docs/adr/ADR-016-notification-delivery.md) originally assigned
*writing* real notification rows to `backend-engagement` (P1, unbuilt) and
shipped only the consumer (`bot/notifications/poller.py`) in P0. Per an
explicit product decision (2026-10-06, recorded as an addendum to ADR-016),
the order/payment-confirmation notifications users actually need for the
P0 checkout flow to feel complete are wired directly from `backend-commerce`
or so, instead of waiting on the unbuilt engagement module — see that ADR's
addendum for the full reasoning. This file is the one place that decision
is implemented; it is *not* a second notification system — it writes the
exact same `notifications` row the already-built poller already consumes,
unchanged.

Hard rule (same as `app/security/audit.py::record_audit`): always call this
with the *same* connection/transaction the caller is already using for its
business-logic writes. Nothing here opens or commits a transaction — a
rollback of the caller's transaction must roll this row back too, so a
notification is never created for a state transition that didn't actually
happen.
"""
from __future__ import annotations

import asyncpg


async def create_notification(
    conn: asyncpg.Connection,
    *,
    user_id: int,
    type: str,
    title: str,
    body: str | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
) -> None:
    await conn.execute(
        """
        INSERT INTO notifications (user_id, type, title, body, entity_type, entity_id)
        VALUES ($1, $2, $3, $4, $5, $6)
        """,
        user_id,
        type,
        title,
        body,
        entity_type,
        entity_id,
    )


# ---------------------------------------------------------------------------
# Uzbek copy for the order/payment lifecycle events this slice wires.
# Content lives here (not bot/locales/uz.py) deliberately: the bot never
# templates a notification's text at send time (poller.py reads `title`/
# `body` as plain strings already baked into the row), and this module sits
# in `app/`, not `bot/` — ADR-1's dependency direction is bot -> app, never
# the reverse, so these producers cannot import from `bot.locales`.
# ---------------------------------------------------------------------------


def order_confirmed(*, order_number: str) -> tuple[str, str, str]:
    return ("order.confirmed", "✅ Buyurtmangiz tasdiqlandi", f"Buyurtma raqami: {order_number}")


def order_cancelled(*, order_number: str, reason: str) -> tuple[str, str, str]:
    return (
        "order.cancelled",
        "❌ Buyurtmangiz bekor qilindi",
        f"Buyurtma raqami: {order_number}\nSabab: {reason}",
    )


def payment_approved(*, order_number: str) -> tuple[str, str, str]:
    return ("payment.approved", "✅ To'lovingiz tasdiqlandi", f"Buyurtma raqami: {order_number}")


def payment_rejected(*, order_number: str, reason: str) -> tuple[str, str, str]:
    return (
        "payment.rejected",
        "❌ To'lovingiz rad etildi",
        f"Buyurtma raqami: {order_number}\nSabab: {reason}",
    )
