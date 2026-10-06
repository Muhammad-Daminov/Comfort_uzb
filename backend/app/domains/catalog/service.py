from __future__ import annotations

import asyncpg

from app.domains.catalog import repository
from app.domains.pricing import repository as pricing_repository
from app.domains.pricing.resolver import DiscountCandidate, resolve_price
from app.domains.pricing.service import current_price_for_variant
from app.security.audit import record_audit

PRODUCT_STATUSES = {"DRAFT", "ACTIVE", "ARCHIVED"}
VARIANT_STATUSES = {"ACTIVE", "ARCHIVED"}
# §P1-3: current business scope is exactly seat covers and seat-cover
# slipcovers — a small, business-defined set (DB CHECK backs this too),
# not a generic category system. Material is deliberately NOT an enum
# here (free text, validated only for emptiness) — see migration
# 0019_product_type_material's docstring.
PRODUCT_TYPES = {"SIDENA", "SIDENA_COVER"}
MAX_IMAGES_PER_PRODUCT = 5  # §6.3 — application-enforced, not a DB constraint (migration 0003's own design note)


async def list_products(conn: asyncpg.Connection, **filters) -> list[dict]:
    """Listing rows with discounts applied.

    The SQL returns `min_price` as the *base* minimum. That is not what a
    shopper should see: the detail endpoint runs §7.2's discount resolution,
    so a discounted product used to show one price in the grid and a lower
    one after tapping it. Here the same authoritative `resolve_price` is
    applied to the listing, so both agree.

    §7.2's rule is never re-expressed in SQL (CLAUDE.md: business rules are
    non-negotiable, and `resolver.py` says the price computation must not be
    duplicated between the "show" and "charge" paths). Instead the inputs are
    fetched in bulk — three extra queries for a whole page, regardless of how
    many products it holds, never one per product.

    `base_min_price` is preserved because cursor pagination sorts on the
    SQL's own `min_price`; the cursor must keep encoding that value, not the
    discounted one, or the next page would skip or repeat rows."""
    rows = await repository.list_products(conn, **filters)
    return await _apply_listing_discounts(conn, rows)


async def _apply_listing_discounts(conn: asyncpg.Connection, rows: list[asyncpg.Record]) -> list[dict]:
    """Shared by the listing and search endpoints so both grids show the same
    discounted `min_price`/`old_price` per card (search used to return bare
    id/name rows, which the card component rendered as "NaN so'm")."""
    if not rows:
        return []

    items = [dict(row) for row in rows]
    product_ids = [item["id"] for item in items]

    variants = await repository.get_active_variants_for_products(conn, product_ids=product_ids)
    if not variants:
        for item in items:
            item["base_min_price"] = item["min_price"]
            item["old_price"] = None
        return items

    compat_rows = await repository.get_car_model_ids_for_products(conn, product_ids=product_ids)
    car_models_by_product: dict[int, list[int]] = {}
    for row in compat_rows:
        car_models_by_product.setdefault(row["product_id"], []).append(row["car_model_id"])

    brand_ids = sorted({item["brand_id"] for item in items if item["brand_id"] is not None})
    all_car_model_ids = sorted({model_id for ids in car_models_by_product.values() for model_id in ids})

    discount_rows = await pricing_repository.get_applicable_discounts_bulk(
        conn,
        variant_ids=[v["id"] for v in variants],
        product_ids=product_ids,
        brand_ids=brand_ids,
        car_model_ids=all_car_model_ids,
    )

    # Index the candidates so matching a variant is a dict lookup, not a scan.
    by_target: dict[tuple[str, int | None], list[asyncpg.Record]] = {}
    for row in discount_rows:
        key = (row["target_type"], None if row["target_type"] == "ALL" else row["target_id"])
        by_target.setdefault(key, []).append(row)

    def candidates_for(variant: asyncpg.Record) -> list[DiscountCandidate]:
        matched: list[asyncpg.Record] = list(by_target.get(("ALL", None), []))
        matched += by_target.get(("VARIANT", variant["id"]), [])
        matched += by_target.get(("PRODUCT", variant["product_id"]), [])
        if variant["brand_id"] is not None:
            matched += by_target.get(("BRAND", variant["brand_id"]), [])
        for model_id in car_models_by_product.get(variant["product_id"], []):
            matched += by_target.get(("CAR_MODEL", model_id), [])
        return [
            DiscountCandidate(
                id=row["id"], kind=row["kind"], value=row["value"],
                priority=row["priority"], target_type=row["target_type"],
            )
            for row in matched
        ]

    # Cheapest *after* discount, which is not necessarily the variant that
    # was cheapest before one — a VARIANT-level discount can reorder them.
    best_by_product: dict[int, tuple[int, int]] = {}
    for variant in variants:
        resolved = resolve_price(variant["price"], candidates_for(variant))
        current = best_by_product.get(variant["product_id"])
        if current is None or resolved.unit_price < current[0]:
            best_by_product[variant["product_id"]] = (resolved.unit_price, variant["price"])

    for item in items:
        base = item["min_price"]
        item["base_min_price"] = base
        best = best_by_product.get(item["id"])
        if best is None:
            item["old_price"] = None
            continue
        discounted, base_of_best = best
        item["min_price"] = discounted
        item["old_price"] = base_of_best if discounted < base_of_best else None

    return items


