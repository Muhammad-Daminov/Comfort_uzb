"""Phase 07: admin create/deactivate/reactivate — never creates a second
OWNER, never touches USER rows, structural role-hardcoding enforced.

Note: `actor_id`/`actor_role` here are audit-trail labels only — permission
enforcement happens at the Router layer (`require_permission`), not in
`service.py`, so these tests exercise the service logic directly with any
existing user id as the "actor," same as every other Phase 03-06 service-
layer test. They never create a *second* `role='OWNER'` row — ADR-11's
partial unique index only allows one, and migration 0002 already seeded it
(`OWNER_TELEGRAM_ID`); tests that need a genuine OWNER row query the
existing seeded one instead of minting a new one.
"""
from __future__ import annotations

import secrets

import pytest

from app.domains.owner import service as owner_service
from tests.integration import factories

pytestmark = pytest.mark.asyncio


def _random_telegram_id() -> int:
    return secrets.randbelow(900_000_000) + 100_000_000


async def _get_seeded_owner(conn) -> dict:
    row = await conn.fetchrow("SELECT id, telegram_id FROM users WHERE role = 'OWNER' AND deleted_at IS NULL")
    assert row is not None, "expected the ADR-11 seeded OWNER row (migration 0002) to exist"
    return dict(row)


async def test_create_admin_hardcodes_role(conn, clean_slate):
    actor_id = await factories.make_user(conn)
    telegram_id = _random_telegram_id()

    admin = await owner_service.create_admin(
        conn, telegram_id=telegram_id, first_name="New", last_name=None, username=None,
        actor_id=actor_id, actor_role="OWNER",
    )

    assert admin["role"] == "ADMIN"
    row = await conn.fetchrow("SELECT role FROM users WHERE id = $1", admin["id"])
    assert row["role"] == "ADMIN"

    audit_row = await conn.fetchrow(
        "SELECT * FROM audit_logs WHERE entity_type = 'user' AND entity_id = $1 AND action = 'admin.create'",
        admin["id"],
    )
    assert audit_row is not None


async def test_create_admin_cannot_reassign_the_owner(conn, clean_slate):
    actor_id = await factories.make_user(conn)
    owner = await _get_seeded_owner(conn)

    with pytest.raises(owner_service.CannotModifyOwner):
        await owner_service.create_admin(
            conn, telegram_id=owner["telegram_id"], first_name=None, last_name=None, username=None,
            actor_id=actor_id, actor_role="OWNER",
        )

    role_row = await conn.fetchrow("SELECT role FROM users WHERE id = $1", owner["id"])
    assert role_row["role"] == "OWNER"  # untouched


async def test_deactivate_and_reactivate_admin_roundtrip(conn, clean_slate):
    actor_id = await factories.make_user(conn)
    admin_id = await factories.make_user(conn, role="ADMIN")

    deactivated = await owner_service.set_admin_status(
        conn, user_id=admin_id, status="DEACTIVATED", actor_id=actor_id, actor_role="OWNER"
    )
    assert deactivated["status"] == "DEACTIVATED"

    reactivated = await owner_service.set_admin_status(
        conn, user_id=admin_id, status="ACTIVE", actor_id=actor_id, actor_role="OWNER"
    )
    assert reactivated["status"] == "ACTIVE"

    audit_rows = await conn.fetch(
        "SELECT action FROM audit_logs WHERE entity_type = 'user' AND entity_id = $1 AND action = 'admin.status_change' ORDER BY created_at",
        admin_id,
    )
    assert len(audit_rows) == 2


async def test_cannot_deactivate_the_owner_via_admin_management(conn, clean_slate):
    actor_id = await factories.make_user(conn)
    owner = await _get_seeded_owner(conn)

    with pytest.raises(LookupError):
        await owner_service.set_admin_status(
            conn, user_id=owner["id"], status="DEACTIVATED", actor_id=actor_id, actor_role="OWNER"
        )

    row = await conn.fetchrow("SELECT status FROM users WHERE id = $1", owner["id"])
    assert row["status"] == "ACTIVE"  # untouched — the guarded UPDATE's WHERE role='ADMIN' excluded it


async def test_cannot_deactivate_a_plain_user_via_admin_management(conn, clean_slate):
    actor_id = await factories.make_user(conn)
    user_id = await factories.make_user(conn, role="USER")

    with pytest.raises(LookupError):
        await owner_service.set_admin_status(
            conn, user_id=user_id, status="DEACTIVATED", actor_id=actor_id, actor_role="OWNER"
        )
