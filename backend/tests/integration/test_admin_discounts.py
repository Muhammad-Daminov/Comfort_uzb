"""§P2-4: owner-only discount management. No new discount semantics — CRUD
over the exact discounts/discount_targets model from migration 0005_pricing.
RBAC: `discounts.manage` (migration 0020) is OWNER-only, ADMIN excluded."""
from __future__ import annotations

import pytest

from app.domains.pricing import service as pricing_service
from app.security.permissions import has_permission
from tests.integration import factories


async def _get_seeded_owner_id(conn) -> int:
    row = await conn.fetchrow("SELECT id FROM users WHERE role = 'OWNER' AND deleted_at IS NULL")
    assert row is not None, "expected the ADR-11 seeded OWNER row (migration 0002) to exist"
    return row["id"]

pytestmark = pytest.mark.asyncio


async def test_discounts_manage_is_owner_only(conn, clean_slate):
    assert await has_permission(conn, "OWNER", "discounts.manage") is True
    assert await has_permission(conn, "ADMIN", "discounts.manage") is False
    assert await has_permission(conn, "USER", "discounts.manage") is False


async def test_create_discount_with_all_target(conn, clean_slate):
    owner_id = await _get_seeded_owner_id(conn)
    discount = await pricing_service.admin_create_discount(
        conn, name="Summer sale", kind="PERCENT", value=10, starts_at=None, ends_at=None, priority=0,
        targets=[("ALL", None)], actor_id=owner_id, actor_role="OWNER",
    )
    assert discount["kind"] == "PERCENT"
    assert discount["value"] == 10
    assert discount["is_active"] is True
    assert len(discount["targets"]) == 1
    assert discount["targets"][0]["target_type"] == "ALL"


async def test_percent_value_over_100_rejected(conn, clean_slate):
    owner_id = await _get_seeded_owner_id(conn)
    with pytest.raises(pricing_service.InvalidDiscount):
        await pricing_service.admin_create_discount(
            conn, name="Bad", kind="PERCENT", value=150, starts_at=None, ends_at=None, priority=0,
            targets=[], actor_id=owner_id, actor_role="OWNER",
        )


async def test_negative_value_rejected(conn, clean_slate):
    owner_id = await _get_seeded_owner_id(conn)
    with pytest.raises(pricing_service.InvalidDiscount):
        await pricing_service.admin_create_discount(
            conn, name="Bad", kind="FIXED", value=-1, starts_at=None, ends_at=None, priority=0,
            targets=[], actor_id=owner_id, actor_role="OWNER",
        )


async def test_target_without_id_rejected_for_non_all(conn, clean_slate):
    owner_id = await _get_seeded_owner_id(conn)
    with pytest.raises(pricing_service.InvalidDiscount):
        await pricing_service.admin_create_discount(
            conn, name="Bad", kind="FIXED", value=1000, starts_at=None, ends_at=None, priority=0,
            targets=[("PRODUCT", None)], actor_id=owner_id, actor_role="OWNER",
        )


async def test_all_target_with_id_rejected(conn, clean_slate):
    owner_id = await _get_seeded_owner_id(conn)
    with pytest.raises(pricing_service.InvalidDiscount):
        await pricing_service.admin_create_discount(
            conn, name="Bad", kind="FIXED", value=1000, starts_at=None, ends_at=None, priority=0,
            targets=[("ALL", 1)], actor_id=owner_id, actor_role="OWNER",
        )


async def test_update_discount_fields(conn, clean_slate):
    owner_id = await _get_seeded_owner_id(conn)
    discount = await pricing_service.admin_create_discount(
        conn, name="Original", kind="FIXED", value=1000, starts_at=None, ends_at=None, priority=0,
        targets=[], actor_id=owner_id, actor_role="OWNER",
    )
    updated = await pricing_service.admin_update_discount(
        conn, discount_id=discount["id"], name="Renamed", kind=None, value=2000, starts_at=None, ends_at=None,
        priority=None, set_starts_at=False, set_ends_at=False, actor_id=owner_id, actor_role="OWNER",
    )
    assert updated["name"] == "Renamed"
    assert updated["value"] == 2000
    assert updated["kind"] == "FIXED"  # untouched


async def test_update_missing_discount_raises_lookup_error(conn, clean_slate):
    owner_id = await _get_seeded_owner_id(conn)
    with pytest.raises(LookupError):
        await pricing_service.admin_update_discount(
            conn, discount_id=999999, name="X", kind=None, value=None, starts_at=None, ends_at=None,
            priority=None, set_starts_at=False, set_ends_at=False, actor_id=owner_id, actor_role="OWNER",
        )


async def test_activate_deactivate_discount(conn, clean_slate):
    owner_id = await _get_seeded_owner_id(conn)
    discount = await pricing_service.admin_create_discount(
        conn, name="Toggle me", kind="FIXED", value=500, starts_at=None, ends_at=None, priority=0,
        targets=[], actor_id=owner_id, actor_role="OWNER",
    )
    assert discount["is_active"] is True

    deactivated = await pricing_service.admin_set_discount_active(
        conn, discount_id=discount["id"], is_active=False, actor_id=owner_id, actor_role="OWNER"
    )
    assert deactivated["is_active"] is False

    reactivated = await pricing_service.admin_set_discount_active(
        conn, discount_id=discount["id"], is_active=True, actor_id=owner_id, actor_role="OWNER"
    )
    assert reactivated["is_active"] is True


async def test_add_and_remove_discount_target(conn, clean_slate):
    owner_id = await _get_seeded_owner_id(conn)
    brand_id = await factories.make_brand(conn, name="DiscountBrand")
    discount = await pricing_service.admin_create_discount(
        conn, name="Brand sale", kind="PERCENT", value=5, starts_at=None, ends_at=None, priority=0,
        targets=[], actor_id=owner_id, actor_role="OWNER",
    )
    target = await pricing_service.admin_add_discount_target(
        conn, discount_id=discount["id"], target_type="BRAND", target_id=brand_id,
        actor_id=owner_id, actor_role="OWNER",
    )
    assert target["target_type"] == "BRAND"
    assert target["target_id"] == brand_id

    listed = await pricing_service.admin_list_discounts(conn)
    this_one = next(d for d in listed if d["id"] == discount["id"])
    assert len(this_one["targets"]) == 1

    with pytest.raises(LookupError):
        await pricing_service.admin_remove_discount_target(
            conn, discount_id=discount["id"], row_id=999999, actor_id=owner_id, actor_role="OWNER"
        )

    await pricing_service.admin_remove_discount_target(
        conn, discount_id=discount["id"], row_id=target["id"], actor_id=owner_id, actor_role="OWNER"
    )
    listed_after = await pricing_service.admin_list_discounts(conn)
    this_one_after = next(d for d in listed_after if d["id"] == discount["id"])
    assert len(this_one_after["targets"]) == 0


async def test_ends_before_starts_rejected(conn, clean_slate):
    from datetime import datetime, timedelta, timezone

    owner_id = await _get_seeded_owner_id(conn)
    now = datetime.now(timezone.utc)
    with pytest.raises(pricing_service.InvalidDiscount):
        await pricing_service.admin_create_discount(
            conn, name="Backwards", kind="FIXED", value=100, starts_at=now, ends_at=now - timedelta(days=1),
            priority=0, targets=[], actor_id=owner_id, actor_role="OWNER",
        )
