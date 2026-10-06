"""Regression: a duplicate brand/color name is a client-side conflict (409),
not an unhandled `asyncpg.UniqueViolationError` escaping as HTTP 500.

Found by the hardening pass's systematic constraint sweep, which drove every
externally reachable mutating endpoint with inputs designed to violate each
constraint class (FK, unique, check, not-null, invalid state transition).
Four routes had no guard: POST/PATCH on /admin/brands and /admin/colors.

`brands_name_idx` and `colors_name_idx` are UNIQUE ... WHERE deleted_at IS
NULL, so re-using an ARCHIVED name is legitimate and must keep working —
that behaviour is pinned here too, so the fix cannot be "reject any repeat".

Only `UniqueViolationError` is mapped. Any other PostgresError still becomes
a 500, because it would represent a genuine server fault, and blanket-
catching database errors would hide exactly the kind of bug this suite exists
to surface.
"""
from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from tests.integration import factories
from tests.integration.test_security_suite import _session_token, _telegram_id_of


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


def _client(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _admin_headers(conn, client: AsyncClient) -> dict[str, str]:
    admin_id = await factories.make_user(conn, role="ADMIN")
    telegram_id = await _telegram_id_of(conn, admin_id)
    token = await _session_token(client, telegram_id)
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
@pytest.mark.parametrize("resource", ["brands", "colors"])
async def test_duplicate_name_on_create_is_409_not_500(conn, clean_slate, app_client, resource):
    async with _client(app_client) as client:
        headers = await _admin_headers(conn, client)
        name = f"Dup-{uuid.uuid4().hex[:8]}"
        first = await client.post(f"/admin/{resource}", json={"name": name}, headers=headers)
        assert first.status_code in (200, 201), first.text

        second = await client.post(f"/admin/{resource}", json={"name": name}, headers=headers)

    assert second.status_code == 409, second.text
    assert "UniqueViolation" not in second.text
    assert "_name_idx" not in second.text


@pytest.mark.asyncio
@pytest.mark.parametrize("resource", ["brands", "colors"])
async def test_duplicate_name_on_update_is_409_not_500(conn, clean_slate, app_client, resource):
    async with _client(app_client) as client:
        headers = await _admin_headers(conn, client)
        taken = f"Taken-{uuid.uuid4().hex[:8]}"
        other = f"Other-{uuid.uuid4().hex[:8]}"
        await client.post(f"/admin/{resource}", json={"name": taken}, headers=headers)
        created = await client.post(f"/admin/{resource}", json={"name": other}, headers=headers)
        target_id = created.json()["id"]

        clash = await client.patch(f"/admin/{resource}/{target_id}", json={"name": taken}, headers=headers)

    assert clash.status_code == 409, clash.text
    assert "UniqueViolation" not in clash.text


@pytest.mark.asyncio
@pytest.mark.parametrize("resource", ["brands", "colors"])
async def test_an_archived_name_can_be_reused(conn, clean_slate, app_client, resource):
    """Guards against over-rejecting: the unique index is partial, so a name
    freed by archiving must still be available."""
    async with _client(app_client) as client:
        headers = await _admin_headers(conn, client)
        name = f"Recycle-{uuid.uuid4().hex[:8]}"
        created = await client.post(f"/admin/{resource}", json={"name": name}, headers=headers)
        archived = await client.post(
            f"/admin/{resource}/{created.json()['id']}/archive", headers=headers
        )
        assert archived.status_code in (200, 204), archived.text

        recreated = await client.post(f"/admin/{resource}", json={"name": name}, headers=headers)

    assert recreated.status_code in (200, 201), recreated.text
