"""Priority 3 of the v2 rebuild brief: IMAGE + VOICE/TEXT correlation,
exercised against a real DB — short-lived, admin+chat-bound, atomic claim."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.ai import pending_media
from tests.integration import factories

pytestmark = pytest.mark.asyncio


async def test_consume_returns_the_pending_photo(conn, clean_slate):
    admin_id = await factories.make_user(conn, role="ADMIN")
    await pending_media.create_or_replace(conn, admin_id=admin_id, chat_id=555, telegram_file_id="file-1")

    claimed = await pending_media.consume(conn, admin_id=admin_id, chat_id=555)

    assert claimed is not None
    assert claimed["telegram_file_id"] == "file-1"
    assert claimed["status"] == "CONSUMED"


async def test_consume_is_one_time(conn, clean_slate):
    admin_id = await factories.make_user(conn, role="ADMIN")
    await pending_media.create_or_replace(conn, admin_id=admin_id, chat_id=555, telegram_file_id="file-1")

    first = await pending_media.consume(conn, admin_id=admin_id, chat_id=555)
    second = await pending_media.consume(conn, admin_id=admin_id, chat_id=555)

    assert first is not None
    assert second is None


async def test_second_photo_replaces_the_first_not_stacks(conn, clean_slate):
    admin_id = await factories.make_user(conn, role="ADMIN")
    await pending_media.create_or_replace(conn, admin_id=admin_id, chat_id=555, telegram_file_id="file-1")
    await pending_media.create_or_replace(conn, admin_id=admin_id, chat_id=555, telegram_file_id="file-2")

    claimed = await pending_media.consume(conn, admin_id=admin_id, chat_id=555)

    assert claimed["telegram_file_id"] == "file-2"
    pending_rows = await conn.fetch(
        "SELECT status FROM ai_pending_media WHERE admin_id = $1 AND chat_id = $2 ORDER BY id", admin_id, 555,
    )
    assert [r["status"] for r in pending_rows] == ["EXPIRED", "CONSUMED"]


async def test_expired_context_is_not_combined(conn, clean_slate):
    admin_id = await factories.make_user(conn, role="ADMIN")
    row = await pending_media.create_or_replace(conn, admin_id=admin_id, chat_id=555, telegram_file_id="file-1")
    await conn.execute(
        "UPDATE ai_pending_media SET expires_at = $2 WHERE id = $1",
        row["id"], datetime.now(timezone.utc) - timedelta(seconds=1),
    )

    claimed = await pending_media.consume(conn, admin_id=admin_id, chat_id=555)

    assert claimed is None


async def test_wrong_admin_cannot_claim_another_admins_photo(conn, clean_slate):
    admin_id = await factories.make_user(conn, role="ADMIN")
    other_admin_id = await factories.make_user(conn, role="ADMIN")
    await pending_media.create_or_replace(conn, admin_id=admin_id, chat_id=555, telegram_file_id="file-1")

    claimed = await pending_media.consume(conn, admin_id=other_admin_id, chat_id=555)

    assert claimed is None


async def test_wrong_chat_does_not_correlate(conn, clean_slate):
    admin_id = await factories.make_user(conn, role="ADMIN")
    await pending_media.create_or_replace(conn, admin_id=admin_id, chat_id=555, telegram_file_id="file-1")

    claimed = await pending_media.consume(conn, admin_id=admin_id, chat_id=999)

    assert claimed is None


async def test_concurrent_consume_only_one_wins(pool, clean_slate):
    async with pool.acquire() as setup_conn:
        admin_id = await factories.make_user(setup_conn, role="ADMIN")
        await pending_media.create_or_replace(setup_conn, admin_id=admin_id, chat_id=555, telegram_file_id="file-1")

    async def attempt():
        async with pool.acquire() as conn:
            return await pending_media.consume(conn, admin_id=admin_id, chat_id=555)

    results = await asyncio.gather(attempt(), attempt())
    claimed = [r for r in results if r is not None]
    assert len(claimed) == 1
