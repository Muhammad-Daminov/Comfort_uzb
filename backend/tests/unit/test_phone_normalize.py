"""§5.3: phone normalization strips whitespace/-/(), and the bot's
contact-share path (no leading '+') is accepted the same as a typed one."""
import pytest

from app.domains.identity.service import InvalidPhone, normalize_phone


def test_strips_spaces_dashes_and_parens():
    assert normalize_phone("+998 (90) 123-45-67") == "+998901234567"


def test_adds_missing_leading_plus():
    assert normalize_phone("998901234567") == "+998901234567"


def test_already_normalized_passes_through():
    assert normalize_phone("+998901234567") == "+998901234567"


def test_wrong_country_code_rejected():
    with pytest.raises(InvalidPhone):
        normalize_phone("+7 901 234 56 78")


def test_too_short_rejected():
    with pytest.raises(InvalidPhone):
        normalize_phone("+99890123")


def test_non_numeric_rejected():
    with pytest.raises(InvalidPhone):
        normalize_phone("not-a-phone")
