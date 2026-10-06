"""Shared audit-write helper (§12.3). The one hard rule (Phase 0 review
correction, reiterated in AGENTS/security.md and AGENTS/backend-commerce.md):
this function must be called with the *same* connection/transaction the
caller is already using for its business-logic writes — it never acquires
its own connection — so that a rollback of the caller's transaction rolls
the audit row back too. Nothing here starts or commits a transaction; that
is entirely the caller's responsibility.
"""
from __future__ import annotations

import json
from typing import Any

import asyncpg


async def record_audit(
    conn: asyncpg.Connection,
    *,
    actor_id: int | None,
    actor_role: str | None,
    action: str,
    entity_type: str,
    entity_id: int | None,
    old_data: dict[str, Any] | None = None,
    new_data: dict[str, Any] | None = None,
    ip: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    await conn.execute(
        """
        INSERT INTO audit_logs
            (actor_id, actor_role, action, entity_type, entity_id, old_data, new_data, ip, metadata)
        VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8, $9::jsonb)
        """,
        actor_id,
        actor_role,
        action,
        entity_type,
        entity_id,
        json.dumps(old_data) if old_data is not None else None,
        json.dumps(new_data) if new_data is not None else None,
        ip,
        json.dumps(metadata) if metadata is not None else None,
    )
