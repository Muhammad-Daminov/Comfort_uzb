"""OWNER-only endpoints (Phase 07). Every route is gated by the exact §3
permission key it corresponds to — all five (`finance.view`,
`analytics.view`, `admins.manage`, `audit.view`, `settings.manage`) were
already seeded in migration 0001_identity, held only by OWNER (ADMIN
explicitly excluded in that same seed data) — reused verbatim, nothing new.
"""
from __future__ import annotations

from datetime import datetime, timezone

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from app.db.pool import get_conn
from app.domains.owner import repository, service
from app.security.permissions import CurrentUser, require_permission

router = APIRouter(prefix="/owner", tags=["owner"])


def _parse_date(value: str, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"invalid {field_name}, expected ISO-8601") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


@router.get("/dashboard")
async def owner_dashboard(
    current_user: CurrentUser = Depends(require_permission("finance.view")),
    conn: asyncpg.Connection = Depends(get_conn),
) -> dict:
    return await service.get_dashboard(conn)


@router.get("/finance")
async def owner_finance(
    from_: str = Query(..., alias="from"),
    to: str = Query(...),
    current_user: CurrentUser = Depends(require_permission("finance.view")),
    conn: asyncpg.Connection = Depends(get_conn),
) -> dict:
    date_from = _parse_date(from_, "from")
    date_to = _parse_date(to, "to")
    try:
        return await service.get_finance(conn, date_from=date_from, date_to=date_to)
    except service.InvalidDateRange as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/analytics")
async def owner_analytics(
    from_: str = Query(..., alias="from"),
    to: str = Query(...),
    current_user: CurrentUser = Depends(require_permission("analytics.view")),
    conn: asyncpg.Connection = Depends(get_conn),
) -> dict:
    date_from = _parse_date(from_, "from")
    date_to = _parse_date(to, "to")
    try:
        return await service.get_analytics(conn, date_from=date_from, date_to=date_to)
    except service.InvalidDateRange as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


class CreateAdminRequest(BaseModel):
    # Deliberately no `role` field — role is hardcoded 'ADMIN' server-side
    # (service.py), so a request body can never specify or escalate it.
    telegram_id: int
    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None


class SetAdminStatusRequest(BaseModel):
    status: str


@router.get("/admins")
async def owner_list_admins(
    current_user: CurrentUser = Depends(require_permission("admins.manage")),
    conn: asyncpg.Connection = Depends(get_conn),
) -> dict:
    rows = await service.list_admins(conn)
    return {"items": [dict(r) for r in rows]}


@router.post("/admins")
async def owner_create_admin(
    body: CreateAdminRequest,
    request: Request,
    current_user: CurrentUser = Depends(require_permission("admins.manage")),
    conn: asyncpg.Connection = Depends(get_conn),
) -> dict:
    try:
        admin = await service.create_admin(
            conn, telegram_id=body.telegram_id, first_name=body.first_name, last_name=body.last_name,
            username=body.username, actor_id=current_user.id, actor_role=current_user.role,
            ip=request.client.host if request.client else None,
        )
    except service.CannotModifyOwner as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return dict(admin)


@router.post("/admins/{user_id}/deactivate")
async def owner_deactivate_admin(
    user_id: int,
    request: Request,
    current_user: CurrentUser = Depends(require_permission("admins.manage")),
    conn: asyncpg.Connection = Depends(get_conn),
) -> dict:
    try:
        admin = await service.set_admin_status(
            conn, user_id=user_id, status="DEACTIVATED", actor_id=current_user.id, actor_role=current_user.role,
            ip=request.client.host if request.client else None,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return dict(admin)


@router.post("/admins/{user_id}/reactivate")
async def owner_reactivate_admin(
    user_id: int,
    request: Request,
    current_user: CurrentUser = Depends(require_permission("admins.manage")),
    conn: asyncpg.Connection = Depends(get_conn),
) -> dict:
    try:
        admin = await service.set_admin_status(
            conn, user_id=user_id, status="ACTIVE", actor_id=current_user.id, actor_role=current_user.role,
            ip=request.client.host if request.client else None,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return dict(admin)


@router.get("/audit-logs")
async def owner_list_audit_logs(
    entity_type: str | None = None,
    action: str | None = None,
    actor_id: int | None = None,
    cursor: str | None = None,
    limit: int = Query(default=50, le=200, gt=0),
    current_user: CurrentUser = Depends(require_permission("audit.view")),
    conn: asyncpg.Connection = Depends(get_conn),
) -> dict:
    rows = await service.list_audit_logs(
        conn, entity_type=entity_type, action=action, actor_id=actor_id, cursor=cursor, limit=limit
    )
    next_cursor = None
    if rows:
        last = rows[-1]
        next_cursor = repository.encode_audit_cursor(last["created_at"], last["id"])
    return {"items": rows, "next_cursor": next_cursor}


class PutSettingsRequest(BaseModel):
    # Matches §13.4's literal single `GET/PUT /owner/settings` shape — a
    # flat {key: value, ...} object. Each key is upserted independently
    # (partial update, not a whole-blob replace) so setting one key never
    # risks silently clobbering another the caller didn't send.
    settings: dict[str, object]


@router.get("/settings")
async def owner_get_settings(
    current_user: CurrentUser = Depends(require_permission("settings.manage")),
    conn: asyncpg.Connection = Depends(get_conn),
) -> dict:
    return await service.get_settings(conn)


@router.put("/settings")
async def owner_put_settings(
    body: PutSettingsRequest,
    request: Request,
    current_user: CurrentUser = Depends(require_permission("settings.manage")),
    conn: asyncpg.Connection = Depends(get_conn),
) -> dict:
    ip = request.client.host if request.client else None
    try:
        for key, value in body.settings.items():
            await service.put_setting(conn, key=key, value=value, actor_id=current_user.id, actor_role=current_user.role, ip=ip)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return await service.get_settings(conn)
