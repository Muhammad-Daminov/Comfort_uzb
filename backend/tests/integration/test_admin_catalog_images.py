"""Phase 06: image management — primary-image uniqueness, including under
genuine concurrent writes (two real connections, not simulated)."""
from __future__ import annotations

import asyncio

import pytest

from secrets import token_hex

from app.domains.catalog import service as catalog_service
from tests.integration import factories

pytestmark = pytest.mark.asyncio


async def _setup_product_with_variant(conn):
    brand_id = await factories.make_brand(conn, name=f"ImageAdminBrand-{token_hex(4)}")
    admin_id = await factories.make_user(conn, role="ADMIN")
    product = await catalog_service.admin_create_product(
        conn, name="Image Admin Product", description=None, brand_id=brand_id, actor_id=admin_id, actor_role="ADMIN"
    )
    return product["id"], admin_id


async def test_first_image_is_automatically_primary(conn, clean_slate):
    product_id, admin_id = await _setup_product_with_variant(conn)

    image = await catalog_service.admin_add_image(
        conn, product_id=product_id, storage_path=f"products/{product_id}/a.webp", width=100, height=100,
        actor_id=admin_id, actor_role="ADMIN",
    )
    assert image["is_primary"] is True


async def test_sixth_image_is_rejected(conn, clean_slate):
    product_id, admin_id = await _setup_product_with_variant(conn)
    for i in range(5):
        await catalog_service.admin_add_image(
            conn, product_id=product_id, storage_path=f"products/{product_id}/{i}.webp", width=100, height=100,
            actor_id=admin_id, actor_role="ADMIN",
        )

    with pytest.raises(catalog_service.TooManyImages):
        await catalog_service.admin_add_image(
            conn, product_id=product_id, storage_path=f"products/{product_id}/six.webp", width=100, height=100,
            actor_id=admin_id, actor_role="ADMIN",
        )


async def test_setting_primary_unsets_the_previous_one(conn, clean_slate):
    product_id, admin_id = await _setup_product_with_variant(conn)
    first = await catalog_service.admin_add_image(
        conn, product_id=product_id, storage_path=f"products/{product_id}/first.webp", width=100, height=100,
        actor_id=admin_id, actor_role="ADMIN",
    )
    second = await catalog_service.admin_add_image(
        conn, product_id=product_id, storage_path=f"products/{product_id}/second.webp", width=100, height=100,
        actor_id=admin_id, actor_role="ADMIN",
    )
    assert first["is_primary"] is True
    assert second["is_primary"] is False

    await catalog_service.admin_set_primary_image(
        conn, image_id=second["id"], product_id=product_id, actor_id=admin_id, actor_role="ADMIN"
    )

    rows = await conn.fetch(
        "SELECT id, is_primary FROM product_images WHERE product_id = $1 AND deleted_at IS NULL", product_id
    )
    primaries = [r for r in rows if r["is_primary"]]
    assert len(primaries) == 1
    assert primaries[0]["id"] == second["id"]


async def test_removed_image_is_soft_deleted_not_hard_deleted(conn, clean_slate):
    product_id, admin_id = await _setup_product_with_variant(conn)
    image = await catalog_service.admin_add_image(
        conn, product_id=product_id, storage_path=f"products/{product_id}/x.webp", width=100, height=100,
        actor_id=admin_id, actor_role="ADMIN",
    )

    await catalog_service.admin_remove_image(
        conn, image_id=image["id"], product_id=product_id, actor_id=admin_id, actor_role="ADMIN"
    )

    row = await conn.fetchrow("SELECT deleted_at FROM product_images WHERE id = $1", image["id"])
    assert row["deleted_at"] is not None
    images = await conn.fetch(
        "SELECT id FROM product_images WHERE product_id = $1 AND deleted_at IS NULL", product_id
    )
    assert len(images) == 0


# --- §P2-3 reorder --------------------------------------------------------


async def _add_three_images(conn, product_id, admin_id):
    images = []
    for i in range(3):
        image = await catalog_service.admin_add_image(
            conn, product_id=product_id, storage_path=f"products/{product_id}/{i}.webp", width=100, height=100,
            actor_id=admin_id, actor_role="ADMIN",
        )
        images.append(image)
    return images


