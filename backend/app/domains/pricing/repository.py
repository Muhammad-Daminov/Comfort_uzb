"""Repository for PRICING reads (ADR-015: raw asyncpg, parametrized SQL
only). `discount_targets.target_id` is a polymorphic reference with no FK
(see migration 0005_pricing's design notes) — resolving it to the right
table is exactly this application-layer responsibility.
"""
from __future__ import annotations

import asyncpg

from app.domains.pricing.resolver import DiscountCandidate


async def get_applicable_discounts(
    conn: asyncpg.Connection,
    *,
    variant_id: int,
    product_id: int,
    brand_id: int,
    car_model_ids: list[int],
) -> list[DiscountCandidate]:
    rows = await conn.fetch(
        """
        SELECT d.id, d.kind, d.value, d.priority, dt.target_type
        FROM discounts d
        JOIN discount_targets dt ON dt.discount_id = d.id
        WHERE d.is_active
          AND dt.deleted_at IS NULL
          AND (d.starts_at IS NULL OR d.starts_at <= now())
          AND (d.ends_at IS NULL OR d.ends_at >= now())
          AND (
                dt.target_type = 'ALL'
                OR (dt.target_type = 'VARIANT' AND dt.target_id = $1)
                OR (dt.target_type = 'PRODUCT' AND dt.target_id = $2)
                OR (dt.target_type = 'BRAND' AND dt.target_id = $3)
                OR (dt.target_type = 'CAR_MODEL' AND dt.target_id = ANY($4::bigint[]))
              )
        """,
        variant_id,
        product_id,
        brand_id,
        car_model_ids,
    )
    return [
        DiscountCandidate(
            id=row["id"], kind=row["kind"], value=row["value"], priority=row["priority"],
            target_type=row["target_type"],
        )
        for row in rows
    ]


async def get_compatible_car_model_ids(conn: asyncpg.Connection, *, product_id: int) -> list[int]:
    rows = await conn.fetch(
        """
        SELECT DISTINCT cg.car_model_id
        FROM product_compatibilities pc
        JOIN car_generations cg ON cg.id = pc.generation_id
        WHERE pc.product_id = $1 AND pc.deleted_at IS NULL
        """,
        product_id,
    )
    return [row["car_model_id"] for row in rows]


# --- Admin (owner-only): discount CRUD (§P2-4) ------------------------------
# discounts/discount_targets model is unchanged from migration 0005 — no new
# semantics invented here, only CRUD over the existing columns.


async def list_discounts(conn: asyncpg.Connection) -> list[asyncpg.Record]:
    return await conn.fetch("SELECT * FROM discounts ORDER BY created_at DESC")


async def get_discount(conn: asyncpg.Connection, *, discount_id: int) -> asyncpg.Record | None:
    return await conn.fetchrow("SELECT * FROM discounts WHERE id = $1", discount_id)


async def list_targets_for_discounts(conn: asyncpg.Connection, *, discount_ids: list[int]) -> list[asyncpg.Record]:
    return await conn.fetch(
        "SELECT id, discount_id, target_type, target_id FROM discount_targets "
        "WHERE discount_id = ANY($1::bigint[]) AND deleted_at IS NULL",
        discount_ids,
    )


async def create_discount(
    conn: asyncpg.Connection,
    *,
    name: str,
    kind: str,
    value: int,
    starts_at,
    ends_at,
    priority: int,
) -> asyncpg.Record:
    return await conn.fetchrow(
        """
        INSERT INTO discounts (name, kind, value, starts_at, ends_at, priority)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING *
        """,
        name, kind, value, starts_at, ends_at, priority,
    )


async def update_discount(
    conn: asyncpg.Connection,
    *,
    discount_id: int,
    name: str | None,
    kind: str | None,
    value: int | None,
    starts_at,
    ends_at,
    priority: int | None,
    set_starts_at: bool,
    set_ends_at: bool,
) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        UPDATE discounts SET
            name       = COALESCE($2, name),
            kind       = COALESCE($3, kind),
            value      = COALESCE($4, value),
            starts_at  = CASE WHEN $5 THEN $6 ELSE starts_at END,
            ends_at    = CASE WHEN $7 THEN $8 ELSE ends_at END,
            priority   = COALESCE($9, priority),
            updated_at = now()
        WHERE id = $1
        RETURNING *
        """,
        discount_id, name, kind, value, set_starts_at, starts_at, set_ends_at, ends_at, priority,
    )


async def set_discount_active(conn: asyncpg.Connection, *, discount_id: int, is_active: bool) -> asyncpg.Record | None:
    return await conn.fetchrow(
        "UPDATE discounts SET is_active = $2, updated_at = now() WHERE id = $1 RETURNING *",
        discount_id, is_active,
    )


async def add_discount_target(
    conn: asyncpg.Connection, *, discount_id: int, target_type: str, target_id: int | None
) -> asyncpg.Record:
    return await conn.fetchrow(
        """
        INSERT INTO discount_targets (discount_id, target_type, target_id)
        VALUES ($1, $2, $3)
        RETURNING id, discount_id, target_type, target_id
        """,
        discount_id, target_type, target_id,
    )


async def remove_discount_target(conn: asyncpg.Connection, *, discount_id: int, row_id: int) -> bool:
    # Soft delete (migration 0021_discount_targets_soft_delete) — comfort_app
    # has zero DELETE privilege on any table, blanket, no exceptions (§12.2,
    # backend/db/provision_roles.sql), same rule catalog/repository.py's
    # remove_compatibility already documents.
    row = await conn.fetchrow(
        "UPDATE discount_targets SET deleted_at = now() "
        "WHERE id = $1 AND discount_id = $2 AND deleted_at IS NULL RETURNING id",
        row_id, discount_id,
    )
    return row is not None


async def get_applicable_discounts_bulk(
    conn: asyncpg.Connection,
    *,
    variant_ids: list[int],
    product_ids: list[int],
    brand_ids: list[int],
    car_model_ids: list[int],
) -> list[asyncpg.Record]:
    """Every discount candidate relevant to a whole catalogue page, in one
    query. The per-item `get_applicable_discounts` above is unchanged and
    still what the detail/checkout paths use; this exists so listing a page
    of 20 products costs one query instead of twenty.

    Returns the raw (target_type, target_id) pairs — matching a candidate to
    the variant it applies to is the caller's job, and §7.2's resolution
    order stays in `resolver.py`, never here."""
    return await conn.fetch(
        """
        SELECT d.id, d.kind, d.value, d.priority, dt.target_type, dt.target_id
        FROM discounts d
        JOIN discount_targets dt ON dt.discount_id = d.id
        WHERE d.is_active
          AND dt.deleted_at IS NULL
          AND (d.starts_at IS NULL OR d.starts_at <= now())
          AND (d.ends_at IS NULL OR d.ends_at >= now())
          AND (
                dt.target_type = 'ALL'
                OR (dt.target_type = 'VARIANT'   AND dt.target_id = ANY($1::bigint[]))
                OR (dt.target_type = 'PRODUCT'   AND dt.target_id = ANY($2::bigint[]))
                OR (dt.target_type = 'BRAND'     AND dt.target_id = ANY($3::bigint[]))
                OR (dt.target_type = 'CAR_MODEL' AND dt.target_id = ANY($4::bigint[]))
              )
        """,
        variant_ids,
        product_ids,
        brand_ids,
        car_model_ids,
    )
