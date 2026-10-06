"""CATALOG repository (ADR-015: raw asyncpg). Listing is at product level
(one row per product, aggregating its variants) — the TZ names product
detail/variant detail but not which granularity `GET /catalog/products`
itself lists at; product-level with an aggregated min price and total
available stock is the standard, lowest-surprise interpretation and is
documented here as an implementation necessity, not a silent business-rule
guess (contrast with things like OPEN-3/OPEN-6, which are genuine TZ
contradictions requiring escalation — this is an ordinary API-shape choice
within an unambiguous requirement).

Cursor pagination (REQ-PERF-002: never OFFSET on large tables) uses keyset
pagination on `(sort_value, id)`.
"""
from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from datetime import datetime

import asyncpg

_SORT_COLUMNS = {
    # These names are resolved against the outer subquery's exposed column
    # list (the `listing` alias in list_products' final SELECT/ORDER BY/
    # cursor WHERE), which has no table qualifiers — `p.created_at` doesn't
    # exist at that scope (Postgres raises UndefinedTableError: missing
    # FROM-clause entry for table "p"). Found via Phase 08-FINAL's
    # consolidated security suite (the default "newest" sort — used by
    # every unfiltered GET /catalog/products call — had no prior test
    # coverage at all).
    "newest": ("created_at", "DESC"),
    "price_asc": ("min_price", "ASC"),
    "price_desc": ("min_price", "DESC"),
    "popular": ("popularity", "DESC"),
}


@dataclass(frozen=True)
class Cursor:
    sort_value: object
    id: int


class InvalidCursor(ValueError):
    """An opaque cursor the client tampered with or truncated — bad input
    (422), never a server fault."""


def encode_cursor(sort_value: object, id_: int) -> str:
    if isinstance(sort_value, datetime):
        sort_value = sort_value.isoformat()
    payload = json.dumps({"v": sort_value, "id": id_})
    return base64.urlsafe_b64encode(payload.encode()).decode()


def decode_cursor(cursor: str, *, sort_expr: str) -> Cursor:
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
        sort_value = payload["v"]
        id_ = int(payload["id"])
        if sort_expr == "created_at":
            # asyncpg's binary protocol needs a real datetime for a
            # timestamptz comparison — passing the ISO string back raised
            # DataError (same bug the owner audit cursor already fixed).
            sort_value = datetime.fromisoformat(sort_value)
        else:
            sort_value = int(sort_value)
    except (ValueError, TypeError, KeyError, binascii.Error, UnicodeDecodeError) as exc:
        raise InvalidCursor("malformed cursor") from exc
    return Cursor(sort_value=sort_value, id=id_)