async def test_valid_reorder_persists_new_sort_order(conn, clean_slate):
    product_id, admin_id = await _setup_product_with_variant(conn)
    images = await _add_three_images(conn, product_id, admin_id)
    new_order = [images[2]["id"], images[0]["id"], images[1]["id"]]

    result = await catalog_service.admin_reorder_images(
        conn, product_id=product_id, image_ids=new_order, actor_id=admin_id, actor_role="ADMIN"
    )
    assert result == new_order

    rows = await conn.fetch(
        "SELECT id, sort_order FROM product_images WHERE product_id = $1 AND deleted_at IS NULL ORDER BY sort_order",
        product_id,
    )
    assert [r["id"] for r in rows] == new_order


async def test_duplicate_image_id_rejected(conn, clean_slate):
    product_id, admin_id = await _setup_product_with_variant(conn)
    images = await _add_three_images(conn, product_id, admin_id)

    with pytest.raises(catalog_service.InvalidImageOrder):
        await catalog_service.admin_reorder_images(
            conn, product_id=product_id,
            image_ids=[images[0]["id"], images[0]["id"], images[1]["id"]],
            actor_id=admin_id, actor_role="ADMIN",
        )


async def test_missing_image_id_rejected(conn, clean_slate):
    product_id, admin_id = await _setup_product_with_variant(conn)
    images = await _add_three_images(conn, product_id, admin_id)

    with pytest.raises(catalog_service.InvalidImageOrder):
        await catalog_service.admin_reorder_images(
            conn, product_id=product_id, image_ids=[images[0]["id"], images[1]["id"]],
            actor_id=admin_id, actor_role="ADMIN",
        )


async def test_foreign_product_image_id_rejected(conn, clean_slate):
    product_id, admin_id = await _setup_product_with_variant(conn)
    images = await _add_three_images(conn, product_id, admin_id)

    other_product_id, _ = await _setup_product_with_variant(conn)
    other_image = await catalog_service.admin_add_image(
        conn, product_id=other_product_id, storage_path=f"products/{other_product_id}/x.webp", width=100, height=100,
        actor_id=admin_id, actor_role="ADMIN",
    )

    with pytest.raises(catalog_service.InvalidImageOrder):
        await catalog_service.admin_reorder_images(
            conn, product_id=product_id,
            image_ids=[other_image["id"], images[0]["id"], images[1]["id"]],
            actor_id=admin_id, actor_role="ADMIN",
        )

    # Rejected payload must not partially apply — original sort_order untouched.
    rows = await conn.fetch(
        "SELECT id, sort_order FROM product_images WHERE product_id = $1 AND deleted_at IS NULL ORDER BY sort_order",
        product_id,
    )
    assert [r["id"] for r in rows] == [img["id"] for img in images]


async def test_deleted_image_id_rejected(conn, clean_slate):
    product_id, admin_id = await _setup_product_with_variant(conn)
    images = await _add_three_images(conn, product_id, admin_id)
    await catalog_service.admin_remove_image(
        conn, image_id=images[2]["id"], product_id=product_id, actor_id=admin_id, actor_role="ADMIN"
    )

    with pytest.raises(catalog_service.InvalidImageOrder):
        await catalog_service.admin_reorder_images(
            conn, product_id=product_id,
            image_ids=[images[2]["id"], images[0]["id"], images[1]["id"]],
            actor_id=admin_id, actor_role="ADMIN",
        )


async def test_concurrent_set_primary_leaves_exactly_one_primary(pool, clean_slate):
    async with pool.acquire() as setup_conn:
        product_id, admin_id = await _setup_product_with_variant(setup_conn)
        first = await catalog_service.admin_add_image(
            setup_conn, product_id=product_id, storage_path=f"products/{product_id}/a.webp", width=100, height=100,
            actor_id=admin_id, actor_role="ADMIN",
        )
        second = await catalog_service.admin_add_image(
            setup_conn, product_id=product_id, storage_path=f"products/{product_id}/b.webp", width=100, height=100,
            actor_id=admin_id, actor_role="ADMIN",
        )

    async def set_primary(image_id: int):
        async with pool.acquire() as conn:
            await catalog_service.admin_set_primary_image(
                conn, image_id=image_id, product_id=product_id, actor_id=admin_id, actor_role="ADMIN"
            )

    # Two real, concurrent connections racing to set a *different* image
    # primary on the same product — the existing partial unique index
    # (migration 0003_catalog) is what actually guarantees exactly one
    # survives, not application-level locking.
    await asyncio.gather(set_primary(first["id"]), set_primary(second["id"]))

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, is_primary FROM product_images WHERE product_id = $1 AND deleted_at IS NULL", product_id
        )
    primaries = [r for r in rows if r["is_primary"]]
    assert len(primaries) == 1  # never zero, never two — whichever write committed last wins cleanly
