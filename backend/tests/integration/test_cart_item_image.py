"""Savat qatoridagi mahsulot rasmi.

Savat ilgari faqat matn qaytarardi, shuning uchun Mini App da qatorlarni
rasmdan ajratib bo'lmasdi. Ikki narsa tekshiriladi:
  1. Tanlangan rasm KATALOG bilan bir xil bo'lishi (asosiy → sort_order → id).
  2. ADR-13: javobda xom `storage_path` qolmasligi, faqat imzolangan havola.
"""
from __future__ import annotations

import uuid

import pytest

from app.domains.commerce.cart import service as cart_service
from app.domains.commerce.cart.router import _with_signed_image
from tests.integration import factories

pytestmark = pytest.mark.asyncio


async def _cart_with_product(conn, *, sku: str):
    user_id = await factories.make_user(conn)
    brand_id = await factories.make_brand(conn, name=f"CartImgBrand-{sku}-{uuid.uuid4().hex[:8]}")
    product_id = await factories.make_product(conn, brand_id=brand_id, name="Teri sidena")
    variant_id = await factories.make_variant(
        conn, product_id=product_id, sku=sku, price=10_000, stock_on_hand=10
    )
    await cart_service.add_item(conn, user_id=user_id, variant_id=variant_id, quantity=1)
    return user_id, product_id


async def _add_image(conn, product_id: int, path: str, *, primary: bool, sort_order: int = 0) -> int:
    return await conn.fetchval(
        "INSERT INTO product_images (product_id, storage_path, sort_order, is_primary) "
        "VALUES ($1, $2, $3, $4) RETURNING id",
        product_id, path, sort_order, primary,
    )


async def test_cart_item_carries_the_primary_image_path(conn, clean_slate):
    user_id, product_id = await _cart_with_product(conn, sku="CARTIMG-1")
    await _add_image(conn, product_id, "products/1/main.webp", primary=True)

    items = await cart_service.get_cart(conn, user_id=user_id)

    assert items[0]["primary_image_path"] == "products/1/main.webp"


async def test_primary_image_wins_over_a_lower_sort_order(conn, clean_slate):
    """Katalog ro'yxati bilan bir xil tartib — aks holda bir mahsulot
    savatda boshqa rasm bilan chiqadi."""
    user_id, product_id = await _cart_with_product(conn, sku="CARTIMG-2")
    await _add_image(conn, product_id, "products/2/first.webp", primary=False, sort_order=0)
    await _add_image(conn, product_id, "products/2/main.webp", primary=True, sort_order=9)

    items = await cart_service.get_cart(conn, user_id=user_id)

    assert items[0]["primary_image_path"] == "products/2/main.webp"


async def test_cart_item_without_an_image_reports_none(conn, clean_slate):
    user_id, _ = await _cart_with_product(conn, sku="CARTIMG-3")

    items = await cart_service.get_cart(conn, user_id=user_id)

    assert items[0]["primary_image_path"] is None


async def test_router_signs_the_path_and_drops_the_raw_one():
    signed = _with_signed_image({"id": 1, "primary_image_path": "products/1/main.webp"})

    assert "primary_image_path" not in signed  # ADR-13: xom yo'l uzatilmaydi
    assert signed["primary_image_url"].startswith("/files/products/")
    # secure_link_md5 imzosi: `s` (imzo) + `e` (muddat) — ADR-13.
    assert "s=" in signed["primary_image_url"]
    assert "e=" in signed["primary_image_url"]


async def test_router_reports_no_url_when_there_is_no_image():
    signed = _with_signed_image({"id": 1, "primary_image_path": None})

    assert signed["primary_image_url"] is None


async def test_soft_deleted_image_is_not_used_in_the_cart(conn, clean_slate):
    """Adminda o'chirilgan rasm savatda ham yo'qolishi kerak. Katalog
    ro'yxatida aynan shu filtr yetishmasdi (test_catalog_images.py)."""
    user_id, product_id = await _cart_with_product(conn, sku="CARTIMG-4")
    image_id = await _add_image(conn, product_id, "products/4/gone.webp", primary=True)
    await conn.execute("UPDATE product_images SET deleted_at = now() WHERE id = $1", image_id)

    items = await cart_service.get_cart(conn, user_id=user_id)

    assert items[0]["primary_image_path"] is None