async def get_product_detail(conn: asyncpg.Connection, *, product_id: int) -> dict | None:
    product = await repository.get_product_detail(conn, product_id=product_id)
    if product is None:
        return None
    variants = await repository.get_variants_for_product(conn, product_id=product_id)
    images = await repository.get_images_for_product(conn, product_id=product_id)

    priced_variants = []
    for variant in variants:
        resolved = await current_price_for_variant(
            conn,
            variant_id=variant["id"],
            product_id=product["id"],
            brand_id=product["brand_id"],
            base_price=variant["price"],
        )
        priced_variants.append({**dict(variant), "current_price": resolved.unit_price, "discount_amount": resolved.discount_amount})

    return {"product": dict(product), "variants": priced_variants, "images": [dict(i) for i in images]}


async def search_products(conn: asyncpg.Connection, *, query: str, limit: int = 20) -> list[dict]:
    rows = await repository.search_products(conn, query=query, limit=limit)
    return await _apply_listing_discounts(conn, rows)


async def list_filters(conn: asyncpg.Connection) -> dict:
    return await repository.list_filters(conn)


# --- Admin: products/variants (Phase 06) ------------------------------------
# Permission enforcement happens at the Router layer (existing
# `require_permission` dependency) — every function here assumes the
# caller is already authorized and only handles the transaction/audit/
# search_text orchestration.


async def admin_create_product(
    conn: asyncpg.Connection, *, name: str, description: str | None, brand_id: int, actor_id: int, actor_role: str,
    product_type: str | None = None,
) -> asyncpg.Record:
    if product_type is not None and product_type not in PRODUCT_TYPES:
        raise ValueError(f"invalid product_type: {product_type!r}")
    async with conn.transaction():
        product = await repository.create_product(
            conn, name=name, description=description, brand_id=brand_id, product_type=product_type
        )
        await repository.rebuild_search_text(conn, product_id=product["id"])
        await record_audit(
            conn, actor_id=actor_id, actor_role=actor_role, action="product.create",
            entity_type="product", entity_id=product["id"],
            new_data={"name": name, "brand_id": brand_id, "product_type": product_type},
        )
        return product


async def admin_update_product(
    conn: asyncpg.Connection,
    *,
    product_id: int,
    name: str | None,
    description: str | None,
    brand_id: int | None,
    actor_id: int,
    actor_role: str,
    product_type: str | None = None,
) -> asyncpg.Record:
    if product_type is not None and product_type not in PRODUCT_TYPES:
        raise ValueError(f"invalid product_type: {product_type!r}")
    async with conn.transaction():
        product = await repository.update_product(
            conn, product_id=product_id, name=name, description=description, brand_id=brand_id,
            product_type=product_type,
        )
        if product is None:
            raise LookupError(f"product {product_id} not found")
        await repository.rebuild_search_text(conn, product_id=product_id)
        await record_audit(
            conn, actor_id=actor_id, actor_role=actor_role, action="product.update",
            entity_type="product", entity_id=product_id,
            new_data={"name": name, "description": description, "brand_id": brand_id, "product_type": product_type},
        )
        return product


