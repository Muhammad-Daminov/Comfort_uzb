from __future__ import annotations

import json
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel

from app.db.pool import get_conn
from app.domains.commerce.orders import repository as orders_repository
from app.domains.commerce.orders import service
from app.domains.commerce.orders.service import CheckoutLine
from app.domains.commerce.orders.state_machine import InvalidTransition
from app.domains.commerce.reservations.repository import InsufficientStock as ReservationInsufficientStock
from app.security.idempotency import StoredResult, hash_request, idempotent_scope
from app.security.permissions import CurrentUser, Forbidden, get_current_user, require_permission

router = APIRouter(tags=["orders"])


class CheckoutLineRequest(BaseModel):
    variant_id: int
    quantity: int
    client_unit_price: int | None = None


class CreateOrderRequest(BaseModel):
    lines: list[CheckoutLineRequest]


class CancelOrderRequest(BaseModel):
    reason: str


class AdjustInventoryRequest(BaseModel):
    variant_id: int
    quantity_change: int
    reason: str


def _order_out(order: asyncpg.Record) -> dict:
    return dict(order)


def _respond(result: StoredResult) -> dict:
    """Stored 4xx outcomes are replayed as the same HTTP error — raised only
    here, after `idempotent_scope` has committed the stored row."""
    if result.status_code >= 400:
        raise HTTPException(status_code=result.status_code, detail=result.response_body)
    return result.response_body


@router.post("/orders", status_code=201)
async def create_order(
    body: CreateOrderRequest,
    request: Request,
    idempotency_key: UUID = Header(..., alias="Idempotency-Key"),
    current_user: CurrentUser = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_conn),
) -> dict:
    request_hash = hash_request(body.model_dump())
    lines = [CheckoutLine(variant_id=l.variant_id, quantity=l.quantity, client_unit_price=l.client_unit_price) for l in body.lines]

    async with idempotent_scope(
        conn, key=idempotency_key, endpoint="POST /orders", user_id=current_user.id, request_hash=request_hash
    ) as scope:
        if scope.stored is None:
            try:
                order = await service.create_order(
                    conn, user_id=current_user.id, lines=lines, ip=request.client.host if request.client else None
                )
                scope.set_result(201, _order_out(order))
            except service.PriceMismatch as exc:
                scope.set_result(409, {
                    "error": {
                        "code": "PRICE_MISMATCH",
                        "message": "Narx yangilandi",
                        "details": {
                            "lines": [
                                {"variant_id": m.variant_id, "expected_unit_price": m.expected_unit_price}
                                for m in exc.mismatches
                            ]
                        },
                    }
                })
            except (service.InsufficientStock, ReservationInsufficientStock) as exc:
                scope.set_result(409, {"error": {"code": "INSUFFICIENT_STOCK", "message": str(exc)}})
            except service.VariantNotActive as exc:
                scope.set_result(422, {"error": {"code": "VARIANT_NOT_ACTIVE", "message": str(exc)}})
            except ValueError as exc:
                scope.set_result(422, {"error": {"code": "INVALID_REQUEST", "message": str(exc)}})
    return _respond(scope.result)


@router.get("/orders")
async def list_orders(
    current_user: CurrentUser = Depends(get_current_user), conn: asyncpg.Connection = Depends(get_conn)
) -> dict:
    rows = await orders_repository.list_orders_for_user(conn, user_id=current_user.id)
    items = []
    for row in rows:
        order = dict(row)
        # asyncpg has no JSON codec registered on this pool — json_agg(...)
        # comes back as a raw string, decoded here rather than adding a
        # pool-wide codec for one query.
        order["items"] = json.loads(order["items"]) if order["items"] else []
        items.append(order)
    return {"items": items}


@router.get("/orders/{order_id}")
async def get_order(
    order_id: int, current_user: CurrentUser = Depends(get_current_user), conn: asyncpg.Connection = Depends(get_conn)
) -> dict:
    order = await orders_repository.get_order(conn, order_id=order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="order not found")
    if order["user_id"] != current_user.id:
        from app.security.permissions import has_permission

        if not await has_permission(conn, current_user.role, "orders.view.all"):
            raise Forbidden("cannot view another user's order")

    result = dict(order)
    # Additive fields only — the order-owning USER can see their own
    # cancellation-request and refund history without a separate round
    # trip; neither table is USER-writable through this endpoint.
    from app.domains.commerce.cancellations import repository as cancellations_repository
    from app.domains.commerce.refunds import repository as refunds_repository

    result["cancellation_requests"] = [
        dict(r) for r in await cancellations_repository.list_for_order(conn, order_id=order_id)
    ]
    result["refunds"] = [dict(r) for r in await refunds_repository.list_for_order(conn, order_id=order_id)]
    return result


