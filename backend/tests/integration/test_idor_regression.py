"""Phase 08 IDOR regression: `GET /orders/{id}` — no prior test exercised
this specific check (`order.user_id != current_user.id` -> `orders.view.all`
or 403), even though the guard itself was already correct (Phase 03). This
is a real HTTP-level test (httpx.ASGITransport against the actual FastAPI
app), not a service-layer one, because the ownership check lives only in
`app/domains/commerce/orders/router.py`, not in a Service function.

Cart IDOR is covered separately and more directly in
tests/integration/test_cart_soft_delete.py::test_removing_another_users_item_is_a_safe_noop_not_idor
— cart mutations are already structurally IDOR-proof (cart_id is always
derived server-side from the authenticated user, never from client input),
so no Router-level test is needed there to prove the same thing twice.
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

from app.domains.commerce.orders import service as orders_service
from tests.integration import factories

pytestmark = pytest.mark.asyncio

BOT_TOKEN = "idor-test-bot-token"


def _build_init_data(telegram_id: int) -> str:
    user = json.dumps({"id": telegram_id, "first_name": "IDOR"})
    data = {"auth_date": str(int(time.time())), "user": user}
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    data["hash"] = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(data)


@pytest_asyncio.fixture
async def app_client():
    os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "")
    os.environ["BOT_TOKEN"] = BOT_TOKEN
    os.environ["SESSION_SECRET"] = "idor-test-session-secret"
    os.environ["SIGNING_SECRET"] = "idor-test-signing-secret"
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


async def test_user_cannot_view_another_users_order(conn, clean_slate, app_client):
    # Random telegram_ids (factories.make_user's default) — users is
    # deliberately never truncated between tests (see conftest.py), so a
    # hardcoded literal here would collide with a leftover row from an
    # earlier run of this same file, same lesson as Phase 05's phone-number
    # collision.
    owner_user_id = await factories.make_user(conn)
    other_user_id = await factories.make_user(conn)
    other_telegram_id = await _telegram_id_of(conn, other_user_id)

    brand_id = await factories.make_brand(conn, name="IdorBrand")
    product_id = await factories.make_product(conn, brand_id=brand_id, name="Idor Product")
    variant_id = await factories.make_variant(conn, product_id=product_id, sku="IDOR-SKU-1", price=10_000, stock_on_hand=5)
    order = await orders_service.create_order(
        conn, user_id=owner_user_id, lines=[orders_service.CheckoutLine(variant_id=variant_id, quantity=1)]
    )

    async with AsyncClient(transport=ASGITransport(app=app_client), base_url="http://test") as client:
        r = await client.post("/auth/session", json={"initData": _build_init_data(other_telegram_id)})
        assert r.status_code == 200
        other_token = r.json()["token"]

        r = await client.get(f"/orders/{order['id']}", headers={"Authorization": f"Bearer {other_token}"})

    assert r.status_code == 403


async def test_user_can_view_their_own_order(conn, clean_slate, app_client):
    owner_user_id = await factories.make_user(conn)
    telegram_id = await _telegram_id_of(conn, owner_user_id)

    brand_id = await factories.make_brand(conn, name="IdorBrand2")
    product_id = await factories.make_product(conn, brand_id=brand_id, name="Idor Product 2")
    variant_id = await factories.make_variant(conn, product_id=product_id, sku="IDOR-SKU-2", price=10_000, stock_on_hand=5)
    order = await orders_service.create_order(
        conn, user_id=owner_user_id, lines=[orders_service.CheckoutLine(variant_id=variant_id, quantity=1)]
    )

    async with AsyncClient(transport=ASGITransport(app=app_client), base_url="http://test") as client:
        r = await client.post("/auth/session", json={"initData": _build_init_data(telegram_id)})
        token = r.json()["token"]

        r = await client.get(f"/orders/{order['id']}", headers={"Authorization": f"Bearer {token}"})

    assert r.status_code == 200
    assert r.json()["id"] == order["id"]
