"""ADR-017: a paid/CONFIRMED order cancels only through this request +
admin-decision flow — never a direct user cancel-endpoint call."""
from __future__ import annotations

import asyncpg

from app.domains.commerce.cancellations import repository
from app.domains.commerce.orders import repository as orders_repository
from app.domains.commerce.orders.state_machine import assert_transition_allowed
from app.security.audit import record_audit


class OrderNotEligible(Exception):
    pass


class RequestAlreadyOpen(Exception):
    pass


class RequestNotPending(Exception):
    pass


async def request_cancellation(
    conn: asyncpg.Connection, *, order_id: int, user_id: int, reason: str, ip: str | None = None
) -> asyncpg.Record:
    if not reason or len(reason.strip()) < 10:
        raise ValueError("reason must be at least 10 characters")

    order = await orders_repository.get_order(conn, order_id=order_id)
    if order is None:
        raise LookupError(f"order {order_id} not found")
    if order["user_id"] != user_id:
        raise PermissionError("cannot request cancellation for another user's order")
    if order["paid_amount"] <= 0:
        raise OrderNotEligible("order has no approved payment; use the direct cancel endpoint instead")
    if order["status"] not in ("UNDER_REVIEW", "CONFIRMED"):
        raise OrderNotEligible(f"order {order_id} is {order['status']}, cannot request cancellation")

    existing = await repository.get_pending_for_order(conn, order_id=order_id)
    if existing is not None:
        raise RequestAlreadyOpen(f"order {order_id} already has a pending cancellation request")

    async with conn.transaction():
        request = await repository.create_request(conn, order_id=order_id, requested_by=user_id, reason=reason)
        await record_audit(
            conn,
            actor_id=user_id,
            actor_role="USER",
            action="cancellation_request.create",
            entity_type="order",
            entity_id=order_id,
            new_data={"request_id": request["id"], "reason": reason},
            ip=ip,
        )
        return request


async def decide_cancellation(
    conn: asyncpg.Connection,
    *,
    request_id: int,
    approve: bool,
    decision_note: str | None,
    actor_id: int,
    actor_role: str,
    ip: str | None = None,
) -> asyncpg.Record:
    async with conn.transaction():
        request = await repository.get_request_for_update(conn, request_id=request_id)
        if request is None:
            raise LookupError(f"cancellation request {request_id} not found")
        if request["status"] != "PENDING":
            raise RequestNotPending(f"cancellation request {request_id} is already {request['status']}")

        order = await orders_repository.get_order_for_update(conn, order_id=request["order_id"])
        if order is None:
            raise LookupError(f"order {request['order_id']} not found")

        decided = await repository.decide(
            conn, request_id=request_id, approve=approve, decided_by=actor_id, decision_note=decision_note
        )
        if decided is None:
            raise RequestNotPending(f"cancellation request {request_id} changed concurrently — retry")

        if approve:
            if order["status"] != "CONFIRMED":
                raise OrderNotEligible(
                    f"order {order['id']} is {order['status']}, not CONFIRMED — cannot approve cancellation"
                )
            assert_transition_allowed("CONFIRMED", "CANCELLED")
            updated_order = await orders_repository.transition_status(
                conn,
                order_id=order["id"],
                from_statuses=["CONFIRMED"],
                to_status="CANCELLED",
                extra_set_sql="cancellation_reason = $4, cancelled_at = now(), cancelled_by = $5",
                extra_params=[request["reason"], actor_id],
            )
            if updated_order is None:
                raise OrderNotEligible(f"order {order['id']} status changed concurrently — retry")

            await repository.restore_stock_for_order(conn, order_id=order["id"], actor_id=actor_id)

            await record_audit(
                conn,
                actor_id=actor_id,
                actor_role=actor_role,
                action="order.cancel_via_request",
                entity_type="order",
                entity_id=order["id"],
                old_data={"status": "CONFIRMED"},
                new_data={"status": "CANCELLED", "cancellation_request_id": request_id},
                ip=ip,
            )

        await record_audit(
            conn,
            actor_id=actor_id,
            actor_role=actor_role,
            action="cancellation_request.decide",
            entity_type="cancellation_request",
            entity_id=request_id,
            new_data={"status": decided["status"], "decision_note": decision_note},
            ip=ip,
        )

        return decided
