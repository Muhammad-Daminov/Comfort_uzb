"""§23: 'Never trust AI-generated IDs.' A provider can only extract a
free-text reference ("Malibu 2") — resolving that to a real numeric
variant_id/product_id/brand_id is a backend-owned, deterministic DB lookup,
never something the AI is allowed to assert directly. Ambiguous or missing
matches are reported back to the admin instead of guessed.
"""
from __future__ import annotations

import asyncpg


class ProductNotFound(Exception):
    pass


class AmbiguousReference(Exception):
    def __init__(self, matches: list[dict]) -> None:
        self.matches = matches
        super().__init__(f"{len(matches)} matches — ambiguous reference")


async def resolve_variant_by_name(conn: asyncpg.Connection, *, query: str) -> dict:
    rows = await conn.fetch(
        """
        SELECT v.id AS variant_id, v.product_id, p.name AS product_name, v.sku, v.price,
               v.stock_on_hand - v.stock_reserved AS available
        FROM product_variants v
        JOIN products p ON p.id = v.product_id
        WHERE p.deleted_at IS NULL AND v.deleted_at IS NULL AND p.name ILIKE $1
        ORDER BY p.name LIMIT 5
        """,
        f"%{query.strip()}%",
    )
    if not rows:
        raise ProductNotFound(f"no product matches {query!r}")
    if len(rows) > 1:
        raise AmbiguousReference([dict(r) for r in rows])
    return dict(rows[0])


async def resolve_product_by_name(conn: asyncpg.Connection, *, query: str) -> dict:
    rows = await conn.fetch(
        "SELECT id AS product_id, name FROM products WHERE deleted_at IS NULL AND name ILIKE $1 ORDER BY name LIMIT 5",
        f"%{query.strip()}%",
    )
    if not rows:
        raise ProductNotFound(f"no product matches {query!r}")
    if len(rows) > 1:
        raise AmbiguousReference([dict(r) for r in rows])
    return dict(rows[0])


async def resolve_brand_by_name(conn: asyncpg.Connection, *, query: str) -> dict:
    rows = await conn.fetch(
        "SELECT id AS brand_id, name FROM brands WHERE deleted_at IS NULL AND name ILIKE $1 ORDER BY name LIMIT 5",
        f"%{query.strip()}%",
    )
    if not rows:
        raise ProductNotFound(f"no brand matches {query!r}")
    if len(rows) > 1:
        raise AmbiguousReference([dict(r) for r in rows])
    return dict(rows[0])


async def resolve_color_by_name(conn: asyncpg.Connection, *, query: str) -> dict:
    rows = await conn.fetch(
        "SELECT id AS color_id, name FROM colors WHERE deleted_at IS NULL AND name ILIKE $1 ORDER BY name LIMIT 5",
        f"%{query.strip()}%",
    )
    if not rows:
        raise ProductNotFound(f"no color matches {query!r}")
    if len(rows) > 1:
        raise AmbiguousReference([dict(r) for r in rows])
    return dict(rows[0])


VARIANT_SCOPED_COMMANDS = {"INCREASE_STOCK", "DECREASE_STOCK", "UPDATE_PRICE", "GET_STOCK", "GET_COST_PRICE"}
PRODUCT_SCOPED_COMMANDS = {"ARCHIVE_PRODUCT", "UPDATE_PRODUCT"}
BRAND_RESOLVING_COMMANDS = {"CREATE_PRODUCT", "UPDATE_PRODUCT"}


async def resolve_command_references(conn: asyncpg.Connection, command_type: str, payload: dict) -> dict:
    """Shared by both the HTTP AI router and the bot's text/voice/image
    handlers: turns a provider's free-text `product_query`/`brand_query`
    into the real, DB-verified id the strict command schema requires.
    Raises ProductNotFound/AmbiguousReference — callers must surface those
    to the admin, never guess a match."""
    resolved = dict(payload)
    product_query = resolved.pop("product_query", None)
    brand_query = resolved.pop("brand_query", None)
    color_query = resolved.pop("color_query", None)

    if product_query:
        if command_type in VARIANT_SCOPED_COMMANDS:
            match = await resolve_variant_by_name(conn, query=product_query)
            resolved["variant_id"] = match["variant_id"]
        elif command_type in PRODUCT_SCOPED_COMMANDS:
            match = await resolve_product_by_name(conn, query=product_query)
            resolved["product_id"] = match["product_id"]
    if brand_query and command_type in BRAND_RESOLVING_COMMANDS:
        match = await resolve_brand_by_name(conn, query=brand_query)
        resolved["brand_id"] = match["brand_id"]
    if color_query and command_type == "UPDATE_PRODUCT":
        match = await resolve_color_by_name(conn, query=color_query)
        resolved["color_id"] = match["color_id"]

    return resolved
