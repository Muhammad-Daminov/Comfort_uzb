"""Phase 05 addition: `GET /catalog/products/{id}` signs image URLs
(ADR-13) rather than returning a raw storage path."""
from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.domains.catalog import service as catalog_service
from app.security.signing import signed_url_for_folder
from tests.integration import factories

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def app_client_factory():
    """Real ASGI client against the actual app, so the listing's response
    shape is asserted as the Mini App receives it, not as the repository
    returns it."""
    os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "")
    os.environ.setdefault("BOT_TOKEN", "catalog-image-test-token")
    os.environ.setdefault("SESSION_SECRET", "catalog-image-session-secret")
    os.environ.setdefault("SIGNING_SECRET", "catalog-image-signing-secret")
    os.environ.setdefault("UPLOADS_ROOT", "/tmp")

    from app.db.pool import close_pool, create_pool
    from app.main import app

    await create_pool(os.environ["DATABASE_URL"])

    @asynccontextmanager
    async def factory():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client

    try:
        yield factory
    finally:
        await close_pool()


async def test_product_detail_images_can_be_signed(conn, clean_slate):
    brand_id = await factories.make_brand(conn, name="ImageTestBrand")
    product_id = await factories.make_product(conn, brand_id=brand_id, name="Image Test Product")
    await factories.make_variant(conn, product_id=product_id, sku="IMG-SKU-1", price=10_000, stock_on_hand=5)
    await conn.execute(
        "INSERT INTO product_images (product_id, storage_path, sort_order, is_primary) "
        "VALUES ($1, 'products/test-image.webp', 0, true)",
        product_id,
    )

    detail = await catalog_service.get_product_detail(conn, product_id=product_id)
    assert len(detail["images"]) == 1

    # Mirrors what the router does — verifying the signer itself accepts
    # this storage_path shape and produces the documented URL format.
    url = signed_url_for_folder(detail["images"][0]["storage_path"], "products", "test-secret")
    assert url.startswith("/files/products/test-image.webp?s=")
    assert "&e=" in url


async def test_listing_returns_a_signed_primary_image_and_never_the_raw_path(conn, clean_slate, app_client_factory):
    """`GET /catalog/products` (the listing the Mini App's catalog/home grids
    render) used to return no image at all — only the detail endpoint did.
    A shop catalogue with no thumbnails is not a usable storefront, so the
    listing now carries the primary image's signed URL.

    Two things are asserted, and the second matters as much as the first:
    the URL is signed (ADR-13), and the raw `storage_path` never leaves the
    server — the query selects it, so it would be trivial to leak it by
    returning the row unchanged."""
    brand_id = await factories.make_brand(conn, name="ListImageBrand")
    product_id = await factories.make_product(conn, brand_id=brand_id, name="Listed Product")
    await factories.make_variant(conn, product_id=product_id, sku="LIST-IMG-1", price=25_000, stock_on_hand=3)
    # Two images, the *second* marked primary — proves the query picks by
    # is_primary rather than by insertion order.
    await conn.execute(
        "INSERT INTO product_images (product_id, storage_path, sort_order, is_primary) "
        "VALUES ($1, 'products/secondary.webp', 0, false)",
        product_id,
    )
    await conn.execute(
        "INSERT INTO product_images (product_id, storage_path, sort_order, is_primary) "
        "VALUES ($1, 'products/primary.webp', 1, true)",
        product_id,
    )

    async with app_client_factory() as client:
        response = await client.get("/catalog/products")

    assert response.status_code == 200, response.text
    item = next(i for i in response.json()["items"] if i["id"] == product_id)

    assert item["primary_image_url"] is not None
    assert item["primary_image_url"].startswith("/files/products/primary.webp?s=")
    assert "&e=" in item["primary_image_url"]
    assert "primary_image_path" not in item
    assert "storage_path" not in item


async def test_listing_image_is_null_for_a_product_with_no_images(conn, clean_slate, app_client_factory):
    """A product without an image must not break the listing — the card
    renders a placeholder, so `null` is the contract, not a missing key."""
    brand_id = await factories.make_brand(conn, name="NoImageBrand")
    product_id = await factories.make_product(conn, brand_id=brand_id, name="Imageless Product")
    await factories.make_variant(conn, product_id=product_id, sku="NO-IMG-1", price=15_000, stock_on_hand=2)

    async with app_client_factory() as client:
        response = await client.get("/catalog/products")

    item = next(i for i in response.json()["items"] if i["id"] == product_id)
    assert "primary_image_url" in item
    assert item["primary_image_url"] is None


# --- Listing card data (brand, fitment, discounted price) --------------------


