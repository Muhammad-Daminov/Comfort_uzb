"""§P3B-2: `PATCH /auth/me/notification-settings` — a real HTTP-level test
(same pattern as tests/integration/test_idor_regression.py) because the
"a user can only touch their own row" guarantee here comes from
`current_user.id` always being derived from the signed session token
(`get_current_user`), never from client-supplied input — there is no
`user_id` in the request body at all, so this is IDOR-proof by
construction. This test proves that construction actually behaves that
way end-to-end, not just by reading the code.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from urllib.parse import urlencode

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from tests.integration import factories

pytestmark = pytest.mark.asyncio

BOT_TOKEN = "notif-settings-test-bot-token"


def _build_init_data(telegram_id: int) -> str:
    user = json.dumps({"id": telegram_id, "first_name": "Notif"})
    data = {"auth_date": str(int(time.time())), "user": user}
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    data["hash"] = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(data)


@pytest_asyncio.fixture
async def app_client():
    os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "")
    os.environ["BOT_TOKEN"] = BOT_TOKEN
    os.environ["SESSION_SECRET"] = "notif-settings-test-session-secret"
    os.environ["SIGNING_SECRET"] = "notif-settings-test-signing-secret"
    os.environ.setdefault("UPLOADS_ROOT", "/tmp")

    from app.db.pool import close_pool, create_pool
    from app.main import app

    await create_pool(os.environ["DATABASE_URL"])
    try:
        yield app
    finally:
        await close_pool()


async def _telegram_id_of(conn, user_id: int) -> int:
    row = await conn.fetchrow("SELECT telegram_id FROM users WHERE id = $1", user_id)
    return row["telegram_id"]


async def test_default_is_enabled(conn, clean_slate, app_client):
    user_id = await factories.make_user(conn)
    telegram_id = await _telegram_id_of(conn, user_id)

    async with AsyncClient(transport=ASGITransport(app=app_client), base_url="http://test") as client:
        r = await client.post("/auth/session", json={"initData": _build_init_data(telegram_id)})
        token = r.json()["token"]

        r = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert r.status_code == 200
    assert r.json()["telegram_notifications_enabled"] is True


async def test_user_can_disable_and_reenable_their_own_setting(conn, clean_slate, app_client):
    user_id = await factories.make_user(conn)
    telegram_id = await _telegram_id_of(conn, user_id)

    async with AsyncClient(transport=ASGITransport(app=app_client), base_url="http://test") as client:
        r = await client.post("/auth/session", json={"initData": _build_init_data(telegram_id)})
        token = r.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        r = await client.patch(
            "/auth/me/notification-settings", json={"telegram_notifications_enabled": False}, headers=headers
        )
        assert r.status_code == 200
        assert r.json()["telegram_notifications_enabled"] is False

        r = await client.get("/auth/me", headers=headers)
        assert r.json()["telegram_notifications_enabled"] is False

        r = await client.patch(
            "/auth/me/notification-settings", json={"telegram_notifications_enabled": True}, headers=headers
        )
        assert r.status_code == 200
        assert r.json()["telegram_notifications_enabled"] is True


async def test_updating_own_setting_never_touches_another_users_row(conn, clean_slate, app_client):
    user_a_id = await factories.make_user(conn)
    user_b_id = await factories.make_user(conn)
    telegram_a = await _telegram_id_of(conn, user_a_id)
    telegram_b = await _telegram_id_of(conn, user_b_id)

    async with AsyncClient(transport=ASGITransport(app=app_client), base_url="http://test") as client:
        r = await client.post("/auth/session", json={"initData": _build_init_data(telegram_a)})
        token_a = r.json()["token"]

        r = await client.patch(
            "/auth/me/notification-settings",
            json={"telegram_notifications_enabled": False},
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert r.status_code == 200

        r = await client.post("/auth/session", json={"initData": _build_init_data(telegram_b)})
        token_b = r.json()["token"]

        r = await client.get("/auth/me", headers={"Authorization": f"Bearer {token_b}"})

    assert r.status_code == 200
    assert r.json()["telegram_notifications_enabled"] is True  # untouched by A's update


async def test_unauthenticated_request_is_rejected(app_client):
    async with AsyncClient(transport=ASGITransport(app=app_client), base_url="http://test") as client:
        r = await client.patch("/auth/me/notification-settings", json={"telegram_notifications_enabled": False})
    assert r.status_code == 401
