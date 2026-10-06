"""Notification outbox poller — ADR-016 (resolves OPEN-6). Reads unsent
`notifications` rows, sends the Telegram half, and stamps
`telegram_sent_at`. Guarded and idempotent: a row is only ever selected
while `telegram_sent_at IS NULL`, and every outcome (sent, blocked-user,
permanently undeliverable, or transient Telegram error) results in the row
being marked handled exactly once or left for a later retry — the same
discipline as the reservation-release guarded pattern (Phase 02/03
`AGENTS/backend-commerce.md`), reused here rather than reinvented.

Concurrency: `comfort-api.service` runs uvicorn with `--workers 2`, so two
copies of this loop poll the same table. The batch is fetched with
`FOR UPDATE SKIP LOCKED` inside one transaction held for the whole batch —
each row belongs to exactly one poller until it is stamped, which is what
makes "exactly once" true across processes (before this, both workers
fetched, both sent, and only the second stamp was a no-op).
"""
from __future__ import annotations

import asyncio
import logging

import asyncpg
from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNotFound,
    TelegramRetryAfter,
)

from app.domains.identity import service as identity_service
from bot.locales import uz

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 50
MAX_RETRY_AFTER_SECONDS = 60


async def _fetch_unsent(conn: asyncpg.Connection, *, batch_size: int) -> list[asyncpg.Record]:
    return await conn.fetch(
        """
        SELECT n.id, n.title, n.body, u.telegram_id, u.bot_blocked_at, u.telegram_notifications_enabled
        FROM notifications n
        JOIN users u ON u.id = n.user_id
        WHERE n.telegram_sent_at IS NULL
          AND u.deleted_at IS NULL
        ORDER BY n.created_at
        LIMIT $1
        FOR UPDATE OF n SKIP LOCKED
        """,
        batch_size,
    )


async def _mark_sent(conn: asyncpg.Connection, *, notification_id: int) -> bool:
    row = await conn.fetchrow(
        "UPDATE notifications SET telegram_sent_at = now() "
        "WHERE id = $1 AND telegram_sent_at IS NULL RETURNING id",
        notification_id,
    )
    return row is not None


def _format_message(row: asyncpg.Record) -> str:
    text = uz.NOTIFICATION_PREFIX + row["title"]
    if row["body"]:
        text += f"\n\n{row['body']}"
    return text


async def poll_loop(conn: asyncpg.Connection, bot: Bot, *, batch_size: int = DEFAULT_BATCH_SIZE) -> int:
    """Processes up to `batch_size` unsent notifications in one call.
    Returns the number of rows actually sent via Telegram (blocked-user
    rows marked handled don't count as "sent"). Safe to call repeatedly —
    a second call with nothing new pending sends nothing."""
    async with conn.transaction():
        rows = await _fetch_unsent(conn, batch_size=batch_size)
        sent_count = 0

        for row in rows:
            if row["bot_blocked_at"] is not None:
                # ADR-12: a blocked user only gets the in-app half. Marking it
                # handled prevents the poller from retrying it every cycle —
                # the notifications row itself remains visible in the Mini App.
                await _mark_sent(conn, notification_id=row["id"])
                continue

            if not row["telegram_notifications_enabled"]:
                # §P3B-2: the user opted out of the Telegram channel
                # specifically (`PATCH /auth/me/notification-settings`) —
                # same "in-app half always persists, Telegram half skipped
                # and marked handled" shape as the blocked-user case above,
                # just a different reason for skipping.
                await _mark_sent(conn, notification_id=row["id"])
                continue

            try:
                await bot.send_message(row["telegram_id"], _format_message(row))
            except TelegramForbiddenError:
                await identity_service.mark_bot_blocked(conn, telegram_id=row["telegram_id"])
                await _mark_sent(conn, notification_id=row["id"])
                continue
            except TelegramRetryAfter as exc:
                # 429: Telegram told us how long to wait. Stop this batch (the
                # remaining rows stay unsent and are picked up next cycle)
                # instead of hammering it with the rest of the batch.
                wait = min(max(int(exc.retry_after), 1), MAX_RETRY_AFTER_SECONDS)
                logger.warning("telegram rate limit hit — pausing notifications for %ss", wait)
                await asyncio.sleep(wait)
                break
            except (TelegramNotFound, TelegramBadRequest) as exc:
                # Permanent for this row ("chat not found": the user never
                # opened a chat with the bot; deactivated account). Retrying
                # every 5s forever also parked the row at the head of the
                # `ORDER BY created_at LIMIT 50` batch — 50 such rows and no
                # newer notification was ever sent. Mark handled, keep the
                # in-app half.
                logger.warning("notification id=%s undeliverable (%s) — marked handled", row["id"], exc)
                await _mark_sent(conn, notification_id=row["id"])
                continue
            except TelegramAPIError:
                # Transient Telegram-side failure (network, 5xx) — log and
                # leave `telegram_sent_at` NULL so the next poll retries it;
                # never let one bad send stop the whole batch.
                logger.exception("failed to send notification id=%s", row["id"])
                continue

            marked = await _mark_sent(conn, notification_id=row["id"])
            if marked:
                sent_count += 1

    return sent_count