async def list_products(
    conn: asyncpg.Connection,
    *,
    car_brand_id: int | None = None,
    car_model_id: int | None = None,
    brand_id: int | None = None,
    color_id: int | None = None,
    price_min: int | None = None,
    price_max: int | None = None,
    in_stock_only: bool = False,
    sort: str = "newest",
    cursor: str | None = None,
    limit: int = 20,
) -> list[asyncpg.Record]:
    if sort not in _SORT_COLUMNS:
        raise ValueError(f"unknown sort: {sort!r}")
    sort_expr, direction = _SORT_COLUMNS[sort]

    conditions = ["p.status = 'ACTIVE'", "p.deleted_at IS NULL"]
    params: list[object] = []

    # Appended before any filter so its placeholder index is fixed. When the
    # caller filtered by a car model, that model is pinned to the front of
    # the fitment summary: someone searching for a Nexia must see "Nexia" on
    # the card, not whichever generation happens to be newest.
    params.append(car_model_id)
    fitment_model_param = f"${len(params)}"

    def add(cond: str, value: object) -> None:
        params.append(value)
        conditions.append(cond.format(n=len(params)))

    if brand_id is not None:
        add("p.brand_id = ${n}", brand_id)
    if car_brand_id is not None:
        add(
            "EXISTS (SELECT 1 FROM product_compatibilities pc "
            "JOIN car_generations cg ON cg.id = pc.generation_id "
            "JOIN car_models cm ON cm.id = cg.car_model_id "
            "WHERE pc.product_id = p.id AND pc.deleted_at IS NULL AND cm.car_brand_id = ${n})",
            car_brand_id,
        )
    if car_model_id is not None:
        add(
            "EXISTS (SELECT 1 FROM product_compatibilities pc "
            "JOIN car_generations cg ON cg.id = pc.generation_id "
            "WHERE pc.product_id = p.id AND pc.deleted_at IS NULL AND cg.car_model_id = ${n})",
            car_model_id,
        )
    if color_id is not None:
        add(
            "EXISTS (SELECT 1 FROM product_variants v "
            "WHERE v.product_id = p.id AND v.deleted_at IS NULL AND v.color_id = ${n})",
            color_id,
        )

    having_conditions = []
    if price_min is not None:
        params.append(price_min)
        having_conditions.append(f"MIN(v.price) >= ${len(params)}")
    if price_max is not None:
        params.append(price_max)
        having_conditions.append(f"MIN(v.price) <= ${len(params)}")
    if in_stock_only:
        having_conditions.append("SUM(GREATEST(v.stock_on_hand - v.stock_reserved, 0)) > 0")

    if cursor is not None:
        decoded = decode_cursor(cursor, sort_expr=sort_expr)
        params.append(decoded.sort_value)
        params.append(decoded.id)
        op = "<" if direction == "DESC" else ">"
        # Applied on the `listing` subquery, whose exposed columns are
        # unqualified — `p.id` is not in scope there (it raised
        # UndefinedTableError on every second page, for every sort).
        cursor_condition = (
            f"({sort_expr}, id) {op} (${len(params) - 1}, ${len(params)})"
        )
    else:
        cursor_condition = None

    params.append(limit)
    limit_param = f"${len(params)}"

    where_sql = " AND ".join(conditions)
    having_sql = f"HAVING {' AND '.join(having_conditions)}" if having_conditions else ""
    cursor_sql = f"WHERE {cursor_condition}" if cursor_condition else ""

    # Per-product display extras (image, fitment) are computed on the OUTER
    # query, after ORDER BY/LIMIT. Inside the aggregate they would run once
    # per *matching* product — 2000 subquery executions to render 20 cards,
    # which measured 72ms of an 80ms query. Out here they run 20 times.
    query = f"""
        SELECT page.*,
            (SELECT pi.storage_path
               FROM product_images pi
              WHERE pi.product_id = page.id AND pi.deleted_at IS NULL
              ORDER BY pi.is_primary DESC, pi.sort_order, pi.id
              LIMIT 1) AS primary_image_path,
            (SELECT string_agg(f.label, ', ' ORDER BY f.rk)
               FROM (
                 SELECT cm.name ||
                        CASE
                          WHEN COALESCE(pc.year_from, cg.year_from) IS NULL THEN ''
                          WHEN COALESCE(pc.year_to, cg.year_to) IS NULL
                            THEN ' ' || COALESCE(pc.year_from, cg.year_from)::text || '+'
                          ELSE ' ' || COALESCE(pc.year_from, cg.year_from)::text
                                   || '–' || COALESCE(pc.year_to, cg.year_to)::text
                        END AS label,
                        row_number() OVER (
                          ORDER BY COALESCE(cm.id = {fitment_model_param}, false) DESC,
                                   COALESCE(pc.year_from, cg.year_from) DESC NULLS LAST,
                                   pc.id
                        ) AS rk
                   FROM product_compatibilities pc
                   JOIN car_generations cg ON cg.id = pc.generation_id AND cg.deleted_at IS NULL
                   JOIN car_models cm ON cm.id = cg.car_model_id AND cm.deleted_at IS NULL
                  WHERE pc.product_id = page.id AND pc.deleted_at IS NULL
               ) f
              WHERE f.rk <= 2) AS fitment_summary,
            (SELECT count(*)
               FROM product_compatibilities pc2
               JOIN car_generations cg2 ON cg2.id = pc2.generation_id AND cg2.deleted_at IS NULL
               JOIN car_models cm2 ON cm2.id = cg2.car_model_id AND cm2.deleted_at IS NULL
              WHERE pc2.product_id = page.id AND pc2.deleted_at IS NULL) AS fitment_total
        FROM (
        SELECT * FROM (
            SELECT
                p.id, p.name, p.brand_id, p.status, p.created_at,
                b.name AS brand_name,
                MIN(v.price) AS min_price,
                SUM(GREATEST(v.stock_on_hand - v.stock_reserved, 0)) AS total_available,
                -- Correlated, not a LEFT JOIN on order_items: a join
                -- multiplied every variant row by its number of order
                -- lines, so SUM(available) came out N× too high for any
                -- product that had ever been ordered (47 shown for 17 in
                -- stock during the audit). Popularity counts units actually
                -- sold (CONFIRMED), not abandoned/cancelled checkouts.
                (SELECT COALESCE(SUM(oi.quantity), 0)
                   FROM order_items oi
                   JOIN orders o ON o.id = oi.order_id AND o.status = 'CONFIRMED'
                   JOIN product_variants v2 ON v2.id = oi.variant_id
                  WHERE v2.product_id = p.id) AS popularity
            FROM products p
            -- Only sellable variants feed the card's price/stock: an
            -- ARCHIVED variant cannot be bought, so its (often lower) price
            -- must not be what the grid advertises.
            JOIN product_variants v ON v.product_id = p.id AND v.deleted_at IS NULL AND v.status = 'ACTIVE'
            -- LEFT, deliberately: archiving a brand must not make every one
            -- of its products disappear from the catalogue without a trace.
            LEFT JOIN brands b ON b.id = p.brand_id AND b.deleted_at IS NULL
            WHERE {where_sql}
            GROUP BY p.id, b.name
            {having_sql}
        ) AS listing
            {cursor_sql}
            ORDER BY {sort_expr} {direction}, id {direction}
            LIMIT {limit_param}
        ) AS page
        ORDER BY {sort_expr} {direction}, page.id {direction}
    """
    return await conn.fetch(query, *params)


