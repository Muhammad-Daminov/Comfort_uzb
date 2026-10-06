"""Phase 06: vehicle compatibility management — rejects a soft-deleted
`car_generations` row even though the FK itself would happily allow it
(the FK only proves existence, not that the row is still active — the
same lesson the Phase 02 audit taught about polymorphic references,
applied here to a real FK)."""
from __future__ import annotations

import uuid

import pytest

from app.domains.catalog import service as catalog_service
from tests.integration import factories

pytestmark = pytest.mark.asyncio


async def _make_car_generation(conn, *, deleted: bool = False) -> int:
    # car_brands.name has a partial UNIQUE index — car_brands/car_models/
    # car_generations aren't in clean_slate's truncation list (Phase 05's
    # phone-number lesson: only truncate what's safe to reset globally),
    # so every test needs a genuinely unique name, not just a per-connection one.
    car_brand = await conn.fetchrow(
        "INSERT INTO car_brands (name) VALUES ($1) RETURNING id", f"CarBrand-{uuid.uuid4()}"
    )
    car_model = await conn.fetchrow(
        "INSERT INTO car_models (car_brand_id, name) VALUES ($1, 'Model X') RETURNING id", car_brand["id"]
    )
    deleted_at_sql = "now()" if deleted else "NULL"
    generation = await conn.fetchrow(
        f"INSERT INTO car_generations (car_model_id, name, deleted_at) VALUES ($1, 'Gen I', {deleted_at_sql}) RETURNING id",
        car_model["id"],
    )
    return generation["id"]


async def test_compatibility_add_succeeds_for_active_generation(conn, clean_slate):
    brand_id = await factories.make_brand(conn, name="CompatBrandA")
    admin_id = await factories.make_user(conn, role="ADMIN")
    product = await catalog_service.admin_create_product(
        conn, name="Compat Product A", description=None, brand_id=brand_id, actor_id=admin_id, actor_role="ADMIN"
    )
    generation_id = await _make_car_generation(conn, deleted=False)

    compatibility = await catalog_service.admin_add_compatibility(
        conn, product_id=product["id"], generation_id=generation_id, year_from=2010, year_to=2015, note=None,
        actor_id=admin_id, actor_role="ADMIN",
    )
    assert compatibility["generation_id"] == generation_id

    row = await conn.fetchrow("SELECT search_text FROM products WHERE id = $1", product["id"])
    assert "model x" in row["search_text"] or "modelx" in row["search_text"].replace(" ", "")


async def test_compatibility_add_rejects_soft_deleted_generation(conn, clean_slate):
    brand_id = await factories.make_brand(conn, name="CompatBrandB")
    admin_id = await factories.make_user(conn, role="ADMIN")
    product = await catalog_service.admin_create_product(
        conn, name="Compat Product B", description=None, brand_id=brand_id, actor_id=admin_id, actor_role="ADMIN"
    )
    generation_id = await _make_car_generation(conn, deleted=True)

    with pytest.raises(catalog_service.InactiveGeneration):
        await catalog_service.admin_add_compatibility(
            conn, product_id=product["id"], generation_id=generation_id, year_from=None, year_to=None, note=None,
            actor_id=admin_id, actor_role="ADMIN",
        )

    count = await conn.fetchval(
        "SELECT count(*) FROM product_compatibilities WHERE product_id = $1", product["id"]
    )
    assert count == 0  # nothing written on rejection


async def test_compatibility_remove_is_soft_deleted_not_hard_deleted(conn, clean_slate):
    """comfort_app has zero DELETE privilege on any table (§12.2, blanket,
    no exceptions) — removal must be a soft-delete (migration
    0014_compatibility_soft_delete), never a real DELETE, or this fails in
    production with permission denied (live-reproduced while writing this
    test, which is what led to that migration)."""
    brand_id = await factories.make_brand(conn, name="CompatBrandC")
    admin_id = await factories.make_user(conn, role="ADMIN")
    product = await catalog_service.admin_create_product(
        conn, name="Compat Product C", description=None, brand_id=brand_id, actor_id=admin_id, actor_role="ADMIN"
    )
    generation_id = await _make_car_generation(conn, deleted=False)
    compatibility = await catalog_service.admin_add_compatibility(
        conn, product_id=product["id"], generation_id=generation_id, year_from=None, year_to=None, note=None,
        actor_id=admin_id, actor_role="ADMIN",
    )

    await catalog_service.admin_remove_compatibility(
        conn, compatibility_id=compatibility["id"], product_id=product["id"], actor_id=admin_id, actor_role="ADMIN"
    )

    row = await conn.fetchrow("SELECT id, deleted_at FROM product_compatibilities WHERE id = $1", compatibility["id"])
    assert row is not None  # row still exists...
    assert row["deleted_at"] is not None  # ...but marked removed

    active = await catalog_service.repository.list_compatibilities(conn, product_id=product["id"])
    assert len(active) == 0  # and excluded from the active listing
