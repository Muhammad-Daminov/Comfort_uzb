"""Phase 08: cart-item removal — the fixed `comfort_app` DELETE-privilege
bug (`app/domains/commerce/cart/repository.py`, migration
`0016_cart_items_soft_delete`). Exercised as the real `comfort_app` role
(the `conn` fixture), which is exactly what a real DELETE would have
failed against — this is the regression test for the actual bug, not a
simulation of it.
"""
from __future__ import annotations

import pytest

from app.domains.commerce.cart import service as cart_service
from tests.integration import factories

pytestmark = pytest.mark.asyncio


async def _setup_cart_item(conn):
    user_id = await factories.make_user(conn)
    brand_id = await factories.make_brand(conn, name="CartDeleteBrand")
    product_id = await factories.make_product(conn, brand_id=brand_id, name="Cart Delete Product")
    variant_id = await factories.make_variant(conn, product_id=product_id, sku="CARTDEL-SKU-1", price=10_000, stock_on_hand=10)
    item = await cart_service.add_item(conn, user_id=user_id, variant_id=variant_id, quantity=2)
    return user_id, variant_id, item["id"]


async def test_removing_a_cart_item_succeeds_as_comfort_app(conn, clean_slate):
    """The actual bug: this used to raise InsufficientPrivilegeError
    ("permission denied for table cart_items") against comfort_app."""
    user_id, variant_id, item_id = await _setup_cart_item(conn)

    deleted_id = await cart_service.remove_item(conn, user_id=user_id, cart_item_id=item_id)

    assert deleted_id == item_id


async def test_removed_item_is_excluded_from_cart_listing(conn, clean_slate):
    user_id, variant_id, item_id = await _setup_cart_item(conn)

    await cart_service.remove_item(conn, user_id=user_id, cart_item_id=item_id)
    items = await cart_service.get_cart(conn, user_id=user_id)

    assert all(i["id"] != item_id for i in items)


async def test_removed_item_row_still_exists_soft_deleted(conn, clean_slate):
    user_id, variant_id, item_id = await _setup_cart_item(conn)

    await cart_service.remove_item(conn, user_id=user_id, cart_item_id=item_id)

    row = await conn.fetchrow("SELECT id, deleted_at FROM cart_items WHERE id = $1", item_id)
    assert row is not None  # row still exists...
    assert row["deleted_at"] is not None  # ...but marked removed, not a real DELETE


async def test_unrelated_cart_items_are_unaffected_by_removal(conn, clean_slate):
    user_id, variant_id, item_id = await _setup_cart_item(conn)
    brand_id = await factories.make_brand(conn, name="CartDeleteBrand2")
    product_id = await factories.make_product(conn, brand_id=brand_id, name="Cart Delete Product 2")
    other_variant_id = await factories.make_variant(conn, product_id=product_id, sku="CARTDEL-SKU-2", price=5_000, stock_on_hand=5)
    other_item = await cart_service.add_item(conn, user_id=user_id, variant_id=other_variant_id, quantity=1)

    await cart_service.remove_item(conn, user_id=user_id, cart_item_id=item_id)
    items = await cart_service.get_cart(conn, user_id=user_id)

    assert any(i["id"] == other_item["id"] for i in items)


async def test_removing_a_nonexistent_item_is_a_safe_noop(conn, clean_slate):
    user_id = await factories.make_user(conn)
    deleted_id = await cart_service.remove_item(conn, user_id=user_id, cart_item_id=999999999)
    assert deleted_id is None


async def test_removing_another_users_item_is_a_safe_noop_not_idor(conn, clean_slate):
    _, _, item_id = await _setup_cart_item(conn)
    other_user_id = await factories.make_user(conn)

    deleted_id = await cart_service.remove_item(conn, user_id=other_user_id, cart_item_id=item_id)

    assert deleted_id is None  # not found from this user's perspective — not deleted, not leaked
    row = await conn.fetchrow("SELECT deleted_at FROM cart_items WHERE id = $1", item_id)
    assert row["deleted_at"] is None  # the original owner's item is untouched


async def test_repeated_removal_is_idempotent(conn, clean_slate):
    user_id, variant_id, item_id = await _setup_cart_item(conn)

    first = await cart_service.remove_item(conn, user_id=user_id, cart_item_id=item_id)
    second = await cart_service.remove_item(conn, user_id=user_id, cart_item_id=item_id)

    assert first == item_id
    assert second is None  # guarded — the second call is a no-op, not an error


async def test_variant_can_be_re_added_after_removal(conn, clean_slate):
    """Exercises the partial-unique-index ON CONFLICT target added by
    migration 0016 — re-adding the same (cart_id, variant_id) after a
    soft-deleted row for it already exists must not collide."""
    user_id, variant_id, item_id = await _setup_cart_item(conn)
    await cart_service.remove_item(conn, user_id=user_id, cart_item_id=item_id)

    new_item = await cart_service.add_item(conn, user_id=user_id, variant_id=variant_id, quantity=1)

    assert new_item["id"] != item_id
    items = await cart_service.get_cart(conn, user_id=user_id)
    assert any(i["id"] == new_item["id"] for i in items)


async def test_clear_cart_soft_deletes_all_items(conn, clean_slate):
    from app.domains.commerce.cart import repository as cart_repository

    user_id, variant_id, item_id = await _setup_cart_item(conn)
    cart_id = await cart_repository.get_or_create_cart(conn, user_id=user_id)

    await cart_repository.clear_cart(conn, cart_id=cart_id)

    items = await cart_service.get_cart(conn, user_id=user_id)
    assert items == []
    row = await conn.fetchrow("SELECT deleted_at FROM cart_items WHERE id = $1", item_id)
    assert row["deleted_at"] is not None
