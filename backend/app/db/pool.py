"""The single asyncpg pool for the whole application (ADR-015). Repository
code never opens its own connection — it receives one via FastAPI's
dependency injection (`get_conn`) or, for a transaction spanning multiple
Repository calls, the Service layer acquires one connection/transaction and
threads it through explicitly (see ADR-015 "Consequences").
"""
from __future__ import annotations

from collections.abc import AsyncIterator

import asyncpg

_pool: asyncpg.Pool | None = None


async def create_pool(dsn: str) -> asyncpg.Pool:
    global _pool
    # §13.3: unix socket DSN, small pool — a single store's traffic doesn't
    # need PgBouncer-scale connection counts.
    _pool = await asyncpg.create_pool(dsn=dsn, min_size=2, max_size=10, command_timeout=30)
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Connection pool not initialized — call create_pool() first")
    return _pool


async def get_conn() -> AsyncIterator[asyncpg.Connection]:
    """FastAPI dependency: one connection per request, for read-only or
    single-statement endpoints. Endpoints that need multi-statement
    atomicity acquire their own connection + transaction explicitly in the
    Service layer instead of using this dependency."""
    pool = get_pool()
    async with pool.acquire() as connection:
        yield connection