async def get_product_detail(conn: asyncpg.Connection, *, product_id: int) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        SELECT p.id, p.name, p.description, p.brand_id, b.name AS brand_name, p.status, p.source,
               p.product_type
        FROM products p
        JOIN brands b ON b.id = p.brand_id
        WHERE p.id = $1 AND p.deleted_at IS NULL
        """,
        product_id,
    )


async def get_variants_for_product(conn: asyncpg.Connection, *, product_id: int) -> list[asyncpg.Record]:
    return await conn.fetch(
        """
        SELECT id, product_id, sku, color_id, material, price, required_initial_payment,
               stock_on_hand, stock_reserved, status
        FROM product_variants
        WHERE product_id = $1 AND deleted_at IS NULL
        ORDER BY id
        """,
        product_id,
    )


async def get_images_for_product(conn: asyncpg.Connection, *, product_id: int) -> list[asyncpg.Record]:
    return await conn.fetch(
        """
        SELECT id, storage_path, sort_order, is_primary, width, height
        FROM product_images
        WHERE product_id = $1 AND deleted_at IS NULL
        ORDER BY sort_order
        """,
        product_id,
    )


async def get_variant(conn: asyncpg.Connection, *, variant_id: int) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        SELECT v.id, v.product_id, v.sku, v.color_id, v.material, v.price, v.cost_price,
               v.required_initial_payment, v.stock_on_hand, v.stock_reserved, v.status,
               p.brand_id, p.name AS product_name, p.status AS product_status
        FROM product_variants v
        JOIN products p ON p.id = v.product_id
        WHERE v.id = $1 AND v.deleted_at IS NULL
        """,
        variant_id,
    )


