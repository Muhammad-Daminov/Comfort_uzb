"""Order creation implements §7.3's checkout re-validation exactly: variant
ACTIVE?, `available >= qty`?, recompute current price, compare to whatever
price the client believes it is, write the ADR-5 snapshot. All of this plus
the stock reservation happens inside one transaction on the connection the
caller passed in — nothing here opens a second connection, which is what
keeps the audit-write transaction-participant (§12.3/security's DoD
requirement).
"""
from __future__ import annotations

from dataclasses import dataclass

import asyncpg

from app.domains.catalog import repository as catalog_repository
from app.domains.commerce.cart import repository as cart_repository
from app.domains.commerce.orders import repository as orders_repository
from app.domains.commerce.orders.order_number import generate_order_number
from app.domains.commerce.orders.repository import OrderLineInput
from app.domains.commerce.orders.state_machine import assert_transition_allowed
from app.domains.commerce.reservations import repository as reservations_repository
from app.domains.pricing.service import current_price_for_variant
from app.security.audit import record_audit


@dataclass(frozen=True)
class CheckoutLine:
    variant_id: int
    quantity: int
    client_unit_price: int | None = None


class VariantNotActive(Exception):
    pass


class InsufficientStock(Exception):
    pass


class OrderHasApprovedPayment(Exception):
    """§10/ADR-017: an order with any approved payment cannot be cancelled
    through the direct user-facing endpoint — it must go through a
    cancellation_requests row and an explicit admin decision."""


@dataclass(frozen=True)
class PriceMismatchLine:
    variant_id: int
    expected_unit_price: int
    submitted_unit_price: int


class PriceMismatch(Exception):
    def __init__(self, mismatches: list[PriceMismatchLine]) -> None:
        self.mismatches = mismatches
        super().__init__("checkout price mismatch")


async def create_order(
    conn: asyncpg.Connection, *, user_id: int, lines: list[CheckoutLine], ip: str | None = None
) -> asyncpg.Record:
    if not lines:
        raise ValueError("order must have at least one line")
    for line in lines:
        if line.quantity <= 0:
            raise ValueError("quantity must be positive")

    async with conn.transaction():
        order_lines: list[OrderLineInput] = []
        mismatches: list[PriceMismatchLine] = []

        for line in lines:
            variant = await catalog_repository.get_variant(conn, variant_id=line.variant_id)
            if variant is None or variant["status"] != "ACTIVE" or variant["product_status"] != "ACTIVE":
                raise VariantNotActive(f"variant {line.variant_id} is not active")

            available = variant["stock_on_hand"] - variant["stock_reserved"]
            if available < line.quantity:
                raise InsufficientStock(
                    f"variant {line.variant_id}: requested {line.quantity}, available {available}"
                )

            resolved = await current_price_for_variant(
                conn,
                variant_id=variant["id"],
                product_id=variant["product_id"],
                brand_id=variant["brand_id"],
                base_price=variant["price"],
            )

            if line.client_unit_price is not None and line.client_unit_price != resolved.unit_price:
                mismatches.append(
                    PriceMismatchLine(
                        variant_id=variant["id"],
                        expected_unit_price=resolved.unit_price,
                        submitted_unit_price=line.client_unit_price,
                    )
                )

            order_lines.append(
                OrderLineInput(
                    variant_id=variant["id"],
                    quantity=line.quantity,
                    product_name_snapshot=variant["product_name"],
                    variant_label_snapshot=None,
                    sku_snapshot=variant["sku"],
                    unit_price=variant["price"],
                    discount_amount=resolved.discount_amount * line.quantity,
                    required_initial_payment=variant["required_initial_payment"],
                    cost_price_snapshot=variant["cost_price"],
                )
            )

        if mismatches:
            # §7.3: "Narx farq qilsa -> 409 Conflict + yangi narx" — nothing
            # has been written yet (the transaction block simply raises and
            # rolls back), so re-checkout with the corrected price is clean.
            raise PriceMismatch(mismatches)

        order_number = generate_order_number()
        order = await orders_repository.create_order(conn, user_id=user_id, order_number=order_number, lines=order_lines)

        for order_line in order_lines:
            await reservations_repository.reserve_stock(
                conn,
                order_id=order["id"],
                variant_id=order_line.variant_id,
                quantity=order_line.quantity,
                actor_id=user_id,
            )

        # The ordered lines leave the cart in the same transaction — before
        # this nothing ever cleared it, so the cart screen kept offering
        # "checkout" for units already reserved under the new order.
        await cart_repository.remove_variants_for_user(
            conn, user_id=user_id, variant_ids=[line.variant_id for line in order_lines]
        )

        await record_audit(
            conn,
            actor_id=user_id,
            actor_role="USER",
            action="order.create",
            entity_type="order",
            entity_id=order["id"],
            new_data={"order_number": order["order_number"], "total_amount": order["total_amount"]},
            ip=ip,
        )

        return order


