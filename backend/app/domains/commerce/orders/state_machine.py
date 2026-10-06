"""§8.1's transition table, "kodda aniq jadval" (an explicit table in code)
— not DB-enforced (migration 0007_commerce's design notes explain why: a
CHECK can only validate a single row's current value, not a transition).

ADR-017 (2026-09-29): CONFIRMED -> CANCELLED is now reachable, closing
OPEN-4/OPEN-9, but ONLY via `orders/service.py::approve_cancellation_request`
— never via the generic `cancel_order` path, which still rejects any order
with `paid_amount > 0` before it ever consults this table. Refund is a
fully separate entity (`refunds` table) never implied by this transition.
"""
from __future__ import annotations

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "CREATED": {"AWAITING_PAYMENT", "CANCELLED", "EXPIRED"},
    "AWAITING_PAYMENT": {"PAYMENT_SUBMITTED", "CANCELLED", "EXPIRED"},
    "PAYMENT_SUBMITTED": {"UNDER_REVIEW", "CANCELLED", "EXPIRED"},
    "UNDER_REVIEW": {"CONFIRMED", "REJECTED", "CANCELLED", "EXPIRED"},
    "CONFIRMED": {"CANCELLED"},
    "REJECTED": {"CANCELLED"},
    "CANCELLED": set(),
    "EXPIRED": set(),
}


class InvalidTransition(Exception):
    pass


def assert_transition_allowed(current_status: str, target_status: str) -> None:
    if target_status not in ALLOWED_TRANSITIONS.get(current_status, set()):
        raise InvalidTransition(f"cannot transition order from {current_status} to {target_status}")
