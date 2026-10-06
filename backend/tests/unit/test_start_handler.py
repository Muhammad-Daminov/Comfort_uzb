"""Unit tests for `/start` and contact-share handlers — mocked pool/conn
and a lightweight fake Message (real aiogram Message construction isn't
needed to verify the handler's own branching/reuse-of-Service-layer logic).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.handlers import start as start_handlers

pytestmark = pytest.mark.asyncio


class FakeUser:
    def __init__(self, user_id=555, first_name="Ali", last_name=None, username="ali"):
        self.id = user_id
        self.first_name = first_name
        self.last_name = last_name
        self.username = username


class FakeContact:
    def __init__(self, phone_number="+998901234567", user_id=555):
        self.phone_number = phone_number
        self.user_id = user_id


class FakeMessage:
    def __init__(self, from_user=None, contact=None):
        self.from_user = from_user
        self.contact = contact
        self.answer = AsyncMock()


class FakeConn:
    def __init__(self, phone=None):
        self.phone = phone

    async def fetchrow(self, query, *args):
        return {"phone": self.phone}


def _fake_pool(conn):
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool


async def test_start_new_user_without_phone_asks_for_contact(monkeypatch):
    conn = FakeConn(phone=None)
    pool = _fake_pool(conn)
    message = FakeMessage(from_user=FakeUser())

    monkeypatch.setattr(
        "app.domains.identity.service.get_or_create_user_from_telegram",
        AsyncMock(return_value={"id": 1, "telegram_id": 555, "role": "USER", "status": "ACTIVE"}),
    )
    monkeypatch.setattr("app.domains.identity.service.clear_bot_blocked", AsyncMock(return_value=False))

    await start_handlers.handle_start(message, pool, "https://miniapp.example")

    message.answer.assert_awaited_once()
    args, kwargs = message.answer.call_args
    assert "Xush kelibsiz" in args[0] or "xush kelibsiz" in args[0].lower()


async def test_start_existing_user_with_phone_shows_welcome_back(monkeypatch):
    conn = FakeConn(phone="+998901234567")
    pool = _fake_pool(conn)
    message = FakeMessage(from_user=FakeUser())

    monkeypatch.setattr(
        "app.domains.identity.service.get_or_create_user_from_telegram",
        AsyncMock(return_value={"id": 1, "telegram_id": 555, "role": "USER", "status": "ACTIVE"}),
    )
    monkeypatch.setattr("app.domains.identity.service.clear_bot_blocked", AsyncMock(return_value=False))

    await start_handlers.handle_start(message, pool, "https://miniapp.example")

    message.answer.assert_awaited_once()


async def test_start_reactivates_previously_blocked_user(monkeypatch):
    conn = FakeConn(phone="+998901234567")
    pool = _fake_pool(conn)
    message = FakeMessage(from_user=FakeUser())

    monkeypatch.setattr(
        "app.domains.identity.service.get_or_create_user_from_telegram",
        AsyncMock(return_value={"id": 1, "telegram_id": 555, "role": "USER", "status": "ACTIVE"}),
    )
    monkeypatch.setattr("app.domains.identity.service.clear_bot_blocked", AsyncMock(return_value=True))

    await start_handlers.handle_start(message, pool, "https://miniapp.example")

    assert message.answer.await_count == 2  # reactivation message + welcome-back


async def test_start_with_no_from_user_is_ignored():
    pool = MagicMock()
    message = FakeMessage(from_user=None)

    await start_handlers.handle_start(message, pool, "https://miniapp.example")

    message.answer.assert_not_awaited()


async def test_contact_share_records_phone(monkeypatch):
    conn = FakeConn()
    pool = _fake_pool(conn)
    message = FakeMessage(from_user=FakeUser(), contact=FakeContact())

    monkeypatch.setattr(
        "app.domains.identity.service.get_or_create_user_from_telegram",
        AsyncMock(return_value={"id": 1, "telegram_id": 555, "role": "USER", "status": "ACTIVE"}),
    )
    record_phone = AsyncMock(return_value={"id": 1, "phone": "+998901234567"})
    monkeypatch.setattr("app.domains.identity.service.record_phone", record_phone)

    await start_handlers.handle_contact(message, pool)

    record_phone.assert_awaited_once_with(conn, user_id=1, raw_phone="+998901234567")
    message.answer.assert_awaited_once()


async def test_contact_from_someone_else_is_rejected(monkeypatch):
    pool = MagicMock()
    message = FakeMessage(from_user=FakeUser(user_id=555), contact=FakeContact(user_id=999))

    await start_handlers.handle_contact(message, pool)

    message.answer.assert_awaited_once()
    args, _ = message.answer.call_args
    assert "noto'g'ri" in args[0] or "format" in args[0].lower()


async def test_contact_with_invalid_phone_shows_error(monkeypatch):
    conn = FakeConn()
    pool = _fake_pool(conn)
    message = FakeMessage(from_user=FakeUser(), contact=FakeContact(phone_number="not-a-phone"))

    monkeypatch.setattr(
        "app.domains.identity.service.get_or_create_user_from_telegram",
        AsyncMock(return_value={"id": 1, "telegram_id": 555, "role": "USER", "status": "ACTIVE"}),
    )
    from app.domains.identity.service import InvalidPhone

    monkeypatch.setattr(
        "app.domains.identity.service.record_phone", AsyncMock(side_effect=InvalidPhone("bad"))
    )

    await start_handlers.handle_contact(message, pool)

    message.answer.assert_awaited_once()


# --- audit regressions (docs/11_FULL_SYSTEM_AUDIT_REPORT.md M8) --------------


async def test_address_book_contact_without_telegram_user_id_is_rejected(monkeypatch):
    """A contact card for someone who is not on Telegram has `user_id=None`;
    it is never the sender's own number and must not be stored as such."""
    record_phone = AsyncMock()
    monkeypatch.setattr("app.domains.identity.service.record_phone", record_phone)
    message = FakeMessage(from_user=FakeUser(user_id=555), contact=FakeContact(user_id=None))

    await start_handlers.handle_contact(message, MagicMock())

    record_phone.assert_not_awaited()
    message.answer.assert_awaited_once()


