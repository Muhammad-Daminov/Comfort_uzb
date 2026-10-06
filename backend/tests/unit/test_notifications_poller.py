"""Unit tests for the notification outbox poller (ADR-016) — mocked
asyncpg connection and aiogram Bot, no live DB or Telegram needed to verify
the guarded/idempotent/blocked-user branching logic itself."""
from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNetworkError, TelegramRetryAfter

from bot.notifications.poller import poll_loop

pytestmark = pytest.mark.asyncio


def _row(**overrides):
    base = {
        "id": 1,
        "title": "Buyurtma tasdiqlandi",
        "body": "CU-ABC123",
        "telegram_id": 555,
        "bot_blocked_at": None,
        "telegram_notifications_enabled": True,
    }
    base.update(overrides)
    return base


class FakeConn:
    def __init__(self, rows, mark_sent_results=None):
        self._rows = rows
        self.fetch = AsyncMock(return_value=rows)
        self.marked_ids = []
        self._mark_sent_results = mark_sent_results or {}

    async def fetchrow(self, query, *args):
        if "UPDATE notifications" in query:
            notification_id = args[0]
            self.marked_ids.append(notification_id)
            if self._mark_sent_results.get(notification_id) is False:
                return None
            return {"id": notification_id}
        raise AssertionError(f"unexpected query: {query}")

    async def execute(self, query, *args):
        return "UPDATE 1"

    @asynccontextmanager
    async def transaction(self):
        # The batch runs inside one transaction (FOR UPDATE SKIP LOCKED needs
        # it) — the fake just records that the poller opened one.
        self.in_transaction = True
        yield
        self.in_transaction = False


async def test_sends_unsent_notification_and_marks_it(monkeypatch):
    conn = FakeConn([_row()])
    bot = MagicMock()
    bot.send_message = AsyncMock()

    sent = await poll_loop(conn, bot)

    assert sent == 1
    bot.send_message.assert_awaited_once()
    assert conn.marked_ids == [1]


async def test_blocked_user_row_marked_without_send():
    conn = FakeConn([_row(bot_blocked_at="2026-01-01T00:00:00Z")])
    bot = MagicMock()
    bot.send_message = AsyncMock()

    sent = await poll_loop(conn, bot)

    assert sent == 0  # marked handled, but not counted as "sent"
    bot.send_message.assert_not_awaited()
    assert conn.marked_ids == [1]


async def test_notifications_disabled_row_marked_without_send():
    conn = FakeConn([_row(telegram_notifications_enabled=False)])
    bot = MagicMock()
    bot.send_message = AsyncMock()

    sent = await poll_loop(conn, bot)

    assert sent == 0  # marked handled, but not counted as "sent"
    bot.send_message.assert_not_awaited()
    assert conn.marked_ids == [1]


async def test_forbidden_error_marks_user_blocked_and_row_handled(monkeypatch):
    conn = FakeConn([_row()])
    bot = MagicMock()
    bot.send_message = AsyncMock(side_effect=TelegramForbiddenError(method=MagicMock(), message="blocked"))

    mark_blocked = AsyncMock(return_value=True)
    monkeypatch.setattr("app.domains.identity.service.mark_bot_blocked", mark_blocked)

    sent = await poll_loop(conn, bot)

    assert sent == 0
    mark_blocked.assert_awaited_once_with(conn, telegram_id=555)
    assert conn.marked_ids == [1]


async def test_no_unsent_rows_is_a_noop():
    conn = FakeConn([])
    bot = MagicMock()
    bot.send_message = AsyncMock()

    sent = await poll_loop(conn, bot)

    assert sent == 0
    bot.send_message.assert_not_awaited()
    assert conn.marked_ids == []


async def test_batch_is_fetched_with_skip_locked_inside_a_transaction():
    """Two API workers poll the same table; only a locked fetch keeps a row
    with exactly one of them (regression: both sent every notification)."""
    conn = FakeConn([_row()])
    bot = MagicMock()
    bot.send_message = AsyncMock()

    await poll_loop(conn, bot)

    query = conn.fetch.await_args.args[0]
    assert "FOR UPDATE OF n SKIP LOCKED" in query
    assert "u.deleted_at IS NULL" in query
    assert conn.in_transaction is False  # transaction opened and closed


async def test_permanent_bad_request_marks_row_handled_not_retried_forever():
    conn = FakeConn([_row(id=7)])
    bot = MagicMock()
    bot.send_message = AsyncMock(side_effect=TelegramBadRequest(method=MagicMock(), message="chat not found"))

    sent = await poll_loop(conn, bot)

    assert sent == 0
    assert conn.marked_ids == [7]  # handled once, never re-fetched every 5s


async def test_transient_network_error_leaves_row_for_retry():
    conn = FakeConn([_row(id=8), _row(id=9)])
    bot = MagicMock()
    bot.send_message = AsyncMock(side_effect=[TelegramNetworkError(method=MagicMock(), message="timeout"), None])

    sent = await poll_loop(conn, bot)

    assert sent == 1
    assert conn.marked_ids == [9]  # 8 stays unsent for the next cycle


async def test_retry_after_pauses_and_stops_the_batch(monkeypatch):
    conn = FakeConn([_row(id=1), _row(id=2)])
    bot = MagicMock()
    bot.send_message = AsyncMock(side_effect=TelegramRetryAfter(method=MagicMock(), message="flood", retry_after=3))
    sleep = AsyncMock()
    monkeypatch.setattr("bot.notifications.poller.asyncio.sleep", sleep)

    sent = await poll_loop(conn, bot)

    assert sent == 0
    sleep.assert_awaited_once_with(3)
    assert bot.send_message.await_count == 1  # rest of the batch not hammered
    assert conn.marked_ids == []