async def search_products(conn: asyncpg.Connection, *, query: str, limit: int = 20) -> list[asyncpg.Record]:
    # ADR-8: search_text is normalized at write time; the query string is
    # normalized the same way before being matched (normalization function
    # lives in app/domains/catalog/search_normalize.py, shared so write-time
    # and query-time never drift).
    from app.domains.catalog.search_normalize import normalize

    normalized = normalize(query)
    words = normalized.split()
    if not words:
        return []
    # Multi-word queries are matched word by word (every word must appear
    # somewhere in search_text) — a single phrase-level `<%` only matched
    # when the words sat next to each other, so "nexia gilam" (car model +
    # product) found nothing although both terms are in the text. Each
    # word is first mapped through `search_aliases` (both normalized and
    # as typed — migration 0012 seeds Cyrillic aliases the normalizer
    # would transliterate away), so "neksiya gilam" also resolves.
    raw_words = query.strip().lower().split()
    # Same per-card columns as `list_products` (brand, discounted-later
    # min_price, stock, thumbnail): the Mini App renders search hits with
    # the same product card, which showed "NaN so'm"/"out of stock" for
    # every hit while this returned bare id/name rows. A search page is at
    # most `limit` rows, so per-row subqueries are bounded.
    return await conn.fetch(
        """
        WITH q AS (
            SELECT ord,
                   COALESCE((SELECT sa.canonical FROM search_aliases sa
                              WHERE sa.alias = w.norm OR sa.alias = w.raw LIMIT 1), w.norm) AS term
            FROM unnest($1::text[], $3::text[]) WITH ORDINALITY AS w(norm, raw, ord)
        )
        SELECT hit.*,
            (SELECT pi.storage_path FROM product_images pi
              WHERE pi.product_id = hit.id AND pi.deleted_at IS NULL
              ORDER BY pi.is_primary DESC, pi.sort_order, pi.id LIMIT 1) AS primary_image_path,
            (SELECT string_agg(f.label, ', ' ORDER BY f.rk)
               FROM (
                 SELECT cm.name ||
                        CASE
                          WHEN COALESCE(pc.year_from, cg.year_from) IS NULL THEN ''
                          WHEN COALESCE(pc.year_to, cg.year_to) IS NULL
                            THEN ' ' || COALESCE(pc.year_from, cg.year_from)::text || '+'
                          ELSE ' ' || COALESCE(pc.year_from, cg.year_from)::text
                                   || '–' || COALESCE(pc.year_to, cg.year_to)::text
                        END AS label,
                        row_number() OVER (ORDER BY COALESCE(pc.year_from, cg.year_from) DESC NULLS LAST, pc.id) AS rk
                   FROM product_compatibilities pc
                   JOIN car_generations cg ON cg.id = pc.generation_id AND cg.deleted_at IS NULL
                   JOIN car_models cm ON cm.id = cg.car_model_id AND cm.deleted_at IS NULL
                  WHERE pc.product_id = hit.id AND pc.deleted_at IS NULL
               ) f
              WHERE f.rk <= 2) AS fitment_summary,
            (SELECT count(*)
               FROM product_compatibilities pc2
               JOIN car_generations cg2 ON cg2.id = pc2.generation_id AND cg2.deleted_at IS NULL
               JOIN car_models cm2 ON cm2.id = cg2.car_model_id AND cm2.deleted_at IS NULL
              WHERE pc2.product_id = hit.id AND pc2.deleted_at IS NULL) AS fitment_total
        FROM (
            SELECT p.id, p.name, p.brand_id, p.status, p.created_at,
                   b.name AS brand_name,
                   MIN(v.price) AS min_price,
                   SUM(GREATEST(v.stock_on_hand - v.stock_reserved, 0)) AS total_available,
                   -- Word similarity, not whole-string `%`: search_text is
                   -- the product name + brand + every SKU + every fitment
                   -- name, so a one-word query ("poyandoz") scored ~0.2
                   -- against it, under the 0.3 `%` threshold — search
                   -- returned nothing for ordinary single-word queries.
                   (SELECT AVG(word_similarity(q.term, p.search_text)) FROM q) AS rank
            FROM products p
            JOIN product_variants v ON v.product_id = p.id AND v.deleted_at IS NULL AND v.status = 'ACTIVE'
            LEFT JOIN brands b ON b.id = p.brand_id AND b.deleted_at IS NULL
            WHERE p.status = 'ACTIVE' AND p.deleted_at IS NULL
              AND NOT EXISTS (SELECT 1 FROM q WHERE NOT (q.term <% p.search_text))
            GROUP BY p.id, b.name
            ORDER BY rank DESC, p.id
            LIMIT $2
        ) AS hit
        ORDER BY hit.rank DESC, hit.id
        """,
        words,
        limit,
        raw_words[: len(words)] if len(raw_words) == len(words) else words,
    )


