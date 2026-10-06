"""Phase 07: owner mutations' audit rows roll back with the rest of the
transaction — same pattern as test_admin_catalog_audit_rollback.py."""
from __future__ import annotations

import pytest

from app.domains.owner import service as owner_service
from tests.integration import factories

pytestmark = pytest.mark.asyncio


async def test_admin_create_audit_rolls_back_with_outer_transaction(conn, clean_slate):
    actor_id = await factories.make_user(conn)
    telegram_id = 900123456

    tx = conn.transaction()
    await tx.start()
    try:
        admin = await owner_service.create_admin(
            conn, telegram_id=telegram_id, first_name="Rollback Admin", last_name=None, username=None,
            actor_id=actor_id, actor_role="OWNER",
        )
        raise RuntimeError("forced failure after admin create to test rollback")
    except RuntimeError:
        await tx.rollback()

    user_row = await conn.fetchrow("SELECT id FROM users WHERE id = $1", admin["id"])
    assert user_row is None

    audit_row = await conn.fetchrow(
        "SELECT * FROM audit_logs WHERE entity_type = 'user' AND entity_id = $1 AND action = 'admin.create'",
        admin["id"],
    )
    assert audit_row is None


async def test_settings_put_audit_rolls_back_with_outer_transaction(conn, clean_slate):
    actor_id = await factories.make_user(conn)

    tx = conn.transaction()
    await tx.start()
    try:
        await owner_service.put_setting(conn, key="rollback_test", value="x", actor_id=actor_id, actor_role="OWNER")
        raise RuntimeError("forced failure after settings put to test rollback")
    except RuntimeError:
        await tx.rollback()

    setting_row = await conn.fetchrow("SELECT key FROM store_settings WHERE key = 'rollback_test'")
    assert setting_row is None

    audit_row = await conn.fetchrow(
        "SELECT * FROM audit_logs WHERE entity_type = 'store_settings' AND action = 'settings.update'"
    )
    assert audit_row is None
