"""Phase 06 security boundary matrix — extends tests/integration/
test_permissions.py's pattern to the new admin-catalog and admin-payments
permission keys this phase's endpoints are gated by."""
from __future__ import annotations

import pytest

from app.security.permissions import has_permission

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("permission_key", ["products.create", "products.update", "products.archive", "payments.review"])
async def test_admin_has_new_endpoint_permissions(conn, clean_slate, permission_key):
    assert await has_permission(conn, "ADMIN", permission_key) is True


@pytest.mark.parametrize("permission_key", ["products.create", "products.update", "products.archive", "payments.review"])
async def test_user_lacks_new_endpoint_permissions(conn, clean_slate, permission_key):
    assert await has_permission(conn, "USER", permission_key) is False


@pytest.mark.parametrize("permission_key", ["products.create", "products.update", "products.archive", "payments.review"])
async def test_owner_has_new_endpoint_permissions(conn, clean_slate, permission_key):
    # OWNER's existing broader grant (migration 0001_identity: every
    # permission) must remain intact — Phase 06 adds no OWNER-specific logic.
    assert await has_permission(conn, "OWNER", permission_key) is True


async def test_admin_still_cannot_reach_owner_only_permissions(conn, clean_slate):
    """Phase-06 DoD's explicit case: the Admin Panel must not become an
    Owner Dashboard."""
    for permission_key in ["finance.view", "analytics.view", "admins.manage", "audit.view", "settings.manage"]:
        assert await has_permission(conn, "ADMIN", permission_key) is False
        assert await has_permission(conn, "OWNER", permission_key) is True


# --- v2 rebuild: cancellation/refund/AI permission matrix (migration 0017) --


@pytest.mark.parametrize("permission_key", ["cancellation_requests.review", "refunds.manage", "ai.assistant.use"])
async def test_admin_and_owner_have_cancellation_refund_ai_permissions(conn, clean_slate, permission_key):
    assert await has_permission(conn, "ADMIN", permission_key) is True
    assert await has_permission(conn, "OWNER", permission_key) is True


@pytest.mark.parametrize("permission_key", ["cancellation_requests.review", "refunds.manage", "ai.assistant.use"])
async def test_user_lacks_cancellation_refund_ai_permissions(conn, clean_slate, permission_key):
    # §7/§14 of the v2 brief: AI and cancellation/refund review are never
    # available to a plain USER.
    assert await has_permission(conn, "USER", permission_key) is False


async def test_user_can_only_request_cancellation_not_review_it(conn, clean_slate):
    assert await has_permission(conn, "USER", "cancellation_requests.create") is True
    assert await has_permission(conn, "USER", "cancellation_requests.review") is False


async def test_only_owner_can_set_cost_price(conn, clean_slate):
    # The cost-price endpoints (catalog/admin_router.py) are gated by
    # finance.view, not products.update — this is what makes "ADMIN cannot
    # see/edit cost price, OWNER can" true independent of ADMIN's broader
    # product-management grant.
    assert await has_permission(conn, "ADMIN", "products.update") is True
    assert await has_permission(conn, "ADMIN", "finance.view") is False
    assert await has_permission(conn, "OWNER", "finance.view") is True
