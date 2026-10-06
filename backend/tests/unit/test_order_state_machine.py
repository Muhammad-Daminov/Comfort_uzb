import pytest

from app.domains.commerce.orders.state_machine import InvalidTransition, assert_transition_allowed


def test_created_can_move_to_awaiting_payment():
    assert_transition_allowed("CREATED", "AWAITING_PAYMENT")


def test_under_review_can_move_to_confirmed():
    assert_transition_allowed("UNDER_REVIEW", "CONFIRMED")


def test_confirmed_can_only_reach_cancelled():
    # ADR-017: CONFIRMED -> CANCELLED is now reachable in the transition
    # table (via cancellation_requests + admin decision only — enforced in
    # orders/cancellations service code, not this table), but nothing else.
    assert_transition_allowed("CONFIRMED", "CANCELLED")
    with pytest.raises(InvalidTransition):
        assert_transition_allowed("CONFIRMED", "REJECTED")
    with pytest.raises(InvalidTransition):
        assert_transition_allowed("CONFIRMED", "EXPIRED")


def test_cancelled_is_terminal():
    with pytest.raises(InvalidTransition):
        assert_transition_allowed("CANCELLED", "CONFIRMED")


def test_refund_is_not_an_order_status():
    # ADR-017: refund is tracked in the independent `refunds` table, never
    # as an orders.status value — REFUND_PENDING/REFUNDED are still not (and
    # will never be) rows in this transition table.
    with pytest.raises(InvalidTransition):
        assert_transition_allowed("CONFIRMED", "REFUND_PENDING")


def test_invalid_transition_rejected():
    with pytest.raises(InvalidTransition):
        assert_transition_allowed("CREATED", "CONFIRMED")