@router.post("/orders/{order_id}/cancel")
async def cancel_order(
    order_id: int,
    body: CancelOrderRequest,
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_conn),
) -> dict:
    order = await orders_repository.get_order(conn, order_id=order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="order not found")
    if order["user_id"] != current_user.id:
        raise Forbidden("cannot cancel another user's order")

    try:
        updated = await service.cancel_order(
            conn,
            order_id=order_id,
            reason=body.reason,
            actor_id=current_user.id,
            actor_role=current_user.role,
            ip=request.client.host if request.client else None,
        )
    except service.OrderHasApprovedPayment as exc:
        raise HTTPException(status_code=409, detail={"error": {"code": "APPROVED_PAYMENT_EXISTS", "message": str(exc)}}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except InvalidTransition as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return dict(updated)


@router.get("/admin/orders")
async def admin_list_orders(
    status: str | None = None,
    limit: int = Query(default=20, le=200, gt=0),
    current_user: CurrentUser = Depends(require_permission("orders.view.all")),
    conn: asyncpg.Connection = Depends(get_conn),
) -> dict:
    rows = await orders_repository.list_all_orders(conn, status=status, limit=limit)
    return {"items": [dict(r) for r in rows]}


@router.post("/admin/orders/{order_id}/confirm")
async def admin_confirm_order(
    order_id: int,
    request: Request,
    idempotency_key: UUID = Header(..., alias="Idempotency-Key"),
    current_user: CurrentUser = Depends(require_permission("orders.confirm")),
    conn: asyncpg.Connection = Depends(get_conn),
) -> dict:
    request_hash = hash_request({"order_id": order_id})
    async with idempotent_scope(
        conn, key=idempotency_key, endpoint="POST /admin/orders/confirm", user_id=current_user.id, request_hash=request_hash
    ) as scope:
        if scope.stored is None:
            try:
                order = await service.confirm_order(
                    conn,
                    order_id=order_id,
                    actor_id=current_user.id,
                    actor_role=current_user.role,
                    ip=request.client.host if request.client else None,
                )
                scope.set_result(200, dict(order))
            except service.ConcurrentConfirmation as exc:
                scope.set_result(409, {"error": {"code": "ALREADY_CONFIRMED", "message": str(exc)}})
            except service.InsufficientStock as exc:
                scope.set_result(409, {"error": {"code": "INSUFFICIENT_STOCK", "message": str(exc)}})
            except InvalidTransition as exc:
                scope.set_result(422, {"error": {"code": "INVALID_TRANSITION", "message": str(exc)}})
            except LookupError as exc:
                scope.set_result(404, {"error": {"code": "NOT_FOUND", "message": str(exc)}})
    return _respond(scope.result)


@router.post("/admin/orders/{order_id}/cancel")
async def admin_cancel_order(
    order_id: int,
    body: CancelOrderRequest,
    request: Request,
    idempotency_key: UUID = Header(..., alias="Idempotency-Key"),
    current_user: CurrentUser = Depends(require_permission("orders.cancel")),
    conn: asyncpg.Connection = Depends(get_conn),
) -> dict:
    request_hash = hash_request({"order_id": order_id, "reason": body.reason})
    async with idempotent_scope(
        conn, key=idempotency_key, endpoint="POST /admin/orders/cancel", user_id=current_user.id, request_hash=request_hash
    ) as scope:
        if scope.stored is None:
            try:
                order = await service.cancel_order(
                    conn,
                    order_id=order_id,
                    reason=body.reason,
                    actor_id=current_user.id,
                    actor_role=current_user.role,
                    ip=request.client.host if request.client else None,
                )
                scope.set_result(200, dict(order))
            except service.OrderHasApprovedPayment as exc:
                scope.set_result(409, {"error": {"code": "APPROVED_PAYMENT_EXISTS", "message": str(exc)}})
            except ValueError as exc:
                scope.set_result(422, {"error": {"code": "INVALID_REQUEST", "message": str(exc)}})
            except InvalidTransition as exc:
                scope.set_result(422, {"error": {"code": "INVALID_TRANSITION", "message": str(exc)}})
            except LookupError as exc:
                scope.set_result(404, {"error": {"code": "NOT_FOUND", "message": str(exc)}})
    return _respond(scope.result)


@router.post("/admin/inventory/adjust", status_code=201)
async def admin_adjust_inventory(
    body: AdjustInventoryRequest,
    idempotency_key: UUID = Header(..., alias="Idempotency-Key"),
    current_user: CurrentUser = Depends(require_permission("inventory.manage")),
    conn: asyncpg.Connection = Depends(get_conn),
) -> dict:
    from app.domains.commerce.inventory import repository as inventory_repository
    from app.security.audit import record_audit

    request_hash = hash_request(body.model_dump())
    async with idempotent_scope(
        conn, key=idempotency_key, endpoint="POST /admin/inventory/adjust", user_id=current_user.id, request_hash=request_hash
    ) as scope:
        if scope.stored is None:
            try:
                async with conn.transaction():
                    movement = await inventory_repository.adjust_stock(
                        conn,
                        variant_id=body.variant_id,
                        quantity_change=body.quantity_change,
                        reason=body.reason,
                        actor_id=current_user.id,
                    )
                    await record_audit(
                        conn,
                        actor_id=current_user.id,
                        actor_role=current_user.role,
                        action="inventory.adjust",
                        entity_type="product_variant",
                        entity_id=body.variant_id,
                        new_data={"quantity_change": body.quantity_change, "reason": body.reason},
                    )
                scope.set_result(201, dict(movement))
            except ValueError as exc:
                scope.set_result(422, {"error": {"code": "INVALID_ADJUSTMENT", "message": str(exc)}})
    return _respond(scope.result)