async def list_filters(conn: asyncpg.Connection) -> dict[str, list[asyncpg.Record]]:
    brands = await conn.fetch("SELECT id, name FROM brands WHERE deleted_at IS NULL ORDER BY name")
    colors = await conn.fetch("SELECT id, name, hex_code FROM colors WHERE deleted_at IS NULL ORDER BY name")
    car_brands = await conn.fetch("SELECT id, name FROM car_brands WHERE deleted_at IS NULL ORDER BY name")
    return {"brands": brands, "colors": colors, "car_brands": car_brands}


# --- Admin: products/variants (Phase 06) -----------------------------------


async def create_product(
    conn: asyncpg.Connection, *, name: str, description: str | None, brand_id: int, product_type: str | None = None
) -> asyncpg.Record:
    return await conn.fetchrow(
        """
        INSERT INTO products (name, description, brand_id, status, source, product_type)
        VALUES ($1, $2, $3, 'DRAFT', 'OWN', $4)
        RETURNING id, name, description, brand_id, status, source, product_type, created_at, updated_at
        """,
        name,
        description,
        brand_id,
        product_type,
    )


async def update_product(
    conn: asyncpg.Connection,
    *,
    product_id: int,
    name: str | None,
    description: str | None,
    brand_id: int | None,
    product_type: str | None = None,
) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        UPDATE products
        SET name = COALESCE($2, name),
            description = COALESCE($3, description),
            brand_id = COALESCE($4, brand_id),
            product_type = COALESCE($5, product_type),
            updated_at = now()
        WHERE id = $1 AND deleted_at IS NULL
        RETURNING id, name, description, brand_id, status, source, product_type, created_at, updated_at
        """,
        product_id,
        name,
        description,
        brand_id,
        product_type,
    )


async def set_product_status(conn: asyncpg.Connection, *, product_id: int, status: str) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        UPDATE products SET status = $2, updated_at = now()
        WHERE id = $1 AND deleted_at IS NULL
        RETURNING id, status
        """,
        product_id,
        status,
    )


async def create_variant(
    conn: asyncpg.Connection,
    *,
    product_id: int,
    sku: str,
    color_id: int | None,
    price: int,
    required_initial_payment: int,
    material: str | None = None,
) -> asyncpg.Record:
    # stock_on_hand/stock_reserved deliberately not settable here — they
    # default to 0 and only ever change via POST /admin/inventory/adjust
    # or the order-confirm transaction (§9, AGENTS/backend-commerce.md).
    return await conn.fetchrow(
        """
        INSERT INTO product_variants (product_id, sku, color_id, price, required_initial_payment, status, material)
        VALUES ($1, $2, $3, $4, $5, 'ACTIVE', $6)
        RETURNING id, product_id, sku, color_id, material, price, required_initial_payment,
                  stock_on_hand, stock_reserved, status, created_at, updated_at
        """,
        product_id,
        sku,
        color_id,
        price,
        required_initial_payment,
        material,
    )