async def _seed_fitment(conn, product_id: int, model_name: str, gen_name: str,
                        year_from: int | None, year_to: int | None) -> int:
    # `car_brands` is not in clean_slate's TRUNCATE list, so its unique name
    # index survives between tests — a fixed name collides on the second run.
    car_brand_id = await conn.fetchval(
        "INSERT INTO car_brands (name) VALUES ($1) RETURNING id", f"CB-{model_name}-{uuid.uuid4().hex[:8]}"
    )
    model_id = await conn.fetchval(
        "INSERT INTO car_models (car_brand_id, name) VALUES ($1, $2) RETURNING id", car_brand_id, model_name
    )
    gen_id = await conn.fetchval(
        "INSERT INTO car_generations (car_model_id, name, year_from, year_to) VALUES ($1,$2,$3,$4) RETURNING id",
        model_id, gen_name, year_from, year_to,
    )
    await conn.execute(
        "INSERT INTO product_compatibilities (product_id, generation_id) VALUES ($1, $2)", product_id, gen_id
    )
    return model_id


async def test_listing_carries_brand_name(conn, clean_slate, app_client_factory):
    brand_id = await factories.make_brand(conn, name="CardBrand")
    product_id = await factories.make_product(conn, brand_id=brand_id, name="Branded product")
    await factories.make_variant(conn, product_id=product_id, sku="CARD-1", price=10_000, stock_on_hand=4)

    async with app_client_factory() as client:
        response = await client.get("/catalog/products")

    item = next(i for i in response.json()["items"] if i["id"] == product_id)
    assert item["brand_name"] == "CardBrand"


async def test_archived_brand_does_not_hide_the_product(conn, clean_slate, app_client_factory):
    """The brand join is LEFT on purpose: archiving a brand must not silently
    delete every one of its products from the catalogue."""
    brand_id = await factories.make_brand(conn, name="ToArchive")
    product_id = await factories.make_product(conn, brand_id=brand_id, name="Orphaned product")
    await factories.make_variant(conn, product_id=product_id, sku="ORPH-1", price=12_000, stock_on_hand=2)
    await conn.execute("UPDATE brands SET deleted_at = now() WHERE id = $1", brand_id)

    async with app_client_factory() as client:
        response = await client.get("/catalog/products")

    ids = [i["id"] for i in response.json()["items"]]
    assert product_id in ids, "archiving a brand removed its product from the catalogue"
    item = next(i for i in response.json()["items"] if i["id"] == product_id)
    assert item["brand_name"] is None


async def test_fitment_summary_formats_and_orders_by_newest(conn, clean_slate, app_client_factory):
    brand_id = await factories.make_brand(conn, name="FitBrand")
    product_id = await factories.make_product(conn, brand_id=brand_id, name="Fitted product")
    await factories.make_variant(conn, product_id=product_id, sku="FIT-1", price=20_000, stock_on_hand=3)

    await _seed_fitment(conn, product_id, "Older", "gen-old", 2004, 2013)   # closed range
    await _seed_fitment(conn, product_id, "Newer", "gen-new", 2016, None)   # open-ended
    await _seed_fitment(conn, product_id, "Yearless", "gen-none", None, None)

    async with app_client_factory() as client:
        response = await client.get("/catalog/products")

    item = next(i for i in response.json()["items"] if i["id"] == product_id)
    summary = item["fitment_summary"]
    # Newest generation first, and only two are shown.
    assert summary.startswith("Newer 2016+"), summary
    assert "Older 2004–2013" in summary, summary
    assert item["fitment_total"] == 3, "the card must be able to say how many were hidden"


async def test_fitment_without_years_keeps_the_model_name(conn, clean_slate, app_client_factory):
    """A NULL year must not delete the whole entry — string_agg drops NULLs,
    so a yearless compatibility used to vanish silently."""
    brand_id = await factories.make_brand(conn, name="YearlessBrand")
    product_id = await factories.make_product(conn, brand_id=brand_id, name="Yearless product")
    await factories.make_variant(conn, product_id=product_id, sku="YEAR-1", price=9_000, stock_on_hand=1)
    await _seed_fitment(conn, product_id, "NoYears", "gen-x", None, None)

    async with app_client_factory() as client:
        response = await client.get("/catalog/products")

    item = next(i for i in response.json()["items"] if i["id"] == product_id)
    assert item["fitment_summary"] == "NoYears", item["fitment_summary"]
    assert item["fitment_total"] == 1


async def test_filtered_car_model_is_pinned_first_in_the_summary(conn, clean_slate, app_client_factory):
    brand_id = await factories.make_brand(conn, name="PinBrand")
    product_id = await factories.make_product(conn, brand_id=brand_id, name="Pinned product")
    await factories.make_variant(conn, product_id=product_id, sku="PIN-1", price=30_000, stock_on_hand=5)

    await _seed_fitment(conn, product_id, "Newest", "g1", 2020, None)
    wanted_model_id = await _seed_fitment(conn, product_id, "Wanted", "g2", 2010, 2015)

    async with app_client_factory() as client:
        response = await client.get(f"/catalog/products?car_model_id={wanted_model_id}")

    item = next(i for i in response.json()["items"] if i["id"] == product_id)
    # Without the pin, "Newest 2020+" would sort first.
    assert item["fitment_summary"].startswith("Wanted 2010–2015"), item["fitment_summary"]