async def test_typed_phone_number_is_recorded(monkeypatch):
    conn = FakeConn()
    pool = _fake_pool(conn)
    message = FakeMessage(from_user=FakeUser())
    message.text = "+998 90 123 45 67"
    monkeypatch.setattr(
        "app.domains.identity.service.get_or_create_user_from_telegram",
        AsyncMock(return_value={"id": 1, "telegram_id": 555, "role": "USER", "status": "ACTIVE"}),
    )
    record_phone = AsyncMock(return_value={"id": 1, "phone": "+998901234567"})
    monkeypatch.setattr("app.domains.identity.service.record_phone", record_phone)

    await start_handlers.handle_typed_phone(message, pool)

    record_phone.assert_awaited_once_with(conn, user_id=1, raw_phone="+998 90 123 45 67")


def test_typed_phone_filter_matches_only_uzbek_numbers():
    from aiogram.types import Message as _M  # noqa: F401 — filter is a plain MagicFilter

    check = start_handlers._TYPED_PHONE
    assert check.resolve(MagicMock(text="+998901234567"))
    assert check.resolve(MagicMock(text="998 90 123-45-67"))
    assert not check.resolve(MagicMock(text="hello"))
    assert not check.resolve(MagicMock(text="+1 555 0100"))


async def test_phone_already_bound_to_another_account_gets_specific_message(monkeypatch):
    import asyncpg

    conn = FakeConn()
    pool = _fake_pool(conn)
    message = FakeMessage(from_user=FakeUser(), contact=FakeContact())
    monkeypatch.setattr(
        "app.domains.identity.service.get_or_create_user_from_telegram",
        AsyncMock(return_value={"id": 1, "telegram_id": 555, "role": "USER", "status": "ACTIVE"}),
    )
    monkeypatch.setattr(
        "app.domains.identity.service.record_phone",
        AsyncMock(side_effect=asyncpg.exceptions.UniqueViolationError("dup")),
    )

    await start_handlers.handle_contact(message, pool)

    from bot.locales import uz

    message.answer.assert_awaited_once()
    assert message.answer.call_args.args[0] == uz.PHONE_ALREADY_USED
