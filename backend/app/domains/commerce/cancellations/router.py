from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.db.pool import get_conn
from app.domains.commerce.cancellations import repository, service
from app.security.permissions import CurrentUser, get_current_user, require_permission

router = APIRouter(tags=["cancellations"])


class CancellationRequestBody(BaseModel):
    reason: str


class CancellationDecisionBody(BaseModel):
    decision_note: str | None = None


def _error(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


@router.post("/orders/{order_id}/cancellation-request", status_code=201)
async def create_cancellation_request(
    order_id: int,
    body: CancellationRequestBody,
    request: Request,
    current_user: CurrentUser = Depends(require_permission("cancellation_requests.create")),
    conn: asyncpg.Connection = Depends(get_conn),
) -> dict:
    try:
        result = await service.request_cancellation(
            conn,
            order_id=order_id,
            user_id=current_user.id,
            reason=body.reason,
            ip=request.client.host if request.client else None,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=_error("FORBIDDEN", str(exc))) from exc
    except service.RequestAlreadyOpen as exc:
        raise HTTPException(status_code=409, detail=_error("REQUEST_ALREADY_OPEN", str(exc))) from exc
    except service.OrderNotEligible as exc:
        raise HTTPException(status_code=422, detail=_error("ORDER_NOT_ELIGIBLE", str(exc))) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=_error("INVALID_REQUEST", str(exc))) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=_error("NOT_FOUND", str(exc))) from exc
    return dict(result)


@router.get("/admin/cancellation-requests")
async def list_pending_cancellation_requests(
    current_user: CurrentUser = Depends(require_permission("cancellation_requests.review")),
    conn: asyncpg.Connection = Depends(get_conn),
) -> dict:
    rows = await repository.list_pending(conn)
    return {"items": [dict(r) for r in rows]}


@router.post("/admin/cancellation-requests/{request_id}/approve")
async def approve_cancellation_request(
    request_id: int,
    body: CancellationDecisionBody,
    request: Request,
    current_user: CurrentUser = Depends(require_permission("cancellation_requests.review")),
    conn: asyncpg.Connection = Depends(get_conn),
) -> dict:
    return await _decide(request_id, True, body, request, current_user, conn)


@router.post("/admin/cancellation-requests/{request_id}/deny")
async def deny_cancellation_request(
    request_id: int,
    body: CancellationDecisionBody,
    request: Request,
    current_user: CurrentUser = Depends(require_permission("cancellation_requests.review")),
    conn: asyncpg.Connection = Depends(get_conn),
) -> dict:
    return await _decide(request_id, False, body, request, current_user, conn)


async def _decide(
    request_id: int,
    approve: bool,
    body: CancellationDecisionBody,
    request: Request,
    current_user: CurrentUser,
    conn: asyncpg.Connection,
) -> dict:
    try:
        result = await service.decide_cancellation(
            conn,
            request_id=request_id,
            approve=approve,
            decision_note=body.decision_note,
            actor_id=current_user.id,
            actor_role=current_user.role,
            ip=request.client.host if request.client else None,
        )
    except service.RequestNotPending as exc:
        raise HTTPException(status_code=409, detail=_error("REQUEST_NOT_PENDING", str(exc))) from exc
    except service.OrderNotEligible as exc:
        raise HTTPException(status_code=409, detail=_error("ORDER_NOT_ELIGIBLE", str(exc))) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=_error("NOT_FOUND", str(exc))) from exc
    return dict(result)
