"""Priority 3 of the v2 rebuild brief: correlate a PHOTO with a following
VOICE/TEXT message into one CREATE_PRODUCT command, without an indefinite
or cross-admin/cross-chat binding.

    PHOTO (no caption) -> pending media context (admin_id, chat_id, TTL)
    VOICE/TEXT within window, same admin+chat -> consumed, combined
    window expired -> processed independently, never silently combined

No file bytes live here — only the Telegram file_id. The actual download
still happens exactly once, at AI-draft confirm time
(app/ai/executor.py::_attach_telegram_image).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import asyncpg

CORRELATION_WINDOW = timedelta(minutes=2)


async def create_or_replace(
    conn: asyncpg.Connection, *, admin_id: int, chat_id: int, telegram_file_id: str
) -> asyncpg.Record:
    """A second photo from the same admin/chat replaces the first pending
    context rather than stacking — this is what makes "duplicate media"
    well-defined instead of ambiguous."""
    async with conn.transaction():
        await conn.execute(
            "UPDATE ai_pending_media SET status = 'EXPIRED' WHERE admin_id = $1 AND chat_id = $2 AND status = 'PENDING'",
            admin_id,
            chat_id,
        )
        expires_at = datetime.now(timezone.utc) + CORRELATION_WINDOW
        return await conn.fetchrow(
            """
            INSERT INTO ai_pending_media (admin_id, chat_id, telegram_file_id, media_type, expires_at)
            VALUES ($1, $2, $3, 'PHOTO', $4)
            RETURNING *
            """,
            admin_id,
            chat_id,
            telegram_file_id,
            expires_at,
        )


async def consume(conn: asyncpg.Connection, *, admin_id: int, chat_id: int) -> asyncpg.Record | None:
    """Atomic claim: a guarded UPDATE, not a SELECT-then-UPDATE — two
    messages racing to correlate against the same photo can never both
    succeed (mirrors ai_command_drafts' confirm() claim pattern)."""
    return await conn.fetchrow(
        """
        UPDATE ai_pending_media
        SET status = 'CONSUMED'
        WHERE admin_id = $1 AND chat_id = $2 AND status = 'PENDING' AND expires_at > now()
        RETURNING *
        """,
        admin_id,
        chat_id,
    )
