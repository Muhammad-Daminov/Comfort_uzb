"""Phase 07: audit-log listing (redaction, filtering, keyset pagination)
and settings GET/PUT roundtrip + audit participation."""
from __future__ import annotations

import pytest

from app.domains.owner import repository as owner_repository
from app.domains.owner import service as owner_service
from app.security.audit import record_audit
from tests.integration import factories

pytestmark = pytest.mark.asyncio


async def test_audit_listing_redacts_a_planted_sensitive_key(conn, clean_slate):
    actor_id = await factories.make_user(conn)
    await record_audit(
        conn, actor_id=actor_id, actor_role="OWNER", action="test.sensitive_probe",
        entity_type="probe", entity_id=1, new_data={"password": "hunter2", "note": "kept"},
    )

    rows = await owner_service.list_audit_logs(conn, action="test.sensitive_probe", limit=10)

    assert len(rows) == 1
    assert rows[0]["new_data"]["password"] == "[REDACTED]"
    assert rows[0]["new_data"]["note"] == "kept"


async def test_audit_listing_filters_by_action_and_entity_type(conn, clean_slate):
    actor_id = await factories.make_user(conn)
    await record_audit(conn, actor_id=actor_id, actor_role="OWNER", action="test.alpha", entity_type="probe", entity_id=1)
    await record_audit(conn, actor_id=actor_id, actor_role="OWNER", action="test.beta", entity_type="probe", entity_id=2)

    rows = await owner_service.list_audit_logs(conn, action="test.alpha", limit=10)

    assert all(r["action"] == "test.alpha" for r in rows)
    assert len(rows) == 1


async def test_audit_listing_keyset_pagination_does_not_repeat_rows(conn, clean_slate):
    actor_id = await factories.make_user(conn)
    for i in range(5):
        await record_audit(
            conn, actor_id=actor_id, actor_role="OWNER", action="test.paginate", entity_type="probe", entity_id=i
        )

    first_page = await owner_service.list_audit_logs(conn, action="test.paginate", limit=2)
    assert len(first_page) == 2
    cursor = owner_repository.encode_audit_cursor(first_page[-1]["created_at"], first_page[-1]["id"])

    second_page = await owner_service.list_audit_logs(conn, action="test.paginate", cursor=cursor, limit=2)
    assert len(second_page) == 2
    first_ids = {r["id"] for r in first_page}
    second_ids = {r["id"] for r in second_page}
    assert first_ids.isdisjoint(second_ids)


async def test_settings_put_then_get_roundtrip(conn, clean_slate):
    actor_id = await factories.make_user(conn)

    await owner_service.put_setting(conn, key="store_name", value="Comfort UZB Test", actor_id=actor_id, actor_role="OWNER")

    settings = await owner_service.get_settings(conn)
    assert settings["store_name"] == "Comfort UZB Test"


async def test_settings_put_is_audited(conn, clean_slate):
    actor_id = await factories.make_user(conn)

    await owner_service.put_setting(conn, key="maintenance_mode", value=False, actor_id=actor_id, actor_role="OWNER")

    audit_row = await conn.fetchrow(
        "SELECT * FROM audit_logs WHERE entity_type = 'store_settings' AND action = 'settings.update'"
    )
    assert audit_row is not None


async def test_settings_rejects_empty_key(conn, clean_slate):
    actor_id = await factories.make_user(conn)
    with pytest.raises(ValueError):
        await owner_service.put_setting(conn, key="", value="x", actor_id=actor_id, actor_role="OWNER")


async def test_settings_starts_empty_no_invented_content(conn, clean_slate):
    """Phase-07's explicit decision: zero pre-seeded settings keys — the
    TZ never specifies what a setting is, so nothing is invented."""
    settings = await owner_service.get_settings(conn)
    assert settings == {}