async def cancel_order(
    conn: asyncpg.Connection,
    *,
    order_id: int,
    reason: str,
    actor_id: int,
    actor_role: str,
    ip: str | None = None,
) -> asyncpg.Record:
    """§8.4: reason mandatory (DB CHECK backs the >=10 chars rule). Releases
    every active reservation for this order using the mandatory guarded
    pattern — never an unconditional UPDATE."""
    if not reason or len(reason.strip()) < 10:
        raise ValueError("cancellation_reason must be at least 10 characters")

    async with conn.transaction():
        current = await orders_repository.get_order_for_update(conn, order_id=order_id)
        if current is None:
            raise LookupError(f"order {order_id} not found")
        if current["status"] == "CONFIRMED" or current["paid_amount"] > 0:
            # ADR-017/§10: a CONFIRMED order — or any order with an approved
            # payment even before confirmation (OPEN-9) — routes cancellation
            # through cancellation_requests + admin decision, never this
            # endpoint. Checked before the state-machine lookup: the table
            # now allows CONFIRMED -> CANCELLED (for the dedicated
            # cancellations service), but this generic endpoint must never
            # reach that transition regardless of paid_amount (a CONFIRMED
            # order reached via a test/edge-case path with paid_amount == 0
            # must still be rejected here).
            raise OrderHasApprovedPayment(
                f"order {order_id} is CONFIRMED or has an approved payment; file a cancellation request instead"
            )
        assert_transition_allowed(current["status"], "CANCELLED")

        updated = await orders_repository.transition_status(
            conn,
            order_id=order_id,
            from_statuses=[current["status"]],
            to_status="CANCELLED",
            extra_set_sql="cancellation_reason = $4, cancelled_at = now(), cancelled_by = $5",
            extra_params=[reason, actor_id],
        )
        if updated is None:
            raise LookupError("order status changed concurrently — retry")

        reservations = await reservations_repository.get_active_reservations_for_order(conn, order_id=order_id)
        for reservation in reservations:
            await reservations_repository.release_reservation(conn, reservation_id=reservation["id"], actor_id=actor_id)

        await record_audit(
            conn,
            actor_id=actor_id,
            actor_role=actor_role,
            action="order.cancel",
            entity_type="order",
            entity_id=order_id,
            old_data={"status": current["status"]},
            new_data={"status": "CANCELLED", "cancellation_reason": reason},
            ip=ip,
        )

        return await orders_repository.get_order(conn, order_id=order_id)


async def confirm_order(
    conn: asyncpg.Connection, *, order_id: int, actor_id: int, actor_role: str, ip: str | None = None
) -> asyncpg.Record:
    """§8.2, exact pattern: FOR UPDATE row lock, guarded transition,
    stock decrement, inventory_movements insert, audit insert — one
    transaction. The second concurrent admin's attempt fails at the guarded
    UPDATE (0 rows affected because status is no longer UNDER_REVIEW by the
    time it gets the lock) and gets a clear error, never a silent
    double-decrement."""
    async with conn.transaction():
        current = await orders_repository.get_order_for_update(conn, order_id=order_id)
        if current is None:
            raise LookupError(f"order {order_id} not found")
        if current["status"] != "UNDER_REVIEW":
            raise state_machine_error(current["status"])

        updated = await orders_repository.transition_status(
            conn,
            order_id=order_id,
            from_statuses=["UNDER_REVIEW"],
            to_status="CONFIRMED",
            extra_set_sql="confirmed_at = now(), confirmed_by = $4",
            extra_params=[actor_id],
        )
        if updated is None:
            # Another admin's transaction won the race between our FOR
            # UPDATE read and this guarded UPDATE — extremely unlikely given
            # the row lock, but the guard is the actual safety net, not the
            # lock alone.
            raise ConcurrentConfirmation(order_id)

        items = await orders_repository.get_order_items(conn, order_id=order_id)
        for item in items:
            # Guarded, like every other stock mutation: the CHECK constraints
            # are the last backstop, but a raw CheckViolation here surfaced
            # as an unexplained 500. A confirm whose reservation is no
            # longer held (expired and released by the worker, then the
            # stock sold elsewhere) must fail with a clear error instead.
            row = await conn.fetchrow(
                """
                UPDATE product_variants
                SET stock_on_hand = stock_on_hand - $2, stock_reserved = stock_reserved - $2, updated_at = now()
                WHERE id = $1 AND stock_on_hand >= $2 AND stock_reserved >= $2
                RETURNING stock_on_hand, stock_reserved
                """,
                item["variant_id"],
                item["quantity"],
            )
            if row is None:
                raise InsufficientStock(
                    f"variant {item['variant_id']}: reserved stock for {item['quantity']} unit(s) is no longer held"
                )
            quantity_after = row["stock_on_hand"]
            quantity_before = quantity_after + item["quantity"]
            await conn.execute(
                """
                INSERT INTO inventory_movements
                    (variant_id, movement_type, quantity_change, quantity_before, quantity_after,
                     reference_type, reference_id, actor_id)
                VALUES ($1, 'OUT', $2, $3, $4, 'order', $5, $6)
                """,
                item["variant_id"],
                -item["quantity"],
                quantity_before,
                quantity_after,
                order_id,
                actor_id,
            )

        # The reservation is *consumed* here, not released: the OUT movement
        # above already records the stock leaving, so `stock_reserved` must
        # not be decremented a second time. Before this stamp existed the
        # rows stayed `released_at IS NULL`, and 24h later the expiry worker
        # released them again — `stock_reserved` went negative (CHECK
        # violation, worker wedged on that row forever) or, with other open
        # reservations on the variant, silently under-counted (oversell).
        await reservations_repository.consume_reservations_for_order(conn, order_id=order_id)

        await record_audit(
            conn,
            actor_id=actor_id,
            actor_role=actor_role,
            action="order.confirm",
            entity_type="order",
            entity_id=order_id,
            old_data={"status": "UNDER_REVIEW"},
            new_data={"status": "CONFIRMED"},
            ip=ip,
        )

        return await orders_repository.get_order(conn, order_id=order_id)


class ConcurrentConfirmation(Exception):
    def __init__(self, order_id: int) -> None:
        super().__init__(f"order {order_id} was already confirmed/changed by another admin")


def state_machine_error(current_status: str) -> Exception:
    from app.domains.commerce.orders.state_machine import InvalidTransition

    return InvalidTransition(f"order must be UNDER_REVIEW to confirm, was {current_status}")
