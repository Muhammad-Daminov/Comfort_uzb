"""End-to-end verification of ADR-016's outbox mechanism against a live
Postgres: insert a `notifications` row (simulating a future
`backend-engagement` producer — Phase 04 ships the consumer only, see
ADR-016 "Consequences"), run the real poller with a stubbed Telegram send,
confirm `telegram_sent_at` is stamped and a second poll is a no-op.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramForbiddenError

from app.domains.identity import service as identity_service
from bot.notifications.poller import poll_loop
from tests.integration import factories

pytestmark = pytest.mark.asyncio


async def _insert_notification(conn, *, user_id: int, title: str = "Buyurtma tasdiqlandi") -> int:
    row = await conn.fetchrow(
        "INSERT INTO notifications (user_id, type, title, body) VALUES ($1, 'order.confirmed', $2, 'CU-TEST01') RETURNING id",
        user_id,
        title,
    )
    return row["id"]


async def test_unsent_notification_is_delivered_and_marked(conn, clean_slate):
    user_id = await factories.make_user(conn)
    notification_id = await _insert_notification(conn, user_id=user_id)

    bot = MagicMock()
    bot.send_message = AsyncMock()

    sent = await poll_loop(conn, bot)
    assert sent == 1
    bot.send_message.assert_awaited_once()

    row = await conn.fetchrow("SELECT telegram_sent_at FROM notifications WHERE id = $1", notification_id)
    assert row["telegram_sent_at"] is not None


async def test_second_poll_is_a_noop(conn, clean_slate):
    user_id = await factories.make_user(conn)
    await _insert_notification(conn, user_id=user_id)

    bot = MagicMock()
    bot.send_message = AsyncMock()

    first = await poll_loop(conn, bot)
    second = await poll_loop(conn, bot)

    assert first == 1
    assert second == 0
    bot.send_message.assert_awaited_once()  # not called again on the second poll


async def test_blocked_user_notification_is_marked_without_send(conn, clean_slate):
    user_id = await factories.make_user(conn)
    await identity_service.mark_bot_blocked(conn, telegram_id=(await conn.fetchrow(
        "SELECT telegram_id FROM users WHERE id = $1", user_id
    ))["telegram_id"])
    notification_id = await _insert_notification(conn, user_id=user_id)

    bot = MagicMock()
    bot.send_message = AsyncMock()

    sent = await poll_loop(conn, bot)

    assert sent == 0
    bot.send_message.assert_not_awaited()
    row = await conn.fetchrow("SELECT telegram_sent_at FROM notifications WHERE id = $1", notification_id)
    assert row["telegram_sent_at"] is not None  # handled, not retried forever


async def test_notifications_disabled_user_is_marked_without_send(conn, clean_slate):
    """§P3B-2: `telegram_notifications_enabled = false` skips the Telegram
    half exactly like a blocked user, but the in-app `notifications` row
    (and its readability via a future GET /notifications) is untouched."""
    user_id = await factories.make_user(conn)
    await conn.execute("UPDATE users SET telegram_notifications_enabled = false WHERE id = $1", user_id)
    notification_id = await _insert_notification(conn, user_id=user_id)

    bot = MagicMock()
    bot.send_message = AsyncMock()

    sent = await poll_loop(conn, bot)

    assert sent == 0
    bot.send_message.assert_not_awaited()
    row = await conn.fetchrow("SELECT telegram_sent_at FROM notifications WHERE id = $1", notification_id)
    assert row["telegram_sent_at"] is not None  # handled, not retried forever


async def test_one_users_disabled_preference_does_not_affect_another_users_delivery(conn, clean_slate):
    """§P3C Part 3: the preference is per-row (`users.telegram_notifications_enabled`),
    so disabling it for one user must never change the poller's behavior for
    any other user's pending notification in the same batch."""
    disabled_user_id = await factories.make_user(conn)
    await conn.execute("UPDATE users SET telegram_notifications_enabled = false WHERE id = $1", disabled_user_id)
    enabled_user_id = await factories.make_user(conn)

    disabled_notification_id = await _insert_notification(conn, user_id=disabled_user_id, title="For disabled user")
    enabled_notification_id = await _insert_notification(conn, user_id=enabled_user_id, title="For enabled user")

    bot = MagicMock()
    bot.send_message = AsyncMock()

    sent = await poll_loop(conn, bot)

    assert sent == 1  # only the enabled user's notification actually sent
    bot.send_message.assert_awaited_once()

    disabled_row = await conn.fetchrow(
        "SELECT telegram_sent_at FROM notifications WHERE id = $1", disabled_notification_id
    )
    enabled_row = await conn.fetchrow(
        "SELECT telegram_sent_at FROM notifications WHERE id = $1", enabled_notification_id
    )
    assert disabled_row["telegram_sent_at"] is not None  # handled, not sent
    assert enabled_row["telegram_sent_at"] is not None  # sent and marked


async def test_forbidden_error_marks_user_blocked_via_real_identity_service(conn, clean_slate):
    user_id = await factories.make_user(conn)
    notification_id = await _insert_notification(conn, user_id=user_id)

    bot = MagicMock()
    bot.send_message = AsyncMock(side_effect=TelegramForbiddenError(method=MagicMock(), message="blocked"))

    sent = await poll_loop(conn, bot)
    assert sent == 0

    user_row = await conn.fetchrow("SELECT bot_blocked_at FROM users WHERE id = $1", user_id)
    assert user_row["bot_blocked_at"] is not None

    notification_row = await conn.fetchrow(
        "SELECT telegram_sent_at FROM notifications WHERE id = $1", notification_id
    )
    assert notification_row["telegram_sent_at"] is not None
