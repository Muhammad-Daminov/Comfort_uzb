"""`GET /auth/me` — Phase 05 addition, exercised through the real
Repository function (same pattern as the rest of `tests/integration/`)."""
from __future__ import annotations

import pytest

from app.domains.identity import repository as identity_repository
from app.domains.identity import service as identity_service
from tests.integration import factories

pytestmark = pytest.mark.asyncio


async def test_get_by_id_returns_profile_fields(conn, clean_slate):
    user = await identity_service.get_or_create_user_from_telegram(
        conn, telegram_id=970101, first_name="Dilnoza", last_name=None, username="dilnoza"
    )
    # `users.phone` has a partial unique index (migration 0001_identity) and
    # `users` is deliberately never truncated between tests (see
    # tests/integration/conftest.py's clean_slate) — this literal must stay
    # distinct from every other hardcoded phone in the suite
    # (test_bot_identity.py uses +998901234567).
    await identity_service.record_phone(conn, user_id=user["id"], raw_phone="+998937654321")

    profile = await identity_repository.get_by_id(conn, user_id=user["id"])

    assert profile["id"] == user["id"]
    assert profile["first_name"] == "Dilnoza"
    assert profile["phone"] == "+998937654321"
    assert profile["role"] == "USER"
    assert profile["status"] == "ACTIVE"


async def test_get_by_id_returns_none_for_unknown_user(conn, clean_slate):
    profile = await identity_repository.get_by_id(conn, user_id=999999999)
    assert profile is None
