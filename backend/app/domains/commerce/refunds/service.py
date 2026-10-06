"""ADR-017: refund creation/completion is always admin-attested — no Hamyon
refund API is documented (docs/13_V2_REBUILD_AUDIT.md §2), so neither CASH
nor CARD auto-completes. If a documented Hamyon refund endpoint appears
later, `PaymentProvider.refund()` gets a real body and CARD refunds can
auto-transition to COMPLETED from here without changing this module's shape."""
from __future__ import annotations

import asyncpg

from app.domains.commerce.orders import repository as orders_repository
from app.domains.commerce.refunds import repository
from app.security.audit import record_audit

VALID_METHODS = {"CASH", "CARD"}


class InvalidRefundAmount(Exception):
    pass


class RefundNotPending(Exception):
    pass


async def record_refund(
    conn: asyncpg.Connection,
    *,
    order_id: int,
    payment_id: int | None,
    amount: int,
    method: str,
    reason: str,
    actor_id: int,
    actor_role: str,
    ip: str | None = None,
) -> asyncpg.Record:
    if method not in VALID_METHODS:
        raise ValueError(f"method must be one of {sorted(VALID_METHODS)}")
    if not reason or len(reason.strip()) < 10:
        raise ValueError("reason must be at least 10 characters")
    if amount <= 0:
        raise InvalidRefundAmount("refund amount must be positive")

    async with conn.transaction():
        order = await orders_repository.get_order_for_update(conn, order_id=order_id)
        if order is None:
            raise LookupError(f"order {order_id} not found")

        already_refunded = await repository.total_refunded_for_order(conn, order_id=order_id)
        # Amount-conservation invariant: the sum of COMPLETED refunds can
        # never exceed what was actually paid — this is what stops a
        # duplicate/over-refund regardless of how many refund rows exist.
        if already_refunded + amount > order["paid_amount"]:
            raise InvalidRefundAmount(
                f"order {order_id}: paid {order['paid_amount']}, already refunded {already_refunded}, "
                f"requested {amount} — would exceed amount paid"
            )

        refund = await repository.create_refund(
            conn,
            order_id=order_id,
            payment_id=payment_id,
            amount=amount,
            method=method,
            reason=reason,
            created_by=actor_id,
        )

        await record_audit(
            conn,
            actor_id=actor_id,
            actor_role=actor_role,
            action="refund.create",
            entity_type="refund",
            entity_id=refund["id"],
            new_data={"order_id": order_id, "amount": amount, "method": method},
            ip=ip,
        )
        return refund


async def complete_refund(
    conn: asyncpg.Connection,
    *,
    refund_id: int,
    provider_reference: str | None,
    actor_id: int,
    actor_role: str,
    ip: str | None = None,
) -> asyncpg.Record:
    async with conn.transaction():
        current = await repository.get_refund_for_update(conn, refund_id=refund_id)
        if current is None:
            raise LookupError(f"refund {refund_id} not found")
        if current["status"] != "PENDING":
            raise RefundNotPending(f"refund {refund_id} is already {current['status']}")

        # Re-check the amount-conservation invariant at completion time, not
        # just at creation time: record_refund only guards against
        # *completed* refunds, so two PENDING refunds can be created for the
        # same order (e.g. a genuine race) without either violating it on
        # creation — the ceiling must hold at the point money actually
        # moves, i.e. here. The order row is locked so two concurrent
        # completions on sibling refunds serialize instead of both reading
        # the same already_refunded total.
        order = await orders_repository.get_order_for_update(conn, order_id=current["order_id"])
        already_refunded = await repository.total_refunded_for_order(conn, order_id=current["order_id"])
        if already_refunded + current["amount"] > order["paid_amount"]:
            raise InvalidRefundAmount(
                f"refund {refund_id}: completing it would bring total refunds to "
                f"{already_refunded + current['amount']}, exceeding paid_amount {order['paid_amount']}"
            )

        updated = await repository.mark_status(
            conn, refund_id=refund_id, status="COMPLETED", completed_by=actor_id, provider_reference=provider_reference
        )
        if updated is None:
            raise RefundNotPending(f"refund {refund_id} changed concurrently — retry")

        await record_audit(
            conn,
            actor_id=actor_id,
            actor_role=actor_role,
            action="refund.complete",
            entity_type="refund",
            entity_id=refund_id,
            new_data={"status": "COMPLETED", "provider_reference": provider_reference},
            ip=ip,
        )
        return updated


async def fail_refund(
    conn: asyncpg.Connection,
    *,
    refund_id: int,
    reason: str | None,
    actor_id: int,
    actor_role: str,
    ip: str | None = None,
) -> asyncpg.Record:
    async with conn.transaction():
        current = await repository.get_refund_for_update(conn, refund_id=refund_id)
        if current is None:
            raise LookupError(f"refund {refund_id} not found")
        if current["status"] != "PENDING":
            raise RefundNotPending(f"refund {refund_id} is already {current['status']}")

        updated = await repository.mark_status(
            conn, refund_id=refund_id, status="FAILED", completed_by=None, provider_reference=reason
        )
        if updated is None:
            raise RefundNotPending(f"refund {refund_id} changed concurrently — retry")

        await record_audit(
            conn,
            actor_id=actor_id,
            actor_role=actor_role,
            action="refund.fail",
            entity_type="refund",
            entity_id=refund_id,
            new_data={"status": "FAILED", "reason": reason},
            ip=ip,
        )
        return updated