async def update_variant(
    conn: asyncpg.Connection,
    *,
    variant_id: int,
    sku: str | None,
    color_id: int | None,
    price: int | None,
    required_initial_payment: int | None,
    material: str | None = None,
) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        UPDATE product_variants
        SET sku = COALESCE($2, sku),
            color_id = COALESCE($3, color_id),
            price = COALESCE($4, price),
            required_initial_payment = COALESCE($5, required_initial_payment),
            material = COALESCE($6, material),
            updated_at = now()
        WHERE id = $1 AND deleted_at IS NULL
        RETURNING id, product_id, sku, color_id, material, price, required_initial_payment,
                  stock_on_hand, stock_reserved, status, updated_at
        """,
        variant_id,
        sku,
        color_id,
        price,
        required_initial_payment,
        material,
    )


async def set_variant_status(conn: asyncpg.Connection, *, variant_id: int, status: str) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        UPDATE product_variants SET status = $2, updated_at = now()
        WHERE id = $1 AND deleted_at IS NULL
        RETURNING id, status
        """,
        variant_id,
        status,
    )


async def set_variant_cost_price(
    conn: asyncpg.Connection, *, variant_id: int, cost_price: int
) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        UPDATE product_variants SET cost_price = $2, updated_at = now()
        WHERE id = $1 AND deleted_at IS NULL
        RETURNING id, cost_price
        """,
        variant_id,
        cost_price,
    )


# --- Admin: brands/colors (Phase 06) ----------------------------------------


async def create_brand(conn: asyncpg.Connection, *, name: str) -> asyncpg.Record:
    return await conn.fetchrow("INSERT INTO brands (name) VALUES ($1) RETURNING id, name", name)


async def update_brand(conn: asyncpg.Connection, *, brand_id: int, name: str) -> asyncpg.Record | None:
    return await conn.fetchrow(
        "UPDATE brands SET name = $2 WHERE id = $1 AND deleted_at IS NULL RETURNING id, name",
        brand_id,
        name,
    )


async def archive_brand(conn: asyncpg.Connection, *, brand_id: int) -> asyncpg.Record | None:
    return await conn.fetchrow(
        "UPDATE brands SET deleted_at = now() WHERE id = $1 AND deleted_at IS NULL RETURNING id",
        brand_id,
    )


async def create_color(conn: asyncpg.Connection, *, name: str, hex_code: str | None) -> asyncpg.Record:
    return await conn.fetchrow(
        "INSERT INTO colors (name, hex_code) VALUES ($1, $2) RETURNING id, name, hex_code",
        name,
        hex_code,
    )


async def update_color(
    conn: asyncpg.Connection, *, color_id: int, name: str | None, hex_code: str | None
) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        UPDATE colors SET name = COALESCE($2, name), hex_code = COALESCE($3, hex_code)
        WHERE id = $1 AND deleted_at IS NULL
        RETURNING id, name, hex_code
        """,
        color_id,
        name,
        hex_code,
    )


async def archive_color(conn: asyncpg.Connection, *, color_id: int) -> asyncpg.Record | None:
    return await conn.fetchrow(
        "UPDATE colors SET deleted_at = now() WHERE id = $1 AND deleted_at IS NULL RETURNING id",
        color_id,
    )


# --- Admin: vehicle compatibility (Phase 06) --------------------------------


async def get_active_generation(conn: asyncpg.Connection, *, generation_id: int) -> asyncpg.Record | None:
    """The FK on product_compatibilities.generation_id guarantees the row
    exists, but not that it's still active — soft-deleted reference
    entities must be rejected at the application layer (Phase 02's
    polymorphic-reference lesson, applied here even though this FK is
    real, not polymorphic)."""
    return await conn.fetchrow(
        "SELECT id FROM car_generations WHERE id = $1 AND deleted_at IS NULL", generation_id
    )


async def add_compatibility(
    conn: asyncpg.Connection,
    *,
    product_id: int,
    generation_id: int,
    year_from: int | None,
    year_to: int | None,
    note: str | None,
) -> asyncpg.Record:
    return await conn.fetchrow(
        """
        INSERT INTO product_compatibilities (product_id, generation_id, year_from, year_to, note)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING id, product_id, generation_id, year_from, year_to, note
        """,
        product_id,
        generation_id,
        year_from,
        year_to,
        note,
    )


