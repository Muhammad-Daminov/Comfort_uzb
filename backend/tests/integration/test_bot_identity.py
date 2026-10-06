"""Phase-04 identity flows through the real Service layer (`app.domains.
identity.service`) against a live Postgres — the same functions the bot's
handlers call, exercised as `comfort_app` like the rest of `tests/integration/`.
"""
from __future__ import annotations

import pytest

from app.domains.identity import service as identity_service
from tests.integration import factories

pytestmark = pytest.mark.asyncio


async def test_get_or_create_user_from_telegram_creates_once(conn, clean_slate):
    user_a = await identity_service.get_or_create_user_from_telegram(
        conn, telegram_id=800001, first_name="Ali", last_name=None, username="ali"
    )
    user_b = await identity_service.get_or_create_user_from_telegram(
        conn, telegram_id=800001, first_name="Ali", last_name=None, username="ali"
    )
    assert user_a["id"] == user_b["id"]
    assert user_a["role"] == "USER"


async def test_record_phone_normalizes_and_persists(conn, clean_slate):
    user = await identity_service.get_or_create_user_from_telegram(
        conn, telegram_id=800002, first_name="Vali", last_name=None, username=None
    )
    updated = await identity_service.record_phone(conn, user_id=user["id"], raw_phone="998 90 123-45-67")
    assert updated["phone"] == "+998901234567"


async def test_record_phone_rejects_invalid_shape(conn, clean_slate):
    user = await identity_service.get_or_create_user_from_telegram(
        conn, telegram_id=800003, first_name="Vali", last_name=None, username=None
    )
    with pytest.raises(identity_service.InvalidPhone):
        await identity_service.record_phone(conn, user_id=user["id"], raw_phone="12345")


async def test_mark_and_clear_bot_blocked_roundtrip(conn, clean_slate):
    user = await identity_service.get_or_create_user_from_telegram(
        conn, telegram_id=800004, first_name="Bek", last_name=None, username=None
    )

    marked = await identity_service.mark_bot_blocked(conn, telegram_id=800004)
    assert marked is True

    row = await conn.fetchrow("SELECT bot_blocked_at FROM users WHERE id = $1", user["id"])
    assert row["bot_blocked_at"] is not None

    marked_again = await identity_service.mark_bot_blocked(conn, telegram_id=800004)
    assert marked_again is False  # guarded no-op, matches the reservation-release contract

    cleared = await identity_service.clear_bot_blocked(conn, telegram_id=800004)
    assert cleared is True

    row = await conn.fetchrow("SELECT bot_blocked_at FROM users WHERE id = $1", user["id"])
    assert row["bot_blocked_at"] is None

    cleared_again = await identity_service.clear_bot_blocked(conn, telegram_id=800004)
    assert cleared_again is False
