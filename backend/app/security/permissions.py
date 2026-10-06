"""Server-side permission enforcement backing the §3 matrix. Every endpoint
that isn't purely public calls `get_current_user` (identity + freshness) and,
where a specific permission is required, `require_permission(key)`.

Permission data is read from `role_permissions`/`permissions`/`roles` on
every request rather than cached in the session token — §3: "permission har
API chaqiruvida serverda tekshiriladi" (checked server-side on every call),
and a deactivated admin's existing token must stop working immediately
(§12.6), which a cached/token-embedded role would defeat.
"""
from __future__ import annotations

from dataclasses import dataclass

import asyncpg
from fastapi import Depends, Header, HTTPException

from app.db.pool import get_conn
from app.security import session as session_module
from app.config import Settings


class Forbidden(HTTPException):
    def __init__(self, detail: str = "Permission denied") -> None:
        super().__init__(status_code=403, detail=detail)


class Unauthorized(HTTPException):
    def __init__(self, detail: str = "Not authenticated") -> None:
        super().__init__(status_code=401, detail=detail)


@dataclass(frozen=True)
class CurrentUser:
    id: int
    telegram_id: int
    role: str
    status: str


def _get_settings() -> Settings:
    # Imported lazily as a function (not a module-level singleton) so tests
    # can monkeypatch env vars per-test without import-order issues.
    return Settings.from_env()


async def get_current_user(
    authorization: str | None = Header(default=None),
    conn: asyncpg.Connection = Depends(get_conn),
) -> CurrentUser:
    if not authorization or not authorization.startswith("Bearer "):
        raise Unauthorized("missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()

    settings = _get_settings()
    try:
        user_id = session_module.verify(token, settings.session_secret)
    except session_module.InvalidSession as exc:
        raise Unauthorized(str(exc)) from exc

    row = await conn.fetchrow(
        "SELECT id, telegram_id, role, status FROM users WHERE id = $1 AND deleted_at IS NULL",
        user_id,
    )
    if row is None:
        raise Unauthorized("user not found")

    user = CurrentUser(id=row["id"], telegram_id=row["telegram_id"], role=row["role"], status=row["status"])
    if user.status != "ACTIVE":
        # §12.6 "Deaktivlangan admin amal qiladi -> 403": the token is still
        # cryptographically valid, but the current DB state overrides it.
        raise Forbidden("account is deactivated")
    return user


async def has_permission(conn: asyncpg.Connection, role: str, permission_key: str) -> bool:
    row = await conn.fetchrow(
        """
        SELECT 1
        FROM role_permissions rp
        JOIN roles r ON r.id = rp.role_id
        JOIN permissions p ON p.id = rp.permission_id
        WHERE r.name = $1 AND p.key = $2
        """,
        role,
        permission_key,
    )
    return row is not None


def require_permission(permission_key: str):
    async def dependency(
        current_user: CurrentUser = Depends(get_current_user),
        conn: asyncpg.Connection = Depends(get_conn),
    ) -> CurrentUser:
        if not await has_permission(conn, current_user.role, permission_key):
            raise Forbidden(f"missing permission: {permission_key}")
        return current_user

    return dependency
