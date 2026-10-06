"""Phase 09: `/health/live` and `/health/ready` (app/health.py) — new
endpoints, no prior coverage. Constructed the same way as every other
HTTP-level test in this suite (create_pool/close_pool directly, bypassing
`app/main.py`'s lifespan — which is also why these tests never need
bot-specific env vars: the bot wiring lives inside that lifespan, not at
import time)."""
from __future__ import annotations

import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.domains.commerce.orders import service as orders_service
from tests.integration import factories

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def app_client():
    os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "")
    os.environ["BOT_TOKEN"] = "health-test-bot-token"
    os.environ["SESSION_SECRET"] = "health-test-session-secret"
    os.environ["SIGNING_SECRET"] = "health-test-signing-secret"
    os.environ.setdefault("UPLOADS_ROOT", "/tmp")

    from app.db.pool import close_pool, create_pool
    from app.main import app

    await create_pool(os.environ["DATABASE_URL"])
    try:
        yield app
    finally:
        await close_pool()


async def test_liveness_never_touches_database(app_client):
    async with AsyncClient(transport=ASGITransport(app=app_client), base_url="http://test") as client:
        r = await client.get("/health/live")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_readiness_reports_database_ok(app_client):
    async with AsyncClient(transport=ASGITransport(app=app_client), base_url="http://test") as client:
        r = await client.get("/health/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    # §13.4 "DB + disk + worker holati" — disk/worker are folded into this
    # same endpoint (app/health.py); exact disk percentage is
    # environment-dependent, so only the shape/status enum is asserted.
    assert body["disk"]["status"] in ("ok", "critical", "unknown")
    if body["disk"]["status"] != "unknown":
        assert isinstance(body["disk"]["percent_used"], (int, float))
    assert body["worker"]["status"] in ("ok", "stale")
    assert isinstance(body["worker"]["reservation_expiry_backlog"], int)


async def test_readiness_reports_worker_stale_when_an_expired_reservation_was_never_released(app_client, clean_slate):
    """Proves the §13.4 worker-status signal is real, not a fabricated
    always-"ok" — backdates a genuine reservation past its TTL (simulating
    the reservation-expiry worker having failed to run) and asserts
    /health/ready actually notices."""
    from app.db.pool import get_pool

    pool = get_pool()
    async with pool.acquire() as conn:
        user_id = await factories.make_user(conn)
        brand_id = await factories.make_brand(conn, name="HealthWorkerStaleBrand")
        product_id = await factories.make_product(conn, brand_id=brand_id, name="Health Worker Stale Product")
        variant_id = await factories.make_variant(
            conn, product_id=product_id, sku="HEALTH-STALE-1", price=10_000, stock_on_hand=5
        )
        await orders_service.create_order(
            conn, user_id=user_id, lines=[orders_service.CheckoutLine(variant_id=variant_id, quantity=1)]
        )
        # Simulate the worker having missed this one by a wide margin.
        await conn.execute(
            "UPDATE stock_reservations SET expires_at = now() - interval '1 hour' WHERE variant_id = $1",
            variant_id,
        )

    async with AsyncClient(transport=ASGITransport(app=app_client), base_url="http://test") as client:
        r = await client.get("/health/ready")

    assert r.status_code == 200
    body = r.json()
    assert body["worker"]["status"] == "stale"
    assert body["worker"]["reservation_expiry_backlog"] >= 1


async def test_readiness_reports_503_when_pool_not_initialized():
    # Deliberately does not use app_client (no create_pool call at all) —
    # exercises the RuntimeError branch of app/health.py::readiness.
    os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "")
    os.environ["BOT_TOKEN"] = "health-test-bot-token-2"
    os.environ["SESSION_SECRET"] = "health-test-session-secret-2"
    os.environ["SIGNING_SECRET"] = "health-test-signing-secret-2"
    os.environ.setdefault("UPLOADS_ROOT", "/tmp")

    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/health/ready")
    assert r.status_code == 503
    assert r.json()["status"] == "not_ready"
