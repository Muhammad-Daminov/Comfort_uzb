"""Regression: a foreign key that doesn't exist is bad *client* input, and
must surface as 422 — never as an unhandled asyncpg exception bubbling out
as HTTP 500.

Found by the full-project local verification pass by driving the real HTTP
API: `POST /cart/items` with an unknown `variant_id`, and
`POST`/`PATCH /admin/products` with an unknown `brand_id`, all raised
`asyncpg.exceptions.ForeignKeyViolationError` out of the Repository layer
with no Router-level guard, producing a 500. The sibling variant routes in
the same `admin_router.py` already carried exactly this guard, so the fix
was to extend the established pattern to the routes that were missing it —
not to introduce a new one.

Cart deliberately does NOT validate stock or price here: §7.3 /
docs/04_API_SPEC.md put that re-validation at checkout, and
`test_order_creation.py` covers it there. Only *existence* is at issue.
"""
from __future__ import annotations

import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from tests.integration import factories
from tests.integration.test_security_suite import (
    _build_init_data,
    _session_token,
    _telegram_id_of,
)

NONEXISTENT_ID = 987654321


@pytest_asyncio.fixture
async def app_client():
    os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "")
    os.environ["BOT_TOKEN"] = "sec-suite-bot-token"
    os.environ["SESSION_SECRET"] = "sec-suite-session-secret"
    os.environ["SIGNING_SECRET"] = "sec-suite-signing-secret"
    os.environ.setdefault("UPLOADS_ROOT", "/tmp")

    from app.db.pool import close_pool, create_pool
    from app.main import app

    await create_pool(os.environ["DATABASE_URL"])
    try:
        yield app
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_cart_add_unknown_variant_is_422_not_500(conn, clean_slate, app_client):
    user_id = await factories.make_user(conn, role="USER")
    telegram_id = await _telegram_id_of(conn, user_id)

    async with AsyncClient(transport=ASGITransport(app=app_client), base_url="http://test") as client:
        token = await _session_token(client, telegram_id)
        r = await client.post(
            "/cart/items",
            json={"variant_id": NONEXISTENT_ID, "quantity": 1},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert r.status_code == 422, r.text
    # The raw DB error must never reach the client.
    assert "ForeignKeyViolation" not in r.text
    assert "cart_items_variant_id_fkey" not in r.text


@pytest.mark.asyncio
async def test_admin_create_product_unknown_brand_is_422_not_500(conn, clean_slate, app_client):
    admin_id = await factories.make_user(conn, role="ADMIN")
    telegram_id = await _telegram_id_of(conn, admin_id)

    async with AsyncClient(transport=ASGITransport(app=app_client), base_url="http://test") as client:
        token = await _session_token(client, telegram_id)
        r = await client.post(
            "/admin/products",
            json={"name": "Orphan product", "brand_id": NONEXISTENT_ID},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert r.status_code == 422, r.text
    assert "ForeignKeyViolation" not in r.text
    assert "products_brand_id_fkey" not in r.text


@pytest.mark.asyncio
async def test_admin_update_product_unknown_brand_is_422_not_500(conn, clean_slate, app_client):
    admin_id = await factories.make_user(conn, role="ADMIN")
    telegram_id = await _telegram_id_of(conn, admin_id)
    brand_id = await factories.make_brand(conn, name="Real brand")
    product_id = await factories.make_product(conn, brand_id=brand_id, name="Real product")

    async with AsyncClient(transport=ASGITransport(app=app_client), base_url="http://test") as client:
        token = await _session_token(client, telegram_id)
        r = await client.patch(
            f"/admin/products/{product_id}",
            json={"brand_id": NONEXISTENT_ID},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert r.status_code == 422, r.text
    assert "ForeignKeyViolation" not in r.text


@pytest.mark.asyncio
async def test_cart_add_still_succeeds_for_a_real_variant(conn, clean_slate, app_client):
    """Guards against 'fix' by over-rejecting: the happy path must survive."""
    user_id = await factories.make_user(conn, role="USER")
    telegram_id = await _telegram_id_of(conn, user_id)
    brand_id = await factories.make_brand(conn, name="Cart brand")
    product_id = await factories.make_product(conn, brand_id=brand_id, name="Cart product")
    variant_id = await factories.make_variant(
        conn, product_id=product_id, sku="CART-FK-1", price=1000, stock_on_hand=5
    )

    async with AsyncClient(transport=ASGITransport(app=app_client), base_url="http://test") as client:
        token = await _session_token(client, telegram_id)
        r = await client.post(
            "/cart/items",
            json={"variant_id": variant_id, "quantity": 2},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert r.status_code == 200, r.text
    assert r.json()["variant_id"] == variant_id
