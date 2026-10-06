"""Minimal data-setup helpers shared by the Phase 03 integration tests —
not a generic fixture framework, just the handful of rows every test needs
(a user, a brand, a product with one variant)."""
from __future__ import annotations

import secrets

import asyncpg


async def make_user(conn: asyncpg.Connection, *, telegram_id: int | None = None, role: str = "USER") -> int:
    # Random by default (not a fixed literal) so tests remain independent
    # of truncation ordering/whether `clean_slate` ran — `users` is
    # deliberately left un-truncated between tests since it holds the
    # ADR-11 OWNER seed row other suites depend on (see conftest.py).
    if telegram_id is None:
        telegram_id = secrets.randbelow(900_000_000) + 100_000_000
    row = await conn.fetchrow(
        "INSERT INTO users (telegram_id, role, status) VALUES ($1, $2, 'ACTIVE') RETURNING id",
        telegram_id,
        role,
    )
    return row["id"]


async def make_brand(conn: asyncpg.Connection, *, name: str) -> int:
    row = await conn.fetchrow("INSERT INTO brands (name) VALUES ($1) RETURNING id", name)
    return row["id"]


async def make_product(conn: asyncpg.Connection, *, brand_id: int, name: str, status: str = "ACTIVE") -> int:
    row = await conn.fetchrow(
        "INSERT INTO products (name, brand_id, status) VALUES ($1, $2, $3) RETURNING id",
        name,
        brand_id,
        status,
    )
    return row["id"]


async def make_variant(
    conn: asyncpg.Connection,
    *,
    product_id: int,
    sku: str,
    price: int,
    stock_on_hand: int,
    stock_reserved: int = 0,
    status: str = "ACTIVE",
) -> int:
    row = await conn.fetchrow(
        """
        INSERT INTO product_variants (product_id, sku, price, stock_on_hand, stock_reserved, status)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING id
        """,
        product_id,
        sku,
        price,
        stock_on_hand,
        stock_reserved,
        status,
    )
    return row["id"]
