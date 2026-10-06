import pytest

from app.security.session import InvalidSession, issue, verify

SECRET = "test-session-secret"


def test_issue_then_verify_roundtrips_user_id():
    token = issue(7, SECRET)
    assert verify(token, SECRET) == 7


def test_tampered_token_is_rejected():
    token = issue(7, SECRET)
    tampered = token[:-2] + ("AA" if token[-2:] != "AA" else "BB")
    with pytest.raises(InvalidSession):
        verify(tampered, SECRET)


def test_wrong_secret_is_rejected():
    token = issue(7, SECRET)
    with pytest.raises(InvalidSession):
        verify(token, "wrong-secret")


def test_expired_token_is_rejected():
    token = issue(7, SECRET, now=1_000_000)
    with pytest.raises(InvalidSession):
        verify(token, SECRET, now=1_000_000 + 25 * 60 * 60)


def test_malformed_token_is_rejected():
    with pytest.raises(InvalidSession):
        verify("not-a-valid-token", SECRET)
