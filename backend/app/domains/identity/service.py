from __future__ import annotations

import re

import asyncpg

from app.domains.identity import repository
from app.security import session as session_module
from app.security.telegram_auth import verify_init_data

_PHONE_ALLOWED_CHARS = re.compile(r"[\s\-()]")
_PHONE_SHAPE = re.compile(r"^\+998[0-9]{9}$")


class InvalidPhone(Exception):
    pass


async def authenticate(
    conn: asyncpg.Connection, *, init_data: str, bot_token: str, session_secret: str
) -> tuple[str, asyncpg.Record]:
    """Raises telegram_auth.InvalidInitData on a bad payload (-> 401)."""
    telegram_user = verify_init_data(init_data, bot_token)
    user = await repository.find_or_create_user(
        conn,
        telegram_id=telegram_user.telegram_id,
        first_name=telegram_user.first_name,
        last_name=telegram_user.last_name,
        username=telegram_user.username,
    )
    if user["status"] != "ACTIVE":
        # A deactivated user re-authenticating still doesn't get a session.
        raise PermissionError("account is deactivated")
    token = session_module.issue(user["id"], session_secret)
    return token, user


def normalize_phone(raw_phone: str) -> str:
    """§5.3: "Yozishdan oldin normalizatsiya: bo'shliq, -, (, ) olib
    tashlanadi" (strip whitespace, -, (, ) before writing). Raises
    InvalidPhone if the result doesn't match the required shape — the same
    check the DB CHECK constraint enforces, surfaced here as a clear
    application-level error before the INSERT/UPDATE is even attempted."""
    normalized = _PHONE_ALLOWED_CHARS.sub("", raw_phone)
    if normalized and not normalized.startswith("+"):
        # Telegram's contact.phone_number is commonly delivered without a
        # leading '+' (e.g. "998901234567") even though it's the same
        # international-format number the '+' variant represents.
        normalized = f"+{normalized}"
    if not _PHONE_SHAPE.match(normalized):
        raise InvalidPhone(f"phone must match +998XXXXXXXXX, got {raw_phone!r}")
    return normalized


async def record_phone(conn: asyncpg.Connection, *, user_id: int, raw_phone: str) -> asyncpg.Record:
    """Bot's phone-capture flow (Phase-04, `KeyboardButton(request_contact=
    True)`, §1 ADR-2) calls this — never writes `users.phone` directly."""
    normalized = normalize_phone(raw_phone)
    updated = await repository.update_phone(conn, user_id=user_id, phone=normalized)
    if updated is None:
        raise LookupError(f"user {user_id} not found")
    return updated


async def get_or_create_user_from_telegram(
    conn: asyncpg.Connection, *, telegram_id: int, first_name: str | None, last_name: str | None, username: str | None
) -> asyncpg.Record:
    """Bot's `/start` handler calls this — the exact same Repository
    function the Mini App's `POST /auth/session` path uses (`authenticate`
    above), so there is exactly one place a user row is ever created,
    regardless of which client (bot or Mini App) the user arrives through
    first."""
    return await repository.find_or_create_user(
        conn, telegram_id=telegram_id, first_name=first_name, last_name=last_name, username=username
    )


async def mark_bot_blocked(conn: asyncpg.Connection, *, telegram_id: int) -> bool:
    """ADR-12. Returns True if this call actually recorded the block (the
    guarded UPDATE affected a row), False if it was already recorded —
    mirrors the reservation-release no-op contract from Phase 02/03."""
    row = await repository.mark_bot_blocked(conn, telegram_id=telegram_id)
    return row is not None


async def clear_bot_blocked(conn: asyncpg.Connection, *, telegram_id: int) -> bool:
    """ADR-12: cleared when the user presses /start again."""
    row = await repository.clear_bot_blocked(conn, telegram_id=telegram_id)
    return row is not None