async def admin_set_product_status(
    conn: asyncpg.Connection, *, product_id: int, status: str, actor_id: int, actor_role: str
) -> asyncpg.Record:
    if status not in PRODUCT_STATUSES:
        raise ValueError(f"invalid product status: {status!r}")
    async with conn.transaction():
        product = await repository.set_product_status(conn, product_id=product_id, status=status)
        if product is None:
            raise LookupError(f"product {product_id} not found")
        await record_audit(
            conn, actor_id=actor_id, actor_role=actor_role, action="product.status_change",
            entity_type="product", entity_id=product_id, new_data={"status": status},
        )
        return product


async def admin_create_variant(
    conn: asyncpg.Connection,
    *,
    product_id: int,
    sku: str,
    color_id: int | None,
    price: int,
    required_initial_payment: int,
    actor_id: int,
    actor_role: str,
    material: str | None = None,
) -> asyncpg.Record:
    async with conn.transaction():
        variant = await repository.create_variant(
            conn, product_id=product_id, sku=sku, color_id=color_id, price=price,
            required_initial_payment=required_initial_payment, material=material,
        )
        await repository.rebuild_search_text(conn, product_id=product_id)
        await record_audit(
            conn, actor_id=actor_id, actor_role=actor_role, action="variant.create",
            entity_type="product_variant", entity_id=variant["id"],
            new_data={"sku": sku, "price": price, "material": material},
        )
        return variant


async def admin_update_variant(
    conn: asyncpg.Connection,
    *,
    variant_id: int,
    sku: str | None,
    color_id: int | None,
    price: int | None,
    required_initial_payment: int | None,
    actor_id: int,
    actor_role: str,
    material: str | None = None,
) -> asyncpg.Record:
    async with conn.transaction():
        variant = await repository.update_variant(
            conn, variant_id=variant_id, sku=sku, color_id=color_id, price=price,
            required_initial_payment=required_initial_payment, material=material,
        )
        if variant is None:
            raise LookupError(f"variant {variant_id} not found")
        if sku is not None:
            await repository.rebuild_search_text(conn, product_id=variant["product_id"])
        await record_audit(
            conn, actor_id=actor_id, actor_role=actor_role, action="variant.update",
            entity_type="product_variant", entity_id=variant_id,
            new_data={"sku": sku, "price": price, "required_initial_payment": required_initial_payment, "material": material},
        )
        return variant


async def admin_set_variant_status(
    conn: asyncpg.Connection, *, variant_id: int, status: str, actor_id: int, actor_role: str
) -> asyncpg.Record:
    if status not in VARIANT_STATUSES:
        raise ValueError(f"invalid variant status: {status!r}")
    async with conn.transaction():
        variant = await repository.set_variant_status(conn, variant_id=variant_id, status=status)
        if variant is None:
            raise LookupError(f"variant {variant_id} not found")
        await record_audit(
            conn, actor_id=actor_id, actor_role=actor_role, action="variant.status_change",
            entity_type="product_variant", entity_id=variant_id, new_data={"status": status},
        )
        return variant


async def admin_set_variant_cost_price(
    conn: asyncpg.Connection, *, variant_id: int, cost_price: int, actor_id: int, actor_role: str
) -> asyncpg.Record:
    async with conn.transaction():
        variant = await repository.set_variant_cost_price(conn, variant_id=variant_id, cost_price=cost_price)
        if variant is None:
            raise LookupError(f"variant {variant_id} not found")
        await record_audit(
            conn, actor_id=actor_id, actor_role=actor_role, action="variant.cost_price_set",
            entity_type="product_variant", entity_id=variant_id, new_data={"cost_price": cost_price},
        )
        return variant


