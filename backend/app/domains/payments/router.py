from __future__ import annotations

from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel

from app.config import Settings
from app.db.pool import get_conn
from app.domains.commerce.orders import repository as orders_repository
from app.domains.payments import repository as payments_repository
from app.domains.payments import service
from app.security.idempotency import hash_request, idempotent_scope
from app.security.permissions import CurrentUser, Forbidden, get_current_user, require_permission
from app.security.signing import signed_url_for_folder
from app.security.uploads import InvalidUpload, read_upload_limited

router = APIRouter(tags=["payments"])


class SubmitPaymentRequest(BaseModel):
    order_id: int


class ReviewPaymentRequest(BaseModel):
    approve: bool
    rejection_reason: str | None = None


@router.post("/payments", status_code=201)
async def submit_payment(
    body: SubmitPaymentRequest,
    request: Request,
    idempotency_key: UUID = Header(..., alias="Idempotency-Key"),
    current_user: CurrentUser = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_conn),
) -> dict:
    order = await orders_repository.get_order(conn, order_id=body.order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="order not found")
    if order["user_id"] != current_user.id:
        raise Forbidden("cannot pay for another user's order")

    request_hash = hash_request(body.model_dump())
    async with idempotent_scope(
        conn, key=idempotency_key, endpoint="POST /payments", user_id=current_user.id, request_hash=request_hash
    ) as scope:
        if scope.stored is None:
            try:
                payment = await service.submit_payment(
                    conn,
                    order_id=body.order_id,
                    actor_id=current_user.id,
                    actor_role=current_user.role,
                    ip=request.client.host if request.client else None,
                )
                scope.set_result(201, dict(payment))
            except (LookupError, service.OrderNotAwaitingPayment) as exc:
                scope.set_result(422, {"error": {"code": "INVALID_ORDER_STATE", "message": str(exc)}})
    result = scope.result
    if result.status_code >= 400:
        raise HTTPException(status_code=result.status_code, detail=result.response_body)
    return result.response_body


@router.post("/payments/{payment_id}/receipt")
async def upload_receipt(
    payment_id: int,
    file: UploadFile,
    current_user: CurrentUser = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_conn),
) -> dict:
    payment = await payments_repository.get_payment(conn, payment_id=payment_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="payment not found")
    order = await orders_repository.get_order(conn, order_id=payment["order_id"])
    if order["user_id"] != current_user.id:
        raise Forbidden("cannot attach a receipt to another user's payment")

    settings = Settings.from_env()
    try:
        file_bytes = await read_upload_limited(file)
        receipt = await service.upload_receipt(
            conn,
            payment_id=payment_id,
            file_bytes=file_bytes,
            uploads_root=settings.uploads_root,
            actor_id=current_user.id,
            actor_role=current_user.role,
        )
    except InvalidUpload as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {"id": receipt["id"], "payment_id": receipt["payment_id"]}


@router.get("/admin/payments")
async def admin_list_payments(
    status: str | None = None,
    limit: int = Query(default=20, le=200, gt=0),
    current_user: CurrentUser = Depends(require_permission("payments.review")),
    conn: asyncpg.Connection = Depends(get_conn),
) -> dict:
    rows = await payments_repository.list_payments(conn, status=status, limit=limit)
    return {"items": [dict(r) for r in rows]}


@router.post("/admin/payments/{payment_id}/review")
async def admin_review_payment(
    payment_id: int,
    body: ReviewPaymentRequest,
    request: Request,
    current_user: CurrentUser = Depends(require_permission("payments.review")),
    conn: asyncpg.Connection = Depends(get_conn),
) -> dict:
    try:
        payment = await service.review_payment(
            conn,
            payment_id=payment_id,
            approve=body.approve,
            rejection_reason=body.rejection_reason,
            actor_id=current_user.id,
            actor_role=current_user.role,
            ip=request.client.host if request.client else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except service.OrderNotReviewable as exc:
        raise HTTPException(status_code=422, detail={"error": {"code": "ORDER_NOT_REVIEWABLE", "message": str(exc)}}) from exc
    return dict(payment)


@router.get("/admin/payments/{payment_id}/receipt")
async def admin_get_receipt_url(
    payment_id: int,
    current_user: CurrentUser = Depends(require_permission("payments.review")),
    conn: asyncpg.Connection = Depends(get_conn),
) -> dict:
    receipt = await payments_repository.get_receipt_for_payment(conn, payment_id=payment_id)
    if receipt is None:
        raise HTTPException(status_code=404, detail="receipt not found")

    settings = Settings.from_env()
    url = signed_url_for_folder(receipt["storage_path"], "receipts", settings.signing_secret)
    return {"url": url}