async def remove_compatibility(conn: asyncpg.Connection, *, compatibility_id: int, product_id: int) -> bool:
    # Soft delete (migration 0014_compatibility_soft_delete) — comfort_app
    # has zero DELETE privilege on any table, blanket, no exceptions
    # (§12.2, backend/db/provision_roles.sql); a real DELETE here fails in
    # production regardless of this table's "just an association row"
    # nature. See that migration's docstring for the live-reproduced proof.
    row = await conn.fetchrow(
        "UPDATE product_compatibilities SET deleted_at = now() "
        "WHERE id = $1 AND product_id = $2 AND deleted_at IS NULL RETURNING id",
        compatibility_id,
        product_id,
    )
    return row is not None


async def list_compatibilities(conn: asyncpg.Connection, *, product_id: int) -> list[asyncpg.Record]:
    return await conn.fetch(
        "SELECT id, product_id, generation_id, year_from, year_to, note "
        "FROM product_compatibilities WHERE product_id = $1 AND deleted_at IS NULL ORDER BY id",
        product_id,
    )


# --- Admin: images (Phase 06) -----------------------------------------------


async def count_images(conn: asyncpg.Connection, *, product_id: int) -> int:
    return await conn.fetchval(
        "SELECT count(*) FROM product_images WHERE product_id = $1 AND deleted_at IS NULL", product_id
    )


async def create_image(
    conn: asyncpg.Connection,
    *,
    product_id: int,
    storage_path: str,
    width: int,
    height: int,
    is_primary: bool,
) -> asyncpg.Record:
    row = await conn.fetchrow("SELECT COALESCE(MAX(sort_order), -1) + 1 AS next_sort FROM product_images WHERE product_id = $1", product_id)
    return await conn.fetchrow(
        """
        INSERT INTO product_images (product_id, storage_path, sort_order, is_primary, width, height)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING id, product_id, storage_path, sort_order, is_primary, width, height
        """,
        product_id,
        storage_path,
        row["next_sort"],
        is_primary,
        width,
        height,
    )


async def soft_delete_image(conn: asyncpg.Connection, *, image_id: int, product_id: int) -> asyncpg.Record | None:
    return await conn.fetchrow(
        "UPDATE product_images SET deleted_at = now() WHERE id = $1 AND product_id = $2 AND deleted_at IS NULL "
        "RETURNING id, storage_path",
        image_id,
        product_id,
    )


async def get_image(conn: asyncpg.Connection, *, image_id: int, product_id: int) -> asyncpg.Record | None:
    return await conn.fetchrow(
        "SELECT id, product_id, storage_path, is_primary FROM product_images "
        "WHERE id = $1 AND product_id = $2 AND deleted_at IS NULL",
        image_id,
        product_id,
    )


async def get_image_ids_for_product(conn: asyncpg.Connection, *, product_id: int) -> list[int]:
    rows = await conn.fetch(
        "SELECT id FROM product_images WHERE product_id = $1 AND deleted_at IS NULL", product_id
    )
    return [row["id"] for row in rows]


async def reorder_images(conn: asyncpg.Connection, *, product_id: int, image_ids: list[int]) -> None:
    """Rewrites `sort_order` to 0..n-1 following `image_ids`'s order. Caller
    (service.admin_reorder_images) has already validated image_ids is exactly
    the product's live image set with no duplicates/foreign ids."""
    await conn.execute("SELECT id FROM products WHERE id = $1 FOR UPDATE", product_id)
    for position, image_id in enumerate(image_ids):
        await conn.execute(
            "UPDATE product_images SET sort_order = $1 WHERE id = $2 AND product_id = $3 AND deleted_at IS NULL",
            position, image_id, product_id,
        )