async def test_listing_price_matches_the_detail_endpoint_when_discounted(conn, clean_slate, app_client_factory):
    """The listing used to show the pre-discount price while the detail
    endpoint showed the discounted one — the same product at two prices."""
    # `discounts` survives clean_slate while `products` is truncated with
    # RESTART IDENTITY, so a leftover target can land on a freshly created
    # product id. Start from a known-clean discount state.
    await conn.execute("UPDATE discounts SET is_active = false")

    brand_id = await factories.make_brand(conn, name="DiscountBrand")
    product_id = await factories.make_product(conn, brand_id=brand_id, name="Discounted product")
    await factories.make_variant(conn, product_id=product_id, sku="DISC-1", price=100_000, stock_on_hand=6)

    discount_id = await conn.fetchval(
        "INSERT INTO discounts (name, kind, value, priority, is_active) "
        "VALUES ('list-test', 'PERCENT', 25, 10, true) RETURNING id"
    )
    await conn.execute(
        "INSERT INTO discount_targets (discount_id, target_type, target_id) VALUES ($1,'PRODUCT',$2)",
        discount_id, product_id,
    )

    async with app_client_factory() as client:
        listing = await client.get("/catalog/products")
        detail = await client.get(f"/catalog/products/{product_id}")

    item = next(i for i in listing.json()["items"] if i["id"] == product_id)
    assert item["min_price"] == 75_000, "listing must show the discounted price"
    assert item["old_price"] == 100_000, "the pre-discount price belongs in old_price"
    assert item["min_price"] == detail.json()["variants"][0]["current_price"]
    assert "base_min_price" not in item, "internal cursor field must not leak to the client"


async def test_old_price_is_null_without_a_discount(conn, clean_slate, app_client_factory):
    await conn.execute("UPDATE discounts SET is_active = false")

    brand_id = await factories.make_brand(conn, name="PlainBrand")
    product_id = await factories.make_product(conn, brand_id=brand_id, name="Plain product")
    await factories.make_variant(conn, product_id=product_id, sku="PLAIN-1", price=50_000, stock_on_hand=3)

    async with app_client_factory() as client:
        response = await client.get("/catalog/products")

    item = next(i for i in response.json()["items"] if i["id"] == product_id)
    assert item["min_price"] == 50_000
    assert item["old_price"] is None


async def test_listing_ignores_a_soft_deleted_primary_image(conn, clean_slate):
    """Haqiqiy nuqson (2026-08-27 lokal tekshiruvda topilgan): ro'yxatning
    rasm subquery sida `deleted_at IS NULL` yo'q edi, shuning uchun adminda
    o'chirilgan rasm katalogda ko'rinishda qolaverardi — admin uni almashtira
    olmasdi. Detal endpointida bu filtr allaqachon bor edi."""
    brand_id = await factories.make_brand(conn, name=f"SoftDelImg-{uuid.uuid4().hex[:8]}")
    product_id = await factories.make_product(conn, brand_id=brand_id, name="Soft Deleted Image Product")
    await factories.make_variant(conn, product_id=product_id, sku=f"SDI-{uuid.uuid4().hex[:8]}", price=10_000, stock_on_hand=5)
    image_id = await conn.fetchval(
        "INSERT INTO product_images (product_id, storage_path, sort_order, is_primary) "
        "VALUES ($1, 'products/x/gone.webp', 0, true) RETURNING id",
        product_id,
    )

    before = await catalog_service.list_products(conn, limit=50)
    assert any(p["id"] == product_id and p["primary_image_path"] == "products/x/gone.webp" for p in before)

    await conn.execute("UPDATE product_images SET deleted_at = now() WHERE id = $1", image_id)

    after = await catalog_service.list_products(conn, limit=50)
    listed = next(p for p in after if p["id"] == product_id)
    assert listed["primary_image_path"] is None


async def test_listing_falls_back_to_the_next_image_when_the_primary_is_deleted(conn, clean_slate):
    brand_id = await factories.make_brand(conn, name=f"SoftDelImg2-{uuid.uuid4().hex[:8]}")
    product_id = await factories.make_product(conn, brand_id=brand_id, name="Fallback Image Product")
    await factories.make_variant(conn, product_id=product_id, sku=f"SDI2-{uuid.uuid4().hex[:8]}", price=10_000, stock_on_hand=5)
    primary_id = await conn.fetchval(
        "INSERT INTO product_images (product_id, storage_path, sort_order, is_primary) "
        "VALUES ($1, 'products/y/primary.webp', 0, true) RETURNING id",
        product_id,
    )
    await conn.execute(
        "INSERT INTO product_images (product_id, storage_path, sort_order, is_primary) "
        "VALUES ($1, 'products/y/second.webp', 1, false)",
        product_id,
    )

    await conn.execute("UPDATE product_images SET deleted_at = now() WHERE id = $1", primary_id)

    after = await catalog_service.list_products(conn, limit=50)
    listed = next(p for p in after if p["id"] == product_id)
    assert listed["primary_image_path"] == "products/y/second.webp"
