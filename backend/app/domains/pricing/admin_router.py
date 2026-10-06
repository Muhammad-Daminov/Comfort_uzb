"""Owner-only discount management — v2 rebuild §P2-4. Every route is gated
by `discounts.manage` (migration 0020_discounts_manage_permission), held
only by OWNER — ADMIN must not see or edit discounts (CLAUDE.md business
rule). No new discount semantics: this is CRUD over the exact
discounts/discount_targets model migration 0005_pricing already defines.
"""
from __future__ import annotations

from datetime import datetime, timezone

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.db.pool import get_conn
from app.domains.pricing import service
from app.security.permissions import CurrentUser, require_permission

router = APIRouter(prefix="/owner/discounts", tags=["owner-discounts"])


def _parse_optional_datetime(value: str | None, field_name: str) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"invalid {field_name}, expected ISO-8601") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


class TargetRequest(BaseModel):
    target_type: str
    target_id: int | None = None


class CreateDiscountRequest(BaseModel):
    name: str
    kind: str
    value: int
    starts_at: str | None = None
    ends_at: str | None = None
    priority: int = 0
    targets: list[TargetRequest] = []


class UpdateDiscountRequest(BaseModel):
    name: str | None = None
    kind: str | None = None
    value: int | None = None
    starts_at: str | None = None
    ends_at: str | None = None
    priority: int | None = None
    # Distinguishes "field omitted" from "field explicitly cleared to null" —
    # a bare `starts_at: None` in the JSON body means "clear it", not
    # "leave unchanged", so the model needs to know whether the key was
    # sent at all.
    clear_starts_at: bool = False
    clear_ends_at: bool = False


class SetActiveRequest(BaseModel):
    is_active: bool


@router.get("")
async def owner_list_discounts(
    current_user: CurrentUser = Depends(require_permission("discounts.manage")),
    conn: asyncpg.Connection = Depends(get_conn),
) -> dict:
    items = await service.admin_list_discounts(conn)
    return {"items": items}


@router.post("")
async def owner_create_discount(
    body: CreateDiscountRequest,
    current_user: CurrentUser = Depends(require_permission("discounts.manage")),
    conn: asyncpg.Connection = Depends(get_conn),
) -> dict:
    starts_at = _parse_optional_datetime(body.starts_at, "starts_at")
    ends_at = _parse_optional_datetime(body.ends_at, "ends_at")
    try:
        return await service.admin_create_discount(
            conn, name=body.name, kind=body.kind, value=body.value, starts_at=starts_at, ends_at=ends_at,
            priority=body.priority, targets=[(t.target_type, t.target_id) for t in body.targets],
            actor_id=current_user.id, actor_role=current_user.role,
        )
    except service.InvalidDiscount as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except asyncpg.exceptions.PostgresError as exc:
        raise HTTPException(status_code=422, detail="invalid discount data") from exc


@router.patch("/{discount_id}")
async def owner_update_discount(
    discount_id: int,
    body: UpdateDiscountRequest,
    current_user: CurrentUser = Depends(require_permission("discounts.manage")),
    conn: asyncpg.Connection = Depends(get_conn),
) -> dict:
    starts_at = _parse_optional_datetime(body.starts_at, "starts_at") if body.starts_at is not None else None
    ends_at = _parse_optional_datetime(body.ends_at, "ends_at") if body.ends_at is not None else None
    try:
        return await service.admin_update_discount(
            conn, discount_id=discount_id, name=body.name, kind=body.kind, value=body.value,
            starts_at=starts_at, ends_at=ends_at, priority=body.priority,
            set_starts_at=body.starts_at is not None or body.clear_starts_at,
            set_ends_at=body.ends_at is not None or body.clear_ends_at,
            actor_id=current_user.id, actor_role=current_user.role,
        )
    except service.InvalidDiscount as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{discount_id}/status")
async def owner_set_discount_active(
    discount_id: int,
    body: SetActiveRequest,
    current_user: CurrentUser = Depends(require_permission("discounts.manage")),
    conn: asyncpg.Connection = Depends(get_conn),
) -> dict:
    try:
        return await service.admin_set_discount_active(
            conn, discount_id=discount_id, is_active=body.is_active,
            actor_id=current_user.id, actor_role=current_user.role,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{discount_id}/targets")
async def owner_add_discount_target(
    discount_id: int,
    body: TargetRequest,
    current_user: CurrentUser = Depends(require_permission("discounts.manage")),
    conn: asyncpg.Connection = Depends(get_conn),
) -> dict:
    try:
        return await service.admin_add_discount_target(
            conn, discount_id=discount_id, target_type=body.target_type, target_id=body.target_id,
            actor_id=current_user.id, actor_role=current_user.role,
        )
    except service.InvalidDiscount as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except asyncpg.exceptions.PostgresError as exc:
        raise HTTPException(status_code=422, detail="invalid target data") from exc


@router.delete("/{discount_id}/targets/{row_id}")
async def owner_remove_discount_target(
    discount_id: int,
    row_id: int,
    current_user: CurrentUser = Depends(require_permission("discounts.manage")),
    conn: asyncpg.Connection = Depends(get_conn),
) -> dict:
    try:
        await service.admin_remove_discount_target(
            conn, discount_id=discount_id, row_id=row_id, actor_id=current_user.id, actor_role=current_user.role,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"removed": True}
