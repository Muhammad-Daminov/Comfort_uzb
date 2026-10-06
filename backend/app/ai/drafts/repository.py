from __future__ import annotations

import json

import asyncpg


async def create_draft(
    conn: asyncpg.Connection,
    *,
    admin_id: int,
    command_type: str,
    payload: dict,
    source: str,
    confirmation_token: str,
    expires_at,
) -> asyncpg.Record:
    return await conn.fetchrow(
        """
        INSERT INTO ai_command_drafts (admin_id, command_type, payload, source, confirmation_token, expires_at)
        VALUES ($1, $2, $3::jsonb, $4, $5, $6)
        RETURNING *
        """,
        admin_id,
        command_type,
        json.dumps(payload),
        source,
        confirmation_token,
        expires_at,
    )


async def get_draft(conn: asyncpg.Connection, *, draft_id: int) -> asyncpg.Record | None:
    return await conn.fetchrow("SELECT * FROM ai_command_drafts WHERE id = $1", draft_id)


async def get_draft_for_update(conn: asyncpg.Connection, *, draft_id: int) -> asyncpg.Record | None:
    return await conn.fetchrow("SELECT * FROM ai_command_drafts WHERE id = $1 FOR UPDATE", draft_id)


async def mark_confirmed(
    conn: asyncpg.Connection, *, draft_id: int, result_entity_type: str | None, result_entity_id: int | None
) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        UPDATE ai_command_drafts
        SET status = 'CONFIRMED', confirmed_at = now(), result_entity_type = $2, result_entity_id = $3
        WHERE id = $1 AND status = 'PENDING'
        RETURNING *
        """,
        draft_id,
        result_entity_type,
        result_entity_id,
    )


async def mark_failed(conn: asyncpg.Connection, *, draft_id: int, error: str) -> asyncpg.Record | None:
    return await conn.fetchrow(
        "UPDATE ai_command_drafts SET status = 'FAILED', error = $2 WHERE id = $1 AND status = 'PENDING' RETURNING *",
        draft_id,
        error,
    )


async def mark_cancelled(conn: asyncpg.Connection, *, draft_id: int) -> asyncpg.Record | None:
    return await conn.fetchrow(
        "UPDATE ai_command_drafts SET status = 'CANCELLED' WHERE id = $1 AND status = 'PENDING' RETURNING *",
        draft_id,
    )


async def expire_stale(conn: asyncpg.Connection) -> int:
    result = await conn.execute(
        "UPDATE ai_command_drafts SET status = 'EXPIRED' WHERE status = 'PENDING' AND expires_at < now()"
    )
    return int(result.split()[-1]) if result else 0