# --- Admin: brands/colors (Phase 06) ----------------------------------------


async def admin_create_brand(conn: asyncpg.Connection, *, name: str, actor_id: int, actor_role: str) -> asyncpg.Record:
    async with conn.transaction():
        brand = await repository.create_brand(conn, name=name)
        await record_audit(
            conn, actor_id=actor_id, actor_role=actor_role, action="brand.create",
            entity_type="brand", entity_id=brand["id"], new_data={"name": name},
        )
        return brand


async def admin_update_brand(
    conn: asyncpg.Connection, *, brand_id: int, name: str, actor_id: int, actor_role: str
) -> asyncpg.Record:
    async with conn.transaction():
        brand = await repository.update_brand(conn, brand_id=brand_id, name=name)
        if brand is None:
            raise LookupError(f"brand {brand_id} not found")
        await record_audit(
            conn, actor_id=actor_id, actor_role=actor_role, action="brand.update",
            entity_type="brand", entity_id=brand_id, new_data={"name": name},
        )
        return brand


async def admin_archive_brand(conn: asyncpg.Connection, *, brand_id: int, actor_id: int, actor_role: str) -> None:
    async with conn.transaction():
        result = await repository.archive_brand(conn, brand_id=brand_id)
        if result is None:
            raise LookupError(f"brand {brand_id} not found")
        await record_audit(
            conn, actor_id=actor_id, actor_role=actor_role, action="brand.archive",
            entity_type="brand", entity_id=brand_id, new_data=None,
        )


async def admin_create_color(
    conn: asyncpg.Connection, *, name: str, hex_code: str | None, actor_id: int, actor_role: str
) -> asyncpg.Record:
    async with conn.transaction():
        color = await repository.create_color(conn, name=name, hex_code=hex_code)
        await record_audit(
            conn, actor_id=actor_id, actor_role=actor_role, action="color.create",
            entity_type="color", entity_id=color["id"], new_data={"name": name, "hex_code": hex_code},
        )
        return color


async def admin_update_color(
    conn: asyncpg.Connection, *, color_id: int, name: str | None, hex_code: str | None, actor_id: int, actor_role: str
) -> asyncpg.Record:
    async with conn.transaction():
        color = await repository.update_color(conn, color_id=color_id, name=name, hex_code=hex_code)
        if color is None:
            raise LookupError(f"color {color_id} not found")
        await record_audit(
            conn, actor_id=actor_id, actor_role=actor_role, action="color.update",
            entity_type="color", entity_id=color_id, new_data={"name": name, "hex_code": hex_code},
        )
        return color


async def admin_archive_color(conn: asyncpg.Connection, *, color_id: int, actor_id: int, actor_role: str) -> None:
    async with conn.transaction():
        result = await repository.archive_color(conn, color_id=color_id)
        if result is None:
            raise LookupError(f"color {color_id} not found")
        await record_audit(
            conn, actor_id=actor_id, actor_role=actor_role, action="color.archive",
            entity_type="color", entity_id=color_id, new_data=None,
        )


# --- Admin: vehicle compatibility (Phase 06) --------------------------------


class InactiveGeneration(Exception):
    pass


async def admin_add_compatibility(
    conn: asyncpg.Connection,
    *,
    product_id: int,
    generation_id: int,
    year_from: int | None,
    year_to: int | None,
    note: str | None,
    actor_id: int,
    actor_role: str,
) -> asyncpg.Record:
    async with conn.transaction():
        generation = await repository.get_active_generation(conn, generation_id=generation_id)
        if generation is None:
            raise InactiveGeneration(f"generation {generation_id} does not exist or is deleted")
        compatibility = await repository.add_compatibility(
            conn, product_id=product_id, generation_id=generation_id, year_from=year_from, year_to=year_to, note=note
        )
        await repository.rebuild_search_text(conn, product_id=product_id)
        await record_audit(
            conn, actor_id=actor_id, actor_role=actor_role, action="compatibility.add",
            entity_type="product_compatibility", entity_id=compatibility["id"],
            new_data={"product_id": product_id, "generation_id": generation_id},
        )
        return compatibility


