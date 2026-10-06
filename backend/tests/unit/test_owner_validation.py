"""Unit tests for Phase 07 owner-domain logic that doesn't need a DB —
date-range validation, audit redaction, admin-creation request shape."""
from datetime import datetime, timedelta, timezone

import pytest

from app.domains.owner.repository import _redact
from app.domains.owner.router import CreateAdminRequest
from app.domains.owner.service import InvalidDateRange, validate_date_range


def test_valid_date_range_passes():
    validate_date_range(datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 31, tzinfo=timezone.utc))


def test_to_before_from_is_rejected():
    with pytest.raises(InvalidDateRange):
        validate_date_range(datetime(2026, 1, 31, tzinfo=timezone.utc), datetime(2026, 1, 1, tzinfo=timezone.utc))


def test_equal_from_and_to_is_rejected():
    same = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with pytest.raises(InvalidDateRange):
        validate_date_range(same, same)


def test_range_exceeding_max_days_is_rejected():
    date_from = datetime(2026, 1, 1, tzinfo=timezone.utc)
    date_to = date_from + timedelta(days=400)
    with pytest.raises(InvalidDateRange):
        validate_date_range(date_from, date_to)


def test_redact_removes_sensitive_keys_case_insensitively():
    data = {"Password": "hunter2", "user_token": "abc", "note": "fine", "api_secret": "xyz"}
    redacted = _redact(data)
    assert redacted["Password"] == "[REDACTED]"
    assert redacted["user_token"] == "[REDACTED]"
    assert redacted["api_secret"] == "[REDACTED]"
    assert redacted["note"] == "fine"


def test_redact_recurses_into_nested_structures():
    data = {"outer": {"credential_id": "secret-value", "safe": 1}, "list": [{"token": "x"}]}
    redacted = _redact(data)
    assert redacted["outer"]["credential_id"] == "[REDACTED]"
    assert redacted["outer"]["safe"] == 1
    assert redacted["list"][0]["token"] == "[REDACTED]"


def test_create_admin_request_has_no_role_field():
    # Structural guarantee against privilege escalation via request body —
    # a client literally cannot send "role" because the model has no such
    # field; extra fields are ignored by Pydantic v2's default config, not
    # silently accepted as an override.
    assert "role" not in CreateAdminRequest.model_fields
