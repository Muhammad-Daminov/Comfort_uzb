"""Session tokens issued by `POST /auth/session` after initData verification.

Deliberately minimal: the token carries only `user_id` and an expiry, HMAC
signed. It never carries `role` or `status` — every request that needs
permission enforcement re-reads the user's current role/status from the
database (see `security/permissions.py`), which is what makes "deactivated
admin still tries to act -> 403" (§12.6) work even against an old,
still-unexpired token. No new table is introduced for sessions; the token
itself is the credential, matching IDENTITY's actual schema (no `sessions`
table exists — Phase-02 did not create one, and this is a routine
implementation choice within ADR-2, not a schema change).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import time

SESSION_TTL_SECONDS = 24 * 60 * 60


class InvalidSession(Exception):
    """Missing/malformed/tampered/expired session token -> HTTP 401."""


def issue(user_id: int, secret: str, *, now: float | None = None) -> str:
    current_time = now if now is not None else time.time()
    expires_at = int(current_time) + SESSION_TTL_SECONDS
    payload = f"{user_id}:{expires_at}"
    signature = _sign(payload, secret)
    token_bytes = f"{payload}:{signature}".encode("utf-8")
    return base64.urlsafe_b64encode(token_bytes).decode("ascii")


def verify(token: str, secret: str, *, now: float | None = None) -> int:
    """Returns the user_id encoded in the token. Raises InvalidSession
    otherwise."""
    try:
        raw = base64.urlsafe_b64decode(token.encode("ascii")).decode("utf-8")
        user_id_raw, expires_at_raw, signature = raw.split(":")
    except (ValueError, UnicodeDecodeError) as exc:
        raise InvalidSession("malformed token") from exc

    payload = f"{user_id_raw}:{expires_at_raw}"
    expected_signature = _sign(payload, secret)
    if not hmac.compare_digest(expected_signature, signature):
        raise InvalidSession("signature mismatch")

    current_time = now if now is not None else time.time()
    try:
        expires_at = int(expires_at_raw)
        user_id = int(user_id_raw)
    except ValueError as exc:
        raise InvalidSession("malformed token fields") from exc

    if current_time > expires_at:
        raise InvalidSession("token expired")

    return user_id


def _sign(payload: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