async def admin_remove_compatibility(
    conn: asyncpg.Connection, *, compatibility_id: int, product_id: int, actor_id: int, actor_role: str
) -> None:
    async with conn.transaction():
        removed = await repository.remove_compatibility(conn, compatibility_id=compatibility_id, product_id=product_id)
        if not removed:
            raise LookupError(f"compatibility {compatibility_id} not found for product {product_id}")
        await repository.rebuild_search_text(conn, product_id=product_id)
        await record_audit(
            conn, actor_id=actor_id, actor_role=actor_role, action="compatibility.remove",
            entity_type="product_compatibility", entity_id=compatibility_id, new_data=None,
        )


# --- Admin: images (Phase 06) -----------------------------------------------


class TooManyImages(Exception):
    pass


async def admin_add_image(
    conn: asyncpg.Connection,
    *,
    product_id: int,
    storage_path: str,
    width: int,
    height: int,
    actor_id: int,
    actor_role: str,
) -> asyncpg.Record:
    async with conn.transaction():
        existing_count = await repository.count_images(conn, product_id=product_id)
        if existing_count >= MAX_IMAGES_PER_PRODUCT:
            raise TooManyImages(f"product {product_id} already has the maximum of {MAX_IMAGES_PER_PRODUCT} images")
        is_primary = existing_count == 0  # first image is automatically primary
        image = await repository.create_image(
            conn, product_id=product_id, storage_path=storage_path, width=width, height=height, is_primary=is_primary
        )
        await record_audit(
            conn, actor_id=actor_id, actor_role=actor_role, action="image.add",
            entity_type="product_image", entity_id=image["id"], new_data={"product_id": product_id},
        )
        return image


async def admin_remove_image(
    conn: asyncpg.Connection, *, image_id: int, product_id: int, actor_id: int, actor_role: str
) -> str:
    """Returns the removed image's storage_path so the Router can decide
    whether to also delete the file from disk."""
    async with conn.transaction():
        removed = await repository.soft_delete_image(conn, image_id=image_id, product_id=product_id)
        if removed is None:
            raise LookupError(f"image {image_id} not found for product {product_id}")
        await record_audit(
            conn, actor_id=actor_id, actor_role=actor_role, action="image.remove",
            entity_type="product_image", entity_id=image_id, new_data=None,
        )
        return removed["storage_path"]


class InvalidImageOrder(Exception):
    pass


async def admin_reorder_images(
    conn: asyncpg.Connection, *, product_id: int, image_ids: list[int], actor_id: int, actor_role: str
) -> list[int]:
    """§P2-3: `image_ids` must name exactly the product's current live image
    set — no duplicates, no missing images, no image belonging to another
    product. Never partially applies a bad payload."""
    async with conn.transaction():
        if len(image_ids) != len(set(image_ids)):
            raise InvalidImageOrder("duplicate image_id in reorder payload")
        existing_ids = set(await repository.get_image_ids_for_product(conn, product_id=product_id))
        if set(image_ids) != existing_ids:
            raise InvalidImageOrder("image_ids must match the product's current image set exactly")
        await repository.reorder_images(conn, product_id=product_id, image_ids=image_ids)
        await record_audit(
            conn, actor_id=actor_id, actor_role=actor_role, action="image.reorder",
            entity_type="product", entity_id=product_id, new_data={"image_ids": image_ids},
        )
        return image_ids


async def admin_set_primary_image(
    conn: asyncpg.Connection, *, image_id: int, product_id: int, actor_id: int, actor_role: str
) -> None:
    async with conn.transaction():
        image = await repository.get_image(conn, image_id=image_id, product_id=product_id)
        if image is None:
            raise LookupError(f"image {image_id} not found for product {product_id}")
        await repository.set_primary_image(conn, image_id=image_id, product_id=product_id)
        await record_audit(
            conn, actor_id=actor_id, actor_role=actor_role, action="image.set_primary",
            entity_type="product_image", entity_id=image_id, new_data={"product_id": product_id},
        )
