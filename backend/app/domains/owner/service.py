from __future__ import annotations

import json

import asyncpg

from app.domains.owner import repository
from app.security.audit import record_audit

DATE_RANGE_MAX_DAYS = 366  # bounded query range (§16 performance requirement)


class InvalidDateRange(Exception):
    pass


class CannotModifyOwner(Exception):
    pass


def validate_date_range(date_from, date_to) -> None:
    if date_to <= date_from:
        raise InvalidDateRange("'to' must be after 'from'")
    if (date_to - date_from).days > DATE_RANGE_MAX_DAYS:
        raise InvalidDateRange(f"date range must not exceed {DATE_RANGE_MAX_DAYS} days")


async def get_dashboard(conn: asyncpg.Connection) -> dict:
    return await repository.get_dashboard_summary(conn)


async def get_finance(conn: asyncpg.Connection, *, date_from, date_to) -> dict:
    validate_date_range(date_from, date_to)
    return await repository.get_finance_summary(conn, date_from=date_from, date_to=date_to)


async def get_analytics(conn: asyncpg.Connection, *, date_from, date_to) -> dict:
    validate_date_range(date_from, date_to)
    return await repository.get_analytics(conn, date_from=date_from, date_to=date_to)


async def list_admins(conn: asyncpg.Connection) -> list[asyncpg.Record]:
    return await repository.list_admins(conn)


async def create_admin(
    conn: asyncpg.Connection,
    *,
    telegram_id: int,
    first_name: str | None,
    last_name: str | None,
    username: str | None,
    actor_id: int,
    actor_role: str,
    ip: str | None = None,
) -> asyncpg.Record:
    async with conn.transaction():
        admin = await repository.create_admin(
            conn, telegram_id=telegram_id, first_name=first_name, last_name=last_name, username=username
        )
        if admin is None:
            # The guarded UPDATE's WHERE clause (role != 'OWNER') matched
            # zero rows — the target telegram_id already belongs to the
            # OWNER. Never silently downgrade or leave ambiguous.
            raise CannotModifyOwner(f"telegram_id {telegram_id} belongs to the OWNER and cannot be reassigned")
        await record_audit(
            conn, actor_id=actor_id, actor_role=actor_role, action="admin.create",
            entity_type="user", entity_id=admin["id"], new_data={"telegram_id": telegram_id, "role": "ADMIN"}, ip=ip,
        )
        return admin


async def set_admin_status(
    conn: asyncpg.Connection, *, user_id: int, status: str, actor_id: int, actor_role: str, ip: str | None = None
) -> asyncpg.Record:
    if status not in ("ACTIVE", "DEACTIVATED"):
        raise ValueError(f"invalid status: {status!r}")
    async with conn.transaction():
        admin = await repository.set_admin_status(conn, user_id=user_id, status=status)
        if admin is None:
            raise LookupError(f"admin {user_id} not found (or is not an ADMIN — this endpoint cannot target OWNER/USER rows)")
        await record_audit(
            conn, actor_id=actor_id, actor_role=actor_role, action="admin.status_change",
            entity_type="user", entity_id=user_id, new_data={"status": status}, ip=ip,
        )
        return admin


async def list_audit_logs(conn: asyncpg.Connection, **filters) -> list[dict]:
    return await repository.list_audit_logs(conn, **filters)


async def get_settings(conn: asyncpg.Connection) -> dict[str, object]:
    rows = await repository.get_all_settings(conn)
    return {row["key"]: json.loads(row["value"]) for row in rows}


async def put_setting(
    conn: asyncpg.Connection, *, key: str, value: object, actor_id: int, actor_role: str, ip: str | None = None
) -> dict:
    if not key or len(key) > 100:
        raise ValueError("key must be non-empty and at most 100 characters")
    async with conn.transaction():
        row = await repository.upsert_setting(conn, key=key, value=json.dumps(value), actor_id=actor_id)
        await record_audit(
            conn, actor_id=actor_id, actor_role=actor_role, action="settings.update",
            entity_type="store_settings", entity_id=None, new_data={"key": key, "value": value}, ip=ip,
        )
        return {"key": row["key"], "value": json.loads(row["value"]), "updated_at": row["updated_at"]}
