"""§3/§12.6: permission checks read from role_permissions live, so a
deactivated admin's still-valid session token is rejected on the very next
request — this is what makes the check "server-side, every call" real."""
from __future__ import annotations

import pytest

from app.security.permissions import has_permission
from tests.integration import factories

pytestmark = pytest.mark.asyncio


async def test_owner_has_finance_view_admin_does_not(conn, clean_slate):
    assert await has_permission(conn, "OWNER", "finance.view") is True
    assert await has_permission(conn, "ADMIN", "finance.view") is False


async def test_user_lacks_orders_view_all(conn, clean_slate):
    assert await has_permission(conn, "USER", "orders.view.all") is False
    assert await has_permission(conn, "ADMIN", "orders.view.all") is True


async def test_unknown_permission_key_denied(conn, clean_slate):
    assert await has_permission(conn, "OWNER", "not_a_real_permission") is False


async def test_deactivated_admin_is_rejected_at_get_current_user(conn, clean_slate):
    from app.security.permissions import Forbidden, get_current_user
    from app.security import session as session_module

    admin_id = await factories.make_user(conn, role="ADMIN")
    await conn.execute("UPDATE users SET status = 'DEACTIVATED' WHERE id = $1", admin_id)

    secret = "test-secret-for-permission-integration"
    token = session_module.issue(admin_id, secret)

    import os

    os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "")
    os.environ["BOT_TOKEN"] = "unused"
    os.environ["SESSION_SECRET"] = secret
    os.environ["SIGNING_SECRET"] = "unused"

    with pytest.raises(Forbidden):
        await get_current_user(authorization=f"Bearer {token}", conn=conn)
