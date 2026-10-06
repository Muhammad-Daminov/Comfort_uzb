"""Admin catalog management (Phase 06) — product/variant/image/brand/color/
vehicle-compatibility CRUD. Everything here was explicitly deferred from
Phase 03 to this phase (see `docs/tasks/Phase-06-Admin.md`). Permission
enforcement is the existing `require_permission` dependency
(`app/security/permissions.py`, unchanged) — every mutation reuses the §3
matrix keys already seeded in migration 0001_identity, no new permission.
"""
from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel

from app.config import Settings
from app.db.pool import get_conn
from app.domains.catalog import repository, service
from app.security.permissions import CurrentUser, require_permission
from app.security.uploads import InvalidUpload, read_upload_limited, validate_and_process_image

router = APIRouter(prefix="/admin", tags=["admin-catalog"])


# --- Products ---------------------------------------------------------------


class CreateProductRequest(BaseModel):
    name: str
    description: str | None = None
    brand_id: int
    product_type: str | None = None


class UpdateProductRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    brand_id: int | None = None
    product_type: str | None = None


class SetStatusRequest(BaseModel):
    status: str


@router.post("/products")
async def admin_create_product(
    body: CreateProductRequest,
    current_user: CurrentUser = Depends(require_permission("products.create")),
    conn: asyncpg.Connection = Depends(get_conn),
) -> dict:
    try:
        product = await service.admin_create_product(
            conn, name=body.name, description=body.description, brand_id=body.brand_id,
            actor_id=current_user.id, actor_role=current_user.role, product_type=body.product_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except asyncpg.exceptions.PostgresError as exc:
        # Same guard the variant routes below already carry: a bad
        # `brand_id` is a foreign-key violation, i.e. bad client input —
        # 422, not an unhandled 500. Never leak the raw DB error.
        raise HTTPException(status_code=422, detail="invalid product data") from exc
    return dict(product)


@router.patch("/products/{product_id}")
async def admin_update_product(
    product_id: int,
    body: UpdateProductRequest,
    current_user: CurrentUser = Depends(require_permission("products.update")),
    conn: asyncpg.Connection = Depends(get_conn),
) -> dict:
    try:
        product = await service.admin_update_product(
            conn, product_id=product_id, name=body.name, description=body.description, brand_id=body.brand_id,
            actor_id=current_user.id, actor_role=current_user.role, product_type=body.product_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except asyncpg.exceptions.PostgresError as exc:
        raise HTTPException(status_code=422, detail="invalid product data") from exc
    return dict(product)


@router.post("/products/{product_id}/status")
async def admin_set_product_status(
    product_id: int,
    body: SetStatusRequest,
    current_user: CurrentUser = Depends(require_permission("products.archive")),
    conn: asyncpg.Connection = Depends(get_conn),
) -> dict:
    try:
        product = await service.admin_set_product_status(
            conn, product_id=product_id, status=body.status, actor_id=current_user.id, actor_role=current_user.role,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return dict(product)


# --- Variants ----------------------------------------------------------------


class CreateVariantRequest(BaseModel):
    product_id: int
    sku: str
    color_id: int | None = None
    price: int
    required_initial_payment: int = 0
    material: str | None = None


class UpdateVariantRequest(BaseModel):
    sku: str | None = None
    color_id: int | None = None
    price: int | None = None
    required_initial_payment: int | None = None
    material: str | None = None


@router.post("/variants")
async def admin_create_variant(
    body: CreateVariantRequest,
    current_user: CurrentUser = Depends(require_permission("products.create")),
    conn: asyncpg.Connection = Depends(get_conn),
) -> dict:
    try:
        variant = await service.admin_create_variant(
            conn, product_id=body.product_id, sku=body.sku, color_id=body.color_id, price=body.price,
            required_initial_payment=body.required_initial_payment, material=body.material,
            actor_id=current_user.id, actor_role=current_user.role,
        )
    except asyncpg.exceptions.PostgresError as exc:
        # CHECK/UNIQUE constraint violations (e.g. duplicate SKU,
        # required_initial_payment > price) — never leak the raw DB error.
        raise HTTPException(status_code=422, detail="invalid variant data") from exc
    return dict(variant)


@router.patch("/variants/{variant_id}")
async def admin_update_variant(
    variant_id: int,
    body: UpdateVariantRequest,
    current_user: CurrentUser = Depends(require_permission("products.update")),
    conn: asyncpg.Connection = Depends(get_conn),
) -> dict:
    try:
        variant = await service.admin_update_variant(
            conn, variant_id=variant_id, sku=body.sku, color_id=body.color_id, price=body.price,
            required_initial_payment=body.required_initial_payment, material=body.material,
            actor_id=current_user.id, actor_role=current_user.role,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except asyncpg.exceptions.PostgresError as exc:
        raise HTTPException(status_code=422, detail="invalid variant data") from exc
    return dict(variant)


class SetCostPriceRequest(BaseModel):
    cost_price: int


@router.get("/variants/{variant_id}/cost-price")
async def admin_get_variant_cost_price(
    variant_id: int,
    current_user: CurrentUser = Depends(require_permission("finance.view")),
    conn: asyncpg.Connection = Depends(get_conn),
) -> dict:
    variant = await repository.get_variant(conn, variant_id=variant_id)
    if variant is None:
        raise HTTPException(status_code=404, detail=f"variant {variant_id} not found")
    return {"id": variant["id"], "cost_price": variant["cost_price"]}


@router.patch("/variants/{variant_id}/cost-price")
async def admin_set_variant_cost_price(
    variant_id: int,
    body: SetCostPriceRequest,
    # §12/§13 of the v2 brief: cost price is financial data. ADMIN "cannot
    # view financial data" (§ROLE) — gated behind the same permission as
    # owner/finance reporting, not products.update, which ADMIN also holds.
    current_user: CurrentUser = Depends(require_permission("finance.view")),
    conn: asyncpg.Connection = Depends(get_conn),
) -> dict:
    if body.cost_price < 0:
        raise HTTPException(status_code=422, detail="cost_price must be >= 0")
    try:
        variant = await service.admin_set_variant_cost_price(
            conn, variant_id=variant_id, cost_price=body.cost_price,
            actor_id=current_user.id, actor_role=current_user.role,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return dict(variant)


@router.post("/variants/{variant_id}/status")
async def admin_set_variant_status(
    variant_id: int,
    body: SetStatusRequest,
    current_user: CurrentUser = Depends(require_permission("products.archive")),
    conn: asyncpg.Connection = Depends(get_conn),
) -> dict:
    try:
        variant = await service.admin_set_variant_status(
            conn, variant_id=variant_id, status=body.status, actor_id=current_user.id, actor_role=current_user.role,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return dict(variant)


# --- Brands / colors -----------------------------------------------------------


class NameRequest(BaseModel):
    name: str


class ColorRequest(BaseModel):
    name: str | None = None
    hex_code: str | None = None


@router.post("/brands")
async def admin_create_brand(
    body: NameRequest,
    current_user: CurrentUser = Depends(require_permission("products.create")),
    conn: asyncpg.Connection = Depends(get_conn),
) -> dict:
    try:
        brand = await service.admin_create_brand(conn, name=body.name, actor_id=current_user.id, actor_role=current_user.role)
    except asyncpg.exceptions.UniqueViolationError as exc:
        # `brands_name_idx`/`colors_name_idx` are UNIQUE WHERE deleted_at IS NULL:
        # re-using an *archived* name is legal and must keep working, but a
        # clash with a live one is a client-side conflict, not a server fault.
        # Only UniqueViolationError is caught — every other PostgresError still
        # reaches the generic 500 handler, because it would be a real fault.
        raise HTTPException(status_code=409, detail="a brand with this name already exists") from exc
    return dict(brand)


@router.patch("/brands/{brand_id}")
async def admin_update_brand(
    brand_id: int,
    body: NameRequest,
    current_user: CurrentUser = Depends(require_permission("products.update")),
    conn: asyncpg.Connection = Depends(get_conn),
) -> dict:
    try:
        brand = await service.admin_update_brand(conn, brand_id=brand_id, name=body.name, actor_id=current_user.id, actor_role=current_user.role)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except asyncpg.exceptions.UniqueViolationError as exc:
        raise HTTPException(status_code=409, detail="a brand with this name already exists") from exc
    return dict(brand)


@router.post("/brands/{brand_id}/archive")
async def admin_archive_brand(
    brand_id: int,
    current_user: CurrentUser = Depends(require_permission("products.archive")),
    conn: asyncpg.Connection = Depends(get_conn),
) -> dict:
    try:
        await service.admin_archive_brand(conn, brand_id=brand_id, actor_id=current_user.id, actor_role=current_user.role)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"archived": True}


@router.post("/colors")
async def admin_create_color(
    body: ColorRequest,
    current_user: CurrentUser = Depends(require_permission("products.create")),
    conn: asyncpg.Connection = Depends(get_conn),
) -> dict:
    if not body.name:
        raise HTTPException(status_code=422, detail="name is required")
    try:
        color = await service.admin_create_color(
            conn, name=body.name, hex_code=body.hex_code, actor_id=current_user.id, actor_role=current_user.role
        )
    except asyncpg.exceptions.UniqueViolationError as exc:
        raise HTTPException(status_code=409, detail="a color with this name already exists") from exc
    return dict(color)


@router.patch("/colors/{color_id}")
async def admin_update_color(
    color_id: int,
    body: ColorRequest,
    current_user: CurrentUser = Depends(require_permission("products.update")),
    conn: asyncpg.Connection = Depends(get_conn),
) -> dict:
    try:
        color = await service.admin_update_color(
            conn, color_id=color_id, name=body.name, hex_code=body.hex_code,
            actor_id=current_user.id, actor_role=current_user.role,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except asyncpg.exceptions.UniqueViolationError as exc:
        raise HTTPException(status_code=409, detail="a color with this name already exists") from exc
    return dict(color)


@router.post("/colors/{color_id}/archive")
async def admin_archive_color(
    color_id: int,
    current_user: CurrentUser = Depends(require_permission("products.archive")),
    conn: asyncpg.Connection = Depends(get_conn),
) -> dict:
    try:
        await service.admin_archive_color(conn, color_id=color_id, actor_id=current_user.id, actor_role=current_user.role)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"archived": True}


# --- Vehicle compatibility -----------------------------------------------------


class CompatibilityRequest(BaseModel):
    generation_id: int
    year_from: int | None = None
    year_to: int | None = None
    note: str | None = None


@router.get("/products/{product_id}/compatibilities")
async def admin_list_compatibilities(
    product_id: int,
    current_user: CurrentUser = Depends(require_permission("catalog.view")),
    conn: asyncpg.Connection = Depends(get_conn),
) -> dict:
    rows = await repository.list_compatibilities(conn, product_id=product_id)
    return {"items": [dict(r) for r in rows]}


@router.post("/products/{product_id}/compatibilities")
async def admin_add_compatibility(
    product_id: int,
    body: CompatibilityRequest,
    current_user: CurrentUser = Depends(require_permission("products.update")),
    conn: asyncpg.Connection = Depends(get_conn),
) -> dict:
    try:
        compatibility = await service.admin_add_compatibility(
            conn, product_id=product_id, generation_id=body.generation_id, year_from=body.year_from,
            year_to=body.year_to, note=body.note, actor_id=current_user.id, actor_role=current_user.role,
        )
    except service.InactiveGeneration as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except asyncpg.exceptions.PostgresError as exc:
        raise HTTPException(status_code=422, detail="invalid compatibility data") from exc
    return dict(compatibility)


@router.delete("/products/{product_id}/compatibilities/{compatibility_id}")
async def admin_remove_compatibility(
    product_id: int,
    compatibility_id: int,
    current_user: CurrentUser = Depends(require_permission("products.update")),
    conn: asyncpg.Connection = Depends(get_conn),
) -> dict:
    try:
        await service.admin_remove_compatibility(
            conn, compatibility_id=compatibility_id, product_id=product_id,
            actor_id=current_user.id, actor_role=current_user.role,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"removed": True}


# --- Images --------------------------------------------------------------------


@router.post("/products/{product_id}/images")
async def admin_add_image(
    product_id: int,
    file: UploadFile,
    current_user: CurrentUser = Depends(require_permission("products.update")),
    conn: asyncpg.Connection = Depends(get_conn),
) -> dict:
    settings = Settings.from_env()
    try:
        file_bytes = await read_upload_limited(file)
        processed = validate_and_process_image(file_bytes, settings.uploads_root, folder="products", entity_id=product_id)
    except InvalidUpload as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        image = await service.admin_add_image(
            conn, product_id=product_id, storage_path=processed.storage_path, width=processed.width,
            height=processed.height, actor_id=current_user.id, actor_role=current_user.role,
        )
    except service.TooManyImages as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except asyncpg.exceptions.PostgresError as exc:
        raise HTTPException(status_code=422, detail="invalid image data") from exc

    return dict(image)


@router.delete("/products/{product_id}/images/{image_id}")
async def admin_remove_image(
    product_id: int,
    image_id: int,
    current_user: CurrentUser = Depends(require_permission("products.update")),
    conn: asyncpg.Connection = Depends(get_conn),
) -> dict:
    try:
        await service.admin_remove_image(
            conn, image_id=image_id, product_id=product_id, actor_id=current_user.id, actor_role=current_user.role,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    # File is left on disk deliberately — no purge worker exists for
    # product images yet (out of Phase 06 scope, same "metadata-first,
    # file-purge-later" pattern ADR-9 already established for receipts).
    return {"removed": True}


class ReorderImagesRequest(BaseModel):
    image_ids: list[int]


@router.patch("/products/{product_id}/images/order")
async def admin_reorder_images(
    product_id: int,
    body: ReorderImagesRequest,
    current_user: CurrentUser = Depends(require_permission("products.update")),
    conn: asyncpg.Connection = Depends(get_conn),
) -> dict:
    try:
        image_ids = await service.admin_reorder_images(
            conn, product_id=product_id, image_ids=body.image_ids,
            actor_id=current_user.id, actor_role=current_user.role,
        )
    except service.InvalidImageOrder as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"image_ids": image_ids}


@router.post("/products/{product_id}/images/{image_id}/primary")
async def admin_set_primary_image(
    product_id: int,
    image_id: int,
    current_user: CurrentUser = Depends(require_permission("products.update")),
    conn: asyncpg.Connection = Depends(get_conn),
) -> dict:
    try:
        await service.admin_set_primary_image(
            conn, image_id=image_id, product_id=product_id, actor_id=current_user.id, actor_role=current_user.role,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"is_primary": True}
