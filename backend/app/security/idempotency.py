"""Idempotency-Key handling (ADR-7). Wraps the mutating endpoints ADR-7
names: order creation, payment submission, receipt upload, admin
confirm/cancel, admin inventory adjust.

Usage pattern (Router layer): the endpoint calls `check_idempotency_key`
first; if it returns a stored response, the Router returns that verbatim
without calling the Service layer at all. Otherwise the Router runs the
Service call as normal and then calls `store_idempotency_result` with the
outcome. This is a helper pair, not a framework-level middleware, because
the "response to replay" differs per endpoint and the caller is best placed
to decide what counts as the request body to hash.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import asyncpg
from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder


class IdempotencyKeyReused(HTTPException):
    """The same key was reused with a different request body — this is a
    client bug (reusing a key across unrelated requests violates ADR-7's
    24h-scoped-to-one-action contract), not a replay."""

    def __init__(self) -> None:
        super().__init__(status_code=422, detail="Idempotency-Key reused with a different request")


@dataclass(frozen=True)
class StoredResult:
    status_code: int
    response_body: dict[str, Any] | None


def hash_request(body: dict[str, Any]) -> str:
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def check_idempotency_key(
    conn: asyncpg.Connection,
    *,
    key: UUID,
    endpoint: str,
    user_id: int,
    request_hash: str,
) -> StoredResult | None:
    row = await conn.fetchrow(
        "SELECT endpoint, user_id, request_hash, response_body, status_code "
        "FROM idempotency_keys WHERE key = $1",
        key,
    )
    if row is None:
        return None

    if row["endpoint"] != endpoint or row["user_id"] != user_id or row["request_hash"] != request_hash:
        raise IdempotencyKeyReused()

    body = json.loads(row["response_body"]) if row["response_body"] is not None else None
    return StoredResult(status_code=row["status_code"], response_body=body)


async def store_idempotency_result(
    conn: asyncpg.Connection,
    *,
    key: UUID,
    endpoint: str,
    user_id: int,
    request_hash: str,
    status_code: int,
    response_body: dict[str, Any] | None,
) -> None:
    await conn.execute(
        """
        INSERT INTO idempotency_keys (key, endpoint, user_id, request_hash, response_body, status_code)
        VALUES ($1, $2, $3, $4, $5::jsonb, $6)
        ON CONFLICT (key) DO NOTHING
        """,
        key,
        endpoint,
        user_id,
        request_hash,
        # jsonable_encoder — not a bare json.dumps — because response
        # bodies here are built from asyncpg Record -> dict conversions
        # that still carry datetime/UUID/Decimal values; FastAPI's encoder
        # is what the framework already uses to serialize the same shapes
        # for the actual HTTP response, so replaying a stored result stays
        # byte-for-byte consistent with a fresh one.
        json.dumps(jsonable_encoder(response_body)) if response_body is not None else None,
        status_code,
    )


@dataclass
class IdempotencyScope:
    """What a Router sees inside `idempotent_scope`. `stored` is the replay
    (the Service call must be skipped); otherwise the Router runs the Service
    call and reports the outcome through `set_result`."""

    stored: StoredResult | None
    status_code: int | None = None
    response_body: dict[str, Any] | None = None

    def set_result(self, status_code: int, response_body: dict[str, Any] | None) -> None:
        self.status_code = status_code
        self.response_body = response_body

    @property
    def result(self) -> StoredResult:
        if self.stored is not None:
            return self.stored
        if self.status_code is None:
            raise RuntimeError("idempotent_scope exited without a result")
        return StoredResult(status_code=self.status_code, response_body=self.response_body)


@asynccontextmanager
async def idempotent_scope(
    conn: asyncpg.Connection, *, key: UUID, endpoint: str, user_id: int, request_hash: str
) -> AsyncIterator[IdempotencyScope]:
    """Check → run → store as ONE unit. The plain check/store pair above is
    not atomic: two identical requests arriving together both saw no stored
    row, both ran the Service call, and `ON CONFLICT DO NOTHING` then hid the
    duplicate — a double-tapped checkout created two orders and reserved the
    stock twice (reproduced live during the audit with 4 concurrent calls).

    A transaction-scoped advisory lock keyed on (endpoint, key) serialises
    same-key requests: the second waits, then finds the first's stored row
    and replays it. Service calls open their own `conn.transaction()` inside
    this one, which asyncpg turns into a savepoint — a Service failure
    (409/422) rolls back only its own writes and the outcome is still stored.
    An unexpected exception unwinds the whole transaction, so nothing is
    stored and a retry gets a clean run.

    HTTP errors must be raised by the caller AFTER the block exits (the
    stored-result INSERT commits on exit), never from inside it."""
    async with conn.transaction():
        await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))", f"{endpoint}:{key}")
        stored = await check_idempotency_key(
            conn, key=key, endpoint=endpoint, user_id=user_id, request_hash=request_hash
        )
        scope = IdempotencyScope(stored=stored)
        yield scope
        if stored is None:
            await store_idempotency_result(
                conn,
                key=key,
                endpoint=endpoint,
                user_id=user_id,
                request_hash=request_hash,
                status_code=scope.result.status_code,
                response_body=scope.result.response_body,
            )