async def set_primary_image(conn: asyncpg.Connection, *, image_id: int, product_id: int) -> None:
    """Unset the current primary, then set the new one — both inside the
    caller's transaction (the existing partial unique index,
    `product_images(product_id) WHERE is_primary AND deleted_at IS NULL`
    from migration 0003_catalog, is what actually guarantees exactly one
    survives even if this two-step sequence were ever called concurrently
    for the same product; see the Phase-06 concurrency test)."""
    # Serialise per product: two admins doing this at once used to interleave
    # (A unsets+sets, B's unset saw A's old row, B's set then tripped the
    # partial unique index -> UniqueViolation -> 500). The product row lock
    # makes the unset/set pair atomic per product.
    await conn.execute("SELECT id FROM products WHERE id = $1 FOR UPDATE", product_id)
    await conn.execute(
        "UPDATE product_images SET is_primary = false WHERE product_id = $1 AND is_primary AND deleted_at IS NULL",
        product_id,
    )
    await conn.execute(
        "UPDATE product_images SET is_primary = true WHERE id = $1 AND product_id = $2 AND deleted_at IS NULL",
        image_id,
        product_id,
    )


# --- search_text maintenance (ADR-8) ----------------------------------------


async def rebuild_search_text(conn: asyncpg.Connection, *, product_id: int) -> None:
    """§6.5/ADR-8: search_text is written at write time from everything a
    user might search by — product name, brand, variant SKUs, and
    compatible car brand/model/generation names — normalized through the
    same shared function query-time search uses (search_normalize.py),
    so write-time and query-time never drift (ADR-8's own stated risk).
    Called after anything that changes what a product should be findable
    by: product create/update, variant SKU changes, compatibility changes.
    """
    from app.domains.catalog.search_normalize import normalize

    row = await conn.fetchrow(
        """
        SELECT p.name AS product_name, b.name AS brand_name,
               array_remove(array_agg(DISTINCT v.sku), NULL) AS skus,
               array_remove(array_agg(DISTINCT cb.name), NULL) AS car_brands,
               array_remove(array_agg(DISTINCT cm.name), NULL) AS car_models,
               array_remove(array_agg(DISTINCT cg.name), NULL) AS car_generations
        FROM products p
        JOIN brands b ON b.id = p.brand_id
        LEFT JOIN product_variants v ON v.product_id = p.id AND v.deleted_at IS NULL
        LEFT JOIN product_compatibilities pc ON pc.product_id = p.id AND pc.deleted_at IS NULL
        LEFT JOIN car_generations cg ON cg.id = pc.generation_id
        LEFT JOIN car_models cm ON cm.id = cg.car_model_id
        LEFT JOIN car_brands cb ON cb.id = cm.car_brand_id
        WHERE p.id = $1
        GROUP BY p.id, p.name, b.name
        """,
        product_id,
    )
    if row is None:
        return

    parts = [row["product_name"], row["brand_name"], *row["skus"], *row["car_brands"], *row["car_models"], *row["car_generations"]]
    search_text = normalize(" ".join(p for p in parts if p))
    await conn.execute("UPDATE products SET search_text = $2 WHERE id = $1", product_id, search_text)


async def get_active_variants_for_products(
    conn: asyncpg.Connection, *, product_ids: list[int]
) -> list[asyncpg.Record]:
    """Every sellable variant of the listed products, in one round trip.
    `min_price` has to be recomputed after discounts, and a VARIANT-level
    discount can make a dearer variant the cheapest one — so the whole set
    is needed, not just the pre-discount minimum."""
    return await conn.fetch(
        """
        SELECT v.id, v.product_id, v.price, p.brand_id
        FROM product_variants v
        JOIN products p ON p.id = v.product_id
        WHERE v.product_id = ANY($1::bigint[])
          AND v.deleted_at IS NULL
          AND v.status = 'ACTIVE'
        """,
        product_ids,
    )


async def get_car_model_ids_for_products(
    conn: asyncpg.Connection, *, product_ids: list[int]
) -> list[asyncpg.Record]:
    """CAR_MODEL-targeted discounts need each product's compatible models.
    Batched for the whole page — the per-product equivalent lives in
    `pricing/repository.py` and is what the detail endpoint uses."""
    return await conn.fetch(
        """
        SELECT DISTINCT pc.product_id, cg.car_model_id
        FROM product_compatibilities pc
        JOIN car_generations cg ON cg.id = pc.generation_id
        WHERE pc.product_id = ANY($1::bigint[])
          AND pc.deleted_at IS NULL
        """,
        product_ids,
    )
