"""Phase 06: admin product/variant CRUD through the real Service layer,
including updated_at maintenance, search_text population, and audit
participation."""
from __future__ import annotations

import pytest

from app.domains.catalog import service as catalog_service
from tests.integration import factories

pytestmark = pytest.mark.asyncio


async def test_create_product_populates_search_text(conn, clean_slate):
    brand_id = await factories.make_brand(conn, name="AdminBrandA")
    admin_id = await factories.make_user(conn, role="ADMIN")

    product = await catalog_service.admin_create_product(
        conn, name="Tormoz kolodkasi", description=None, brand_id=brand_id, actor_id=admin_id, actor_role="ADMIN"
    )

    row = await conn.fetchrow("SELECT search_text FROM products WHERE id = $1", product["id"])
    assert "tormoz" in row["search_text"]
    assert "adminbranda" in row["search_text"]

    audit_row = await conn.fetchrow(
        "SELECT * FROM audit_logs WHERE entity_type = 'product' AND entity_id = $1 AND action = 'product.create'",
        product["id"],
    )
    assert audit_row is not None


async def test_update_product_bumps_updated_at(conn, clean_slate):
    brand_id = await factories.make_brand(conn, name="AdminBrandB")
    admin_id = await factories.make_user(conn, role="ADMIN")
    product = await catalog_service.admin_create_product(
        conn, name="Original Name", description=None, brand_id=brand_id, actor_id=admin_id, actor_role="ADMIN"
    )
    original_updated_at = product["updated_at"]

    import asyncio

    await asyncio.sleep(0.01)
    updated = await catalog_service.admin_update_product(
        conn, product_id=product["id"], name="New Name", description=None, brand_id=None,
        actor_id=admin_id, actor_role="ADMIN",
    )

    assert updated["name"] == "New Name"
    assert updated["updated_at"] > original_updated_at


async def test_set_product_status_rejects_invalid_status(conn, clean_slate):
    brand_id = await factories.make_brand(conn, name="AdminBrandC")
    admin_id = await factories.make_user(conn, role="ADMIN")
    product = await catalog_service.admin_create_product(
        conn, name="Status Test", description=None, brand_id=brand_id, actor_id=admin_id, actor_role="ADMIN"
    )

    with pytest.raises(ValueError):
        await catalog_service.admin_set_product_status(
            conn, product_id=product["id"], status="DELETED_FOREVER", actor_id=admin_id, actor_role="ADMIN"
        )


async def test_create_variant_never_accepts_stock_fields(conn, clean_slate):
    """Structural guarantee: admin_create_variant's signature has no
    stock_on_hand/stock_reserved parameter at all — stock only ever
    changes via POST /admin/inventory/adjust or order-confirm."""
    import inspect

    signature = inspect.signature(catalog_service.admin_create_variant)
    assert "stock_on_hand" not in signature.parameters
    assert "stock_reserved" not in signature.parameters


async def test_create_variant_rejects_duplicate_sku(conn, clean_slate):
    brand_id = await factories.make_brand(conn, name="AdminBrandD")
    admin_id = await factories.make_user(conn, role="ADMIN")
    product = await catalog_service.admin_create_product(
        conn, name="Dup SKU Test", description=None, brand_id=brand_id, actor_id=admin_id, actor_role="ADMIN"
    )
    await catalog_service.admin_create_variant(
        conn, product_id=product["id"], sku="DUP-SKU-1", color_id=None, price=10_000,
        required_initial_payment=0, actor_id=admin_id, actor_role="ADMIN",
    )

    import asyncpg

    with pytest.raises(asyncpg.exceptions.UniqueViolationError):
        await catalog_service.admin_create_variant(
            conn, product_id=product["id"], sku="DUP-SKU-1", color_id=None, price=20_000,
            required_initial_payment=0, actor_id=admin_id, actor_role="ADMIN",
        )


async def test_create_variant_rejects_initial_payment_exceeding_price(conn, clean_slate):
    brand_id = await factories.make_brand(conn, name="AdminBrandE")
    admin_id = await factories.make_user(conn, role="ADMIN")
    product = await catalog_service.admin_create_product(
        conn, name="Bad Payment Test", description=None, brand_id=brand_id, actor_id=admin_id, actor_role="ADMIN"
    )

    import asyncpg

    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        await catalog_service.admin_create_variant(
            conn, product_id=product["id"], sku="BADPAY-SKU-1", color_id=None, price=10_000,
            required_initial_payment=50_000, actor_id=admin_id, actor_role="ADMIN",
        )
