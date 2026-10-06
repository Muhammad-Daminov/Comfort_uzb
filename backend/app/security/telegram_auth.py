"""Telegram `initData` HMAC verification — ADR-2. This is the *only* way a
request establishes who the caller is; `user_id`/`telegram_id` supplied by
the frontend outside of a verified initData payload is never trusted.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl

MAX_AUTH_AGE_SECONDS = 24 * 60 * 60


class InvalidInitData(Exception):
    """Raised for a missing/malformed/tampered/expired initData payload.
    Callers map this to HTTP 401 (§12.6 "Buzilgan / eskirgan initData")."""


@dataclass(frozen=True)
class TelegramUser:
    telegram_id: int
    first_name: str | None
    last_name: str | None
    username: str | None


def verify_init_data(init_data: str, bot_token: str, *, now: float | None = None) -> TelegramUser:
    """Recompute the HMAC exactly per Telegram's documented algorithm and
    ADR-2's decision. Raises InvalidInitData on any failure — hash mismatch,
    missing fields, or auth_date older than 24h."""
    if not init_data:
        raise InvalidInitData("empty initData")

    pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=False)
    data = dict(pairs)

    received_hash = data.pop("hash", None)
    if not received_hash:
        raise InvalidInitData("missing hash field")

    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(data.items()))

    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    computed_hash = hmac.new(
        secret_key, data_check_string.encode("utf-8"), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(computed_hash, received_hash):
        raise InvalidInitData("hash mismatch")

    auth_date_raw = data.get("auth_date")
    if not auth_date_raw:
        raise InvalidInitData("missing auth_date")
    try:
        auth_date = int(auth_date_raw)
    except ValueError as exc:
        raise InvalidInitData("malformed auth_date") from exc

    current_time = now if now is not None else time.time()
    if current_time - auth_date > MAX_AUTH_AGE_SECONDS:
        raise InvalidInitData("auth_date too old")
    if auth_date - current_time > 60:
        # A future auth_date beyond trivial clock skew is not legitimate.
        raise InvalidInitData("auth_date in the future")

    user_raw = data.get("user")
    if not user_raw:
        raise InvalidInitData("missing user field")

    import json

    try:
        user_obj = json.loads(user_raw)
        telegram_id = int(user_obj["id"])
    except (ValueError, KeyError, TypeError) as exc:
        raise InvalidInitData("malformed user field") from exc

    return TelegramUser(
        telegram_id=telegram_id,
        first_name=user_obj.get("first_name"),
        last_name=user_obj.get("last_name"),
        username=user_obj.get("username"),
    )
