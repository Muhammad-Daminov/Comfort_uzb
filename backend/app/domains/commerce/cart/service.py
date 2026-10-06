from __future__ import annotations

import asyncpg

from app.domains.commerce.cart import repository
from app.domains.pricing.service import current_price_for_variant


async def get_cart(conn: asyncpg.Connection, *, user_id: int) -> list[dict]:
    """Items with §7.2's *current* price resolved per line. `price` stays the
    variant's base price; `current_price`/`discount_amount` are what the
    detail screen shows and what checkout will actually charge — the Mini
    App sends `current_price` back as `client_unit_price`. Sending the base
    price (all the cart used to expose) made every discounted item fail
    checkout with 409 PRICE_MISMATCH."""
    cart_id = await repository.get_or_create_cart(conn, user_id=user_id)
    rows = await repository.list_items(conn, cart_id=cart_id)
    items = []
    for row in rows:
        resolved = await current_price_for_variant(
            conn,
            variant_id=row["variant_id"],
            product_id=row["product_id"],
            brand_id=row["brand_id"],
            base_price=row["price"],
        )
        items.append({**dict(row), "current_price": resolved.unit_price, "discount_amount": resolved.discount_amount})
    return items


async def add_item(conn: asyncpg.Connection, *, user_id: int, variant_id: int, quantity: int) -> asyncpg.Record:
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    cart_id = await repository.get_or_create_cart(conn, user_id=user_id)
    return await repository.upsert_item(conn, cart_id=cart_id, variant_id=variant_id, quantity=quantity)


async def update_item(
    conn: asyncpg.Connection, *, user_id: int, cart_item_id: int, quantity: int
) -> asyncpg.Record | None:
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    cart_id = await repository.get_or_create_cart(conn, user_id=user_id)
    return await repository.update_item_quantity(conn, cart_item_id=cart_item_id, cart_id=cart_id, quantity=quantity)


async def remove_item(conn: asyncpg.Connection, *, user_id: int, cart_item_id: int) -> str | None:
    cart_id = await repository.get_or_create_cart(conn, user_id=user_id)
    return await repository.delete_item(conn, cart_item_id=cart_item_id, cart_id=cart_id)
