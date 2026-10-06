from __future__ import annotations

import asyncpg


async def find_or_create_user(
    conn: asyncpg.Connection,
    *,
    telegram_id: int,
    first_name: str | None,
    last_name: str | None,
    username: str | None,
) -> asyncpg.Record:
    row = await conn.fetchrow(
        "SELECT id, telegram_id, role, status FROM users WHERE telegram_id = $1 AND deleted_at IS NULL",
        telegram_id,
    )
    if row is not None:
        return row

    # First login: role defaults to USER (§3 — OWNER is seeded once by
    # ADR-11's bootstrap migration, never created here; ADMIN is granted
    # out-of-band by an OWNER via `admins.manage`, not self-service).
    row = await conn.fetchrow(
        """
        INSERT INTO users (telegram_id, role, status, first_name, last_name, username)
        VALUES ($1, 'USER', 'ACTIVE', $2, $3, $4)
        ON CONFLICT (telegram_id) DO UPDATE SET telegram_id = EXCLUDED.telegram_id
        RETURNING id, telegram_id, role, status
        """,
        telegram_id,
        first_name,
        last_name,
        username,
    )
    return row


async def find_by_telegram_id(conn: asyncpg.Connection, *, telegram_id: int) -> asyncpg.Record | None:
    """Read-only lookup — unlike find_or_create_user, never inserts a row.
    Used by the bot's AI-assistant role check (bot/handlers/ai.py): a
    message from someone with no account yet must be treated as
    unauthorized, not silently registered as a USER."""
    return await conn.fetchrow(
        "SELECT id, telegram_id, role, status FROM users WHERE telegram_id = $1 AND deleted_at IS NULL",
        telegram_id,
    )


async def get_by_id(conn: asyncpg.Connection, *, user_id: int) -> asyncpg.Record | None:
    return await conn.fetchrow(
        "SELECT id, telegram_id, first_name, last_name, username, role, phone, status, "
        "telegram_notifications_enabled FROM users WHERE id = $1 AND deleted_at IS NULL",
        user_id,
    )


async def set_telegram_notifications_enabled(
    conn: asyncpg.Connection, *, user_id: int, enabled: bool
) -> asyncpg.Record | None:
    """§P3B-2: the caller's own preference only — `user_id` here always
    comes from the signed session token (`get_current_user`), never a
    client-supplied id, so there is no path for one user to touch
    another's row (see app/domains/identity/router.py)."""
    return await conn.fetchrow(
        "UPDATE users SET telegram_notifications_enabled = $2, updated_at = now() "
        "WHERE id = $1 AND deleted_at IS NULL RETURNING id, telegram_notifications_enabled",
        user_id,
        enabled,
    )


async def update_phone(conn: asyncpg.Connection, *, user_id: int, phone: str) -> asyncpg.Record | None:
    """§5.3's format/uniqueness is enforced by the existing CHECK + partial
    unique index (migration 0001_identity) — this is a plain guarded
    UPDATE; a `UniqueViolation`/`CheckViolation` from Postgres is the
    caller's signal to map to a user-facing error, not something re-checked
    here first (single source of truth for the constraint, per ADR-015's
    Repository-layer conventions)."""
    return await conn.fetchrow(
        "UPDATE users SET phone = $2, updated_at = now() WHERE id = $1 RETURNING id, phone",
        user_id,
        phone,
    )


async def mark_bot_blocked(conn: asyncpg.Connection, *, telegram_id: int) -> asyncpg.Record | None:
    """ADR-12: `UPDATE users SET bot_blocked_at = now() WHERE telegram_id = ?`
    — copied verbatim. Guarded by `bot_blocked_at IS NULL` so a second
    Forbidden response for an already-blocked user is a no-op, not a
    timestamp overwrite."""
    return await conn.fetchrow(
        "UPDATE users SET bot_blocked_at = now() WHERE telegram_id = $1 AND bot_blocked_at IS NULL "
        "RETURNING id, telegram_id",
        telegram_id,
    )


async def clear_bot_blocked(conn: asyncpg.Connection, *, telegram_id: int) -> asyncpg.Record | None:
    """ADR-12: "Qayta /start bosganda bot_blocked_at = NULL" (bot_blocked_at
    cleared when the user presses /start again — they can only do that if
    the bot isn't actually blocked anymore)."""
    return await conn.fetchrow(
        "UPDATE users SET bot_blocked_at = NULL WHERE telegram_id = $1 AND bot_blocked_at IS NOT NULL "
        "RETURNING id, telegram_id",
        telegram_id,
    )
