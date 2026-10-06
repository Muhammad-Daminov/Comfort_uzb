from __future__ import annotations

import asyncpg

from app.domains.commerce.orders import repository as orders_repository
from app.domains.commerce.orders.state_machine import assert_transition_allowed
from app.domains.payments import repository as payments_repository
from app.security.audit import record_audit
from app.security.uploads import validate_and_process_receipt


class OrderNotAwaitingPayment(Exception):
    pass


class OrderNotReviewable(Exception):
    """The payment's order is CANCELLED/EXPIRED — approving would record
    money against a dead order; rejecting is moot."""


async def submit_payment(
    conn: asyncpg.Connection, *, order_id: int, actor_id: int, actor_role: str, ip: str | None = None
) -> asyncpg.Record:
    """§8.1: CREATED -> AWAITING_PAYMENT -> PAYMENT_SUBMITTED. A `POST
    /payments` call is the user declaring intent to pay; the order moves to
    AWAITING_PAYMENT here if it hasn't already (idempotent no-op if it has)."""
    async with conn.transaction():
        order = await orders_repository.get_order_for_update(conn, order_id=order_id)
        if order is None:
            raise LookupError(f"order {order_id} not found")

        if order["status"] == "CREATED":
            assert_transition_allowed("CREATED", "AWAITING_PAYMENT")
            await orders_repository.transition_status(
                conn, order_id=order_id, from_statuses=["CREATED"], to_status="AWAITING_PAYMENT"
            )
        elif order["status"] != "AWAITING_PAYMENT":
            raise OrderNotAwaitingPayment(f"order {order_id} is {order['status']}, cannot submit a payment")

        # One open payment per order. A second "I will pay" (new
        # Idempotency-Key, e.g. the user reopened the payment screen) used
        # to create another PENDING payment for the full remaining amount;
        # approving both doubled `paid_amount`. The row lock above makes
        # this check race-free.
        existing = await payments_repository.get_pending_payment_for_order(conn, order_id=order_id)
        if existing is not None:
            return existing

        full_order = await orders_repository.get_order(conn, order_id=order_id)
        payment = await payments_repository.create_payment(conn, order_id=order_id, amount=full_order["remaining_amount"])

        await record_audit(
            conn,
            actor_id=actor_id,
            actor_role=actor_role,
            action="payment.submit",
            entity_type="payment",
            entity_id=payment["id"],
            new_data={"order_id": order_id, "amount": payment["amount"]},
            ip=ip,
        )
        return payment


async def upload_receipt(
    conn: asyncpg.Connection,
    *,
    payment_id: int,
    file_bytes: bytes,
    uploads_root: str,
    actor_id: int,
    actor_role: str,
    ip: str | None = None,
) -> asyncpg.Record:
    """§8.1: PAYMENT_SUBMITTED -> UNDER_REVIEW once the actual receipt proof
    is attached — this is what puts the order in the admin review queue."""
    payment = await payments_repository.get_payment(conn, payment_id=payment_id)
    if payment is None:
        raise LookupError(f"payment {payment_id} not found")
    if payment["status"] != "PENDING":
        raise ValueError(f"payment {payment_id} is {payment['status']}, cannot attach a receipt")

    processed = validate_and_process_receipt(file_bytes, uploads_root)

    async with conn.transaction():
        receipt = await payments_repository.create_receipt(
            conn, payment_id=payment_id, storage_path=processed.storage_path
        )

        order = await orders_repository.get_order_for_update(conn, order_id=payment["order_id"])
        if order["status"] == "AWAITING_PAYMENT":
            assert_transition_allowed("AWAITING_PAYMENT", "PAYMENT_SUBMITTED")
            await orders_repository.transition_status(
                conn, order_id=order["id"], from_statuses=["AWAITING_PAYMENT"], to_status="PAYMENT_SUBMITTED"
            )
        current_status = (await orders_repository.get_order(conn, order_id=order["id"]))["status"]
        if current_status == "PAYMENT_SUBMITTED":
            assert_transition_allowed("PAYMENT_SUBMITTED", "UNDER_REVIEW")
            await orders_repository.transition_status(
                conn, order_id=order["id"], from_statuses=["PAYMENT_SUBMITTED"], to_status="UNDER_REVIEW"
            )

        await record_audit(
            conn,
            actor_id=actor_id,
            actor_role=actor_role,
            action="payment.receipt_upload",
            entity_type="payment",
            entity_id=payment_id,
            new_data={"storage_path": processed.storage_path},
            ip=ip,
        )
        return receipt


async def review_payment(
    conn: asyncpg.Connection,
    *,
    payment_id: int,
    approve: bool,
    rejection_reason: str | None,
    actor_id: int,
    actor_role: str,
    ip: str | None = None,
) -> asyncpg.Record:
    if not approve and (not rejection_reason or len(rejection_reason.strip()) == 0):
        raise ValueError("rejection_reason is required when rejecting a payment")

    async with conn.transaction():
        pending = await payments_repository.get_payment(conn, payment_id=payment_id)
        if pending is None or pending["status"] != "PENDING":
            raise ValueError(f"payment {payment_id} is not PENDING (already reviewed) or does not exist")

        # Lock the order first (same FOR UPDATE discipline as confirm/cancel):
        # money must never land on an order that was cancelled or expired
        # while the receipt sat in the review queue, and the REJECTED
        # transition below must not race a concurrent cancel.
        order = await orders_repository.get_order_for_update(conn, order_id=pending["order_id"])
        if order is None or order["status"] in ("CANCELLED", "EXPIRED"):
            raise OrderNotReviewable(
                f"order {pending['order_id']} is {order['status'] if order else 'missing'}; its payment cannot be reviewed"
            )

        payment = await payments_repository.review_payment(
            conn, payment_id=payment_id, actor_id=actor_id, approve=approve, rejection_reason=rejection_reason
        )
        if payment is None:
            raise ValueError(f"payment {payment_id} is not PENDING (already reviewed) or does not exist")

        await payments_repository.mark_receipt_reviewed(conn, payment_id=payment_id, approve=approve)

        if approve:
            await conn.execute(
                """
                UPDATE orders
                SET paid_amount = paid_amount + $2, remaining_amount = total_amount - (paid_amount + $2), updated_at = now()
                WHERE id = $1
                """,
                payment["order_id"],
                payment["amount"],
            )
        elif order["status"] == "UNDER_REVIEW":
            # §8.1: UNDER_REVIEW -> REJECTED is the admin rejecting the
            # receipt. Nothing ever performed this transition before: the
            # payment flipped to REJECTED but the order stayed UNDER_REVIEW
            # forever — the user could neither resubmit (only CREATED/
            # AWAITING_PAYMENT accept a payment) nor see the outcome.
            assert_transition_allowed("UNDER_REVIEW", "REJECTED")
            await orders_repository.transition_status(
                conn, order_id=order["id"], from_statuses=["UNDER_REVIEW"], to_status="REJECTED"
            )
            await record_audit(
                conn,
                actor_id=actor_id,
                actor_role=actor_role,
                action="order.reject",
                entity_type="order",
                entity_id=order["id"],
                old_data={"status": "UNDER_REVIEW"},
                new_data={"status": "REJECTED", "payment_id": payment_id},
                ip=ip,
            )

        await record_audit(
            conn,
            actor_id=actor_id,
            actor_role=actor_role,
            action="payment.review",
            entity_type="payment",
            entity_id=payment_id,
            new_data={"status": payment["status"], "rejection_reason": rejection_reason},
            ip=ip,
        )
        return payment
