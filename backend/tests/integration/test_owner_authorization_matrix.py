"""Phase 07's own required matrix: OWNER 200, ADMIN 403, USER 403 across
all six owner-only permission keys — extends
tests/integration/test_admin_permissions_boundary.py's pattern."""
from __future__ import annotations

import pytest

from app.security.permissions import has_permission

pytestmark = pytest.mark.asyncio

OWNER_ONLY_PERMISSIONS = ["finance.view", "analytics.view", "admins.manage", "audit.view", "settings.manage"]


@pytest.mark.parametrize("permission_key", OWNER_ONLY_PERMISSIONS)
async def test_owner_has_permission(conn, clean_slate, permission_key):
    assert await has_permission(conn, "OWNER", permission_key) is True


@pytest.mark.parametrize("permission_key", OWNER_ONLY_PERMISSIONS)
async def test_admin_lacks_permission(conn, clean_slate, permission_key):
    assert await has_permission(conn, "ADMIN", permission_key) is False


@pytest.mark.parametrize("permission_key", OWNER_ONLY_PERMISSIONS)
async def test_user_lacks_permission(conn, clean_slate, permission_key):
    assert await has_permission(conn, "USER", permission_key) is False
