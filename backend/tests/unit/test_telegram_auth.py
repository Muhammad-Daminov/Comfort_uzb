"""Unit tests for ADR-2's initData HMAC verification — §12.6 "Buzilgan /
eskirgan initData -> 401"."""
import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest

from app.security.telegram_auth import InvalidInitData, verify_init_data

BOT_TOKEN = "123456:FAKE_TOKEN_FOR_TESTS"


def _build_init_data(*, auth_date: int, telegram_id: int = 42, tamper: bool = False) -> str:
    user = json.dumps({"id": telegram_id, "first_name": "Ali", "username": "ali"})
    data = {"auth_date": str(auth_date), "user": user, "query_id": "AA"}
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if tamper:
        computed_hash = "0" * 64
    data["hash"] = computed_hash
    return urlencode(data)


def test_valid_init_data_is_accepted():
    init_data = _build_init_data(auth_date=int(time.time()))
    user = verify_init_data(init_data, BOT_TOKEN)
    assert user.telegram_id == 42


def test_tampered_hash_is_rejected():
    init_data = _build_init_data(auth_date=int(time.time()), tamper=True)
    with pytest.raises(InvalidInitData):
        verify_init_data(init_data, BOT_TOKEN)


def test_expired_auth_date_is_rejected():
    stale = int(time.time()) - (25 * 60 * 60)
    init_data = _build_init_data(auth_date=stale)
    with pytest.raises(InvalidInitData):
        verify_init_data(init_data, BOT_TOKEN)


def test_missing_hash_is_rejected():
    with pytest.raises(InvalidInitData):
        verify_init_data("auth_date=123&user=%7B%7D", BOT_TOKEN)


def test_empty_init_data_is_rejected():
    with pytest.raises(InvalidInitData):
        verify_init_data("", BOT_TOKEN)


def test_wrong_bot_token_is_rejected():
    init_data = _build_init_data(auth_date=int(time.time()))
    with pytest.raises(InvalidInitData):
        verify_init_data(init_data, "different-token")
