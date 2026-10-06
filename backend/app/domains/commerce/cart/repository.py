"""Cart repository (ADR-015: raw asyncpg). §12.2: `comfort_app` has zero
DELETE privilege on any table, blanket, no exceptions — item removal is a
guarded soft-delete (migration 0016_cart_items_soft_delete), never a real
DELETE (that was a real bug, found and fixed in Phase 08 — see that
migration's docstring for the live-reproduced proof).
"""
from __future__ import annotations

import asyncpg


async def get_or_create_cart(conn: asyncpg.Connection, *, user_id: int) -> int:
    row = await conn.fetchrow(
        """
        INSERT INTO carts (user_id) VALUES ($1)
        ON CONFLICT (user_id) DO UPDATE SET user_id = EXCLUDED.user_id
        RETURNING id
        """,
        user_id,
    )
    return row["id"]


async def list_items(conn: asyncpg.Connection, *, cart_id: int) -> list[asyncpg.Record]:
    return await conn.fetch(
        """
        SELECT ci.id, ci.cart_id, ci.variant_id, ci.quantity,
               v.price, v.sku, v.stock_on_hand, v.stock_reserved, v.status AS variant_status,
               p.id AS product_id, p.name AS product_name, p.brand_id,
               -- Asosiy rasm yo'li. Imzo bu yerda QO'YILMAYDI: ADR-13 bo'yicha
               -- imzo har so'rovda yangilanadi, shuning uchun uni router
               -- chizadi (katalog ro'yxati bilan bir xil tartib). Saralash
               -- product_images ustidagi tartib bilan bir xil bo'lishi shart,
               -- aks holda savatdagi rasm katalogdagidan boshqa chiqadi.
               (SELECT pi.storage_path FROM product_images pi
                 WHERE pi.product_id = p.id AND pi.deleted_at IS NULL
                 ORDER BY pi.is_primary DESC, pi.sort_order, pi.id
                 LIMIT 1) AS primary_image_path
        FROM cart_items ci
        JOIN product_variants v ON v.id = ci.variant_id AND v.deleted_at IS NULL
        JOIN products p ON p.id = v.product_id
        WHERE ci.cart_id = $1 AND ci.deleted_at IS NULL
        ORDER BY ci.id
        """,
        cart_id,
    )


async def upsert_item(conn: asyncpg.Connection, *, cart_id: int, variant_id: int, quantity: int) -> asyncpg.Record:
    # ON CONFLICT's inference target must match the partial unique index's
    # predicate exactly (migration 0016) — this is what lets a variant be
    # re-added after a previous soft-deleted row for the same
    # (cart_id, variant_id) still exists, without colliding with it.
    return await conn.fetchrow(
        """
        INSERT INTO cart_items (cart_id, variant_id, quantity)
        VALUES ($1, $2, $3)
        ON CONFLICT (cart_id, variant_id) WHERE deleted_at IS NULL
            DO UPDATE SET quantity = EXCLUDED.quantity, updated_at = now()
        RETURNING id, cart_id, variant_id, quantity
        """,
        cart_id,
        variant_id,
        quantity,
    )


async def update_item_quantity(
    conn: asyncpg.Connection, *, cart_item_id: int, cart_id: int, quantity: int
) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        UPDATE cart_items SET quantity = $1, updated_at = now()
        WHERE id = $2 AND cart_id = $3 AND deleted_at IS NULL
        RETURNING id, cart_id, variant_id, quantity
        """,
        quantity,
        cart_item_id,
        cart_id,
    )


async def delete_item(conn: asyncpg.Connection, *, cart_item_id: int, cart_id: int) -> str | None:
    """Guarded soft-delete — no-op (returns None) if the item is already
    gone or belongs to a different cart, same "check the effect, never
    re-run a completed side effect" discipline used everywhere else since
    Phase 02's reservation-release pattern. Never a real DELETE (§12.2)."""
    row = await conn.fetchrow(
        "UPDATE cart_items SET deleted_at = now() WHERE id = $1 AND cart_id = $2 AND deleted_at IS NULL RETURNING id",
        cart_item_id,
        cart_id,
    )
    return row["id"] if row else None


async def clear_cart(conn: asyncpg.Connection, *, cart_id: int) -> None:
    await conn.execute(
        "UPDATE cart_items SET deleted_at = now() WHERE cart_id = $1 AND deleted_at IS NULL", cart_id
    )


async def remove_variants_for_user(conn: asyncpg.Connection, *, user_id: int, variant_ids: list[int]) -> int:
    """Checkout succeeded for these variants: drop them from the user's cart
    (soft-delete, §12.2) inside the same transaction as the order, so the
    cart never re-offers a line that is already reserved under an order.
    Only the ordered variants — anything else the user left in the cart
    stays. Returns the number of lines removed."""
    result = await conn.execute(
        """
        UPDATE cart_items ci SET deleted_at = now()
        FROM carts c
        WHERE ci.cart_id = c.id AND c.user_id = $1
          AND ci.variant_id = ANY($2::bigint[]) AND ci.deleted_at IS NULL
        """,
        user_id,
        variant_ids,
    )
    return int(result.split()[-1])
