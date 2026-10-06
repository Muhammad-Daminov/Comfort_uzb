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
    assert r.json() == {"status": "ok", "database": "ok"}


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
