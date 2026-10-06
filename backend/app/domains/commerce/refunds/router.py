from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.db.pool import get_conn
from app.domains.commerce.refunds import repository, service
from app.security.permissions import CurrentUser, get_current_user, require_permission

router = APIRouter(tags=["refunds"])


def _error(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


class CreateRefundBody(BaseModel):
    order_id: int
    payment_id: int | None = None
    amount: int
    method: str
    reason: str


class CompleteRefundBody(BaseModel):
    provider_reference: str | None = None


class FailRefundBody(BaseModel):
    reason: str | None = None


@router.post("/admin/refunds", status_code=201)
async def create_refund(
    body: CreateRefundBody,
    request: Request,
    current_user: CurrentUser = Depends(require_permission("refunds.manage")),
    conn: asyncpg.Connection = Depends(get_conn),
) -> dict:
    try:
        refund = await service.record_refund(
            conn,
            order_id=body.order_id,
            payment_id=body.payment_id,
            amount=body.amount,
            method=body.method,
            reason=body.reason,
            actor_id=current_user.id,
            actor_role=current_user.role,
            ip=request.client.host if request.client else None,
        )
    except service.InvalidRefundAmount as exc:
        raise HTTPException(status_code=409, detail=_error("INVALID_REFUND_AMOUNT", str(exc))) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=_error("INVALID_REQUEST", str(exc))) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=_error("NOT_FOUND", str(exc))) from exc
    return dict(refund)


@router.get("/admin/orders/{order_id}/refunds")
async def list_refunds(
    order_id: int,
    current_user: CurrentUser = Depends(require_permission("refunds.manage")),
    conn: asyncpg.Connection = Depends(get_conn),
) -> dict:
    rows = await repository.list_for_order(conn, order_id=order_id)
    return {"items": [dict(r) for r in rows]}


@router.post("/admin/refunds/{refund_id}/complete")
async def complete_refund(
    refund_id: int,
    body: CompleteRefundBody,
    request: Request,
    current_user: CurrentUser = Depends(require_permission("refunds.manage")),
    conn: asyncpg.Connection = Depends(get_conn),
) -> dict:
    try:
        refund = await service.complete_refund(
            conn,
            refund_id=refund_id,
            provider_reference=body.provider_reference,
            actor_id=current_user.id,
            actor_role=current_user.role,
            ip=request.client.host if request.client else None,
        )
    except service.RefundNotPending as exc:
        raise HTTPException(status_code=409, detail=_error("REFUND_NOT_PENDING", str(exc))) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=_error("NOT_FOUND", str(exc))) from exc
    return dict(refund)


@router.post("/admin/refunds/{refund_id}/fail")
async def fail_refund(
    refund_id: int,
    body: FailRefundBody,
    request: Request,
    current_user: CurrentUser = Depends(require_permission("refunds.manage")),
    conn: asyncpg.Connection = Depends(get_conn),
) -> dict:
    try:
        refund = await service.fail_refund(
            conn,
            refund_id=refund_id,
            reason=body.reason,
            actor_id=current_user.id,
            actor_role=current_user.role,
            ip=request.client.host if request.client else None,
        )
    except service.RefundNotPending as exc:
        raise HTTPException(status_code=409, detail=_error("REFUND_NOT_PENDING", str(exc))) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=_error("NOT_FOUND", str(exc))) from exc
    return dict(refund)
