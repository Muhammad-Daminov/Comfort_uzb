"""Regression tests for the defects found by the full-system audit
(docs/11_FULL_SYSTEM_AUDIT_REPORT.md). One test per confirmed bug, each
named after the report's finding id, each failing on the pre-fix code.

Same conventions as the rest of this directory: real disposable Postgres
via `conn`/`pool` (comfort_app), `clean_slate` truncation, HTTP-level checks
through the ASGI app where the bug was in the Router/handler layer.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import io
import json
import os
import time
import uuid
from datetime import timedelta
from urllib.parse import urlencode

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from PIL import Image

from app.domains.catalog import repository as catalog_repository
from app.domains.catalog import service as catalog_service
from app.domains.commerce.cart import service as cart_service
from app.domains.commerce.orders import service as orders_service
from app.domains.commerce.orders.service import CheckoutLine
from app.domains.payments import service as payments_service
from app.workers import reservation_expiry
from tests.integration import factories

BOT_TOKEN = "audit-regression-bot-token"


def _init_data(telegram_id: int) -> str:
    user = json.dumps({"id": telegram_id, "first_name": "Audit"})
    data = {"auth_date": str(int(time.time())), "user": user}
    check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    data["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(data)


@pytest_asyncio.fixture
async def app_client():
    os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "")
    os.environ["BOT_TOKEN"] = BOT_TOKEN
    os.environ["SESSION_SECRET"] = "audit-session-secret"
    os.environ["SIGNING_SECRET"] = "audit-signing-secret"
    os.environ.setdefault("UPLOADS_ROOT", "/tmp")
    from app.db.pool import close_pool, create_pool
    from app.main import app

    await create_pool(os.environ["DATABASE_URL"])
    try:
        yield app
    finally:
        await close_pool()


async def _token(client: AsyncClient, telegram_id: int) -> str:
    r = await client.post("/auth/session", json={"initData": _init_data(telegram_id)})
    assert r.status_code == 200, r.text
    return r.json()["token"]


async def _catalog(conn, *, price: int = 100_000, stock: int = 10, name: str = "Audit product"):
    brand_id = await factories.make_brand(conn, name=f"AuditBrand-{uuid.uuid4().hex[:6]}")
    product_id = await factories.make_product(conn, brand_id=brand_id, name=name)
    variant_id = await factories.make_variant(
        conn, product_id=product_id, sku=f"AUD-{uuid.uuid4().hex[:8]}", price=price, stock_on_hand=stock
    )
    return brand_id, product_id, variant_id


async def _discount_on_product(conn, *, product_id: int, percent: int) -> None:
    # `clean_slate` truncates products with RESTART IDENTITY but never
    # touches `discounts`, so an earlier test's PRODUCT discount would
    # silently re-attach to this test's product id. Switch them all off.
    await conn.execute("UPDATE discounts SET is_active = false")
    discount_id = await conn.fetchval(
        "INSERT INTO discounts (name, kind, value, priority, is_active) VALUES ($1, 'PERCENT', $2, 1, true) RETURNING id",
        f"audit-{uuid.uuid4().hex[:6]}",
        percent,
    )
    await conn.execute(
        "INSERT INTO discount_targets (discount_id, target_type, target_id) VALUES ($1, 'PRODUCT', $2)",
        discount_id,
        product_id,
    )


async def _to_under_review(conn, *, user_id: int, variant_id: int, uploads_root: str):
    order = await orders_service.create_order(conn, user_id=user_id, lines=[CheckoutLine(variant_id=variant_id, quantity=1)])
    payment = await payments_service.submit_payment(conn, order_id=order["id"], actor_id=user_id, actor_role="USER")
    buf = io.BytesIO()
    Image.new("RGB", (32, 32), (10, 20, 30)).save(buf, format="PNG")
    await payments_service.upload_receipt(
        conn, payment_id=payment["id"], file_bytes=buf.getvalue(), uploads_root=uploads_root, actor_id=user_id, actor_role="USER"
    )
    return order, payment


# --- H2: confirm consumes the reservation; expiry worker never double-releases ----


@pytest.mark.asyncio
async def test_h2_confirm_consumes_reservation_and_expiry_worker_leaves_stock_alone(conn, clean_slate, tmp_path):
    user_id = await factories.make_user(conn)
    admin_id = await factories.make_user(conn, role="ADMIN")
    _, _, variant_id = await _catalog(conn, stock=5)
    # A second, still-open order on the same variant — the victim of a
    # double release (its reserved unit would be silently un-reserved).
    other_user = await factories.make_user(conn)
    await orders_service.create_order(conn, user_id=other_user, lines=[CheckoutLine(variant_id=variant_id, quantity=2)])

    order, _ = await _to_under_review(conn, user_id=user_id, variant_id=variant_id, uploads_root=str(tmp_path))
    await orders_service.confirm_order(conn, order_id=order["id"], actor_id=admin_id, actor_role="ADMIN")

    unreleased = await conn.fetchval(
        "SELECT count(*) FROM stock_reservations WHERE order_id = $1 AND released_at IS NULL", order["id"]
    )
    assert unreleased == 0, "confirm must close (consume) its reservation rows"
    stock = await conn.fetchrow("SELECT stock_on_hand, stock_reserved FROM product_variants WHERE id = $1", variant_id)
    assert (stock["stock_on_hand"], stock["stock_reserved"]) == (4, 2)

    # 24h later: the worker must not touch the confirmed order's reservation
    await conn.execute("UPDATE stock_reservations SET expires_at = now() - interval '1 hour' WHERE order_id = $1", order["id"])
    released = await reservation_expiry.run_once(conn)
    assert released == 0
    stock_after = await conn.fetchrow("SELECT stock_on_hand, stock_reserved FROM product_variants WHERE id = $1", variant_id)
    assert dict(stock_after) == dict(stock), "expiry worker double-released a confirmed order's reservation"
    movements = await conn.fetch(
        "SELECT movement_type FROM inventory_movements WHERE reference_type = 'order' AND reference_id = $1 ORDER BY id",
        order["id"],
    )
    assert [m["movement_type"] for m in movements] == ["RESERVE", "OUT"]


@pytest.mark.asyncio
async def test_h2_expiry_worker_backstop_skips_confirmed_orders_with_stale_reservations(conn, clean_slate, tmp_path):
    """Rows confirmed before the fix still have released_at NULL — the
    worker must skip them rather than release stock that already left."""
    user_id = await factories.make_user(conn)
    admin_id = await factories.make_user(conn, role="ADMIN")
    _, _, variant_id = await _catalog(conn, stock=3)
    order, _ = await _to_under_review(conn, user_id=user_id, variant_id=variant_id, uploads_root=str(tmp_path))
    await orders_service.confirm_order(conn, order_id=order["id"], actor_id=admin_id, actor_role="ADMIN")
    # Simulate the pre-fix state: reservation still open, already expired.
    await conn.execute(
        "UPDATE stock_reservations SET released_at = NULL, expires_at = now() - interval '1 hour' WHERE order_id = $1",
        order["id"],
    )
    released = await reservation_expiry.run_once(conn)
    assert released == 0
    stock = await conn.fetchrow("SELECT stock_on_hand, stock_reserved FROM product_variants WHERE id = $1", variant_id)
    assert (stock["stock_on_hand"], stock["stock_reserved"]) == (2, 0)


@pytest.mark.asyncio
async def test_h2_expiry_worker_isolates_a_poison_row(conn, clean_slate, monkeypatch):
    """One reservation that cannot be released must not starve the rest of
    the batch (the query orders by expires_at, so it used to sit at the
    head forever)."""
    user_id = await factories.make_user(conn)
    _, _, variant_id = await _catalog(conn, stock=10)
    first = await orders_service.create_order(conn, user_id=user_id, lines=[CheckoutLine(variant_id=variant_id, quantity=1)])
    second = await orders_service.create_order(conn, user_id=user_id, lines=[CheckoutLine(variant_id=variant_id, quantity=1)])
    await conn.execute("UPDATE stock_reservations SET expires_at = now() - interval '2 hour' WHERE order_id = $1", first["id"])
    await conn.execute("UPDATE stock_reservations SET expires_at = now() - interval '1 hour' WHERE order_id = $1", second["id"])

    real_release = reservation_expiry.reservations_repository.release_reservation

    async def flaky_release(conn_, *, reservation_id, actor_id):
        row = await conn_.fetchrow("SELECT order_id FROM stock_reservations WHERE id = $1", reservation_id)
        if row["order_id"] == first["id"]:
            raise RuntimeError("poison row")
        return await real_release(conn_, reservation_id=reservation_id, actor_id=actor_id)

    monkeypatch.setattr(reservation_expiry.reservations_repository, "release_reservation", flaky_release)
    released = await reservation_expiry.run_once(conn)
    assert released == 1
    assert await conn.fetchval("SELECT status FROM orders WHERE id = $1", second["id"]) == "EXPIRED"
    assert await conn.fetchval("SELECT status FROM orders WHERE id = $1", first["id"]) == "CREATED"


@pytest.mark.asyncio
async def test_h2_confirm_without_held_stock_fails_cleanly_not_500(conn, clean_slate, tmp_path):
    user_id = await factories.make_user(conn)
    admin_id = await factories.make_user(conn, role="ADMIN")
    _, _, variant_id = await _catalog(conn, stock=1)
    order, _ = await _to_under_review(conn, user_id=user_id, variant_id=variant_id, uploads_root=str(tmp_path))
    # The reservation expired and was released; the unit then sold elsewhere.
    await conn.execute("UPDATE stock_reservations SET released_at = now() WHERE order_id = $1", order["id"])
    await conn.execute("UPDATE product_variants SET stock_reserved = 0, stock_on_hand = 0 WHERE id = $1", variant_id)
    with pytest.raises(orders_service.InsufficientStock):
        await orders_service.confirm_order(conn, order_id=order["id"], actor_id=admin_id, actor_role="ADMIN")
    assert await conn.fetchval("SELECT status FROM orders WHERE id = $1", order["id"]) == "UNDER_REVIEW"


# --- H1: catalog cursor pagination -------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("sort", ["newest", "price_asc", "price_desc", "popular"])
async def test_h1_catalog_second_page_works_for_every_sort(conn, clean_slate, sort):
    brand_id = await factories.make_brand(conn, name=f"PageBrand-{sort}")
    ids = []
    for i in range(5):
        pid = await factories.make_product(conn, brand_id=brand_id, name=f"Paged {sort} {i}")
        await factories.make_variant(conn, product_id=pid, sku=f"PG-{sort}-{i}", price=1000 * (i + 1), stock_on_hand=1)
        ids.append(pid)

    page1 = await catalog_service.list_products(conn, sort=sort, limit=2)
    assert len(page1) == 2
    sort_field = {"newest": "created_at", "price_asc": "min_price", "price_desc": "min_price", "popular": "popularity"}[sort]
    last = page1[-1]
    cursor = catalog_repository.encode_cursor(last["base_min_price"] if sort_field == "min_price" else last[sort_field], last["id"])

    page2 = await catalog_service.list_products(conn, sort=sort, cursor=cursor, limit=2)
    assert len(page2) == 2
    assert {p["id"] for p in page1}.isdisjoint({p["id"] for p in page2})

    with pytest.raises(ValueError):
        await catalog_service.list_products(conn, sort=sort, cursor="!!!not-a-cursor", limit=2)


# --- H7: total_available not inflated by order lines; archived variants excluded --


@pytest.mark.asyncio
async def test_h7_total_available_and_min_price_ignore_order_lines_and_archived_variants(conn, clean_slate):
    user_id = await factories.make_user(conn)
    await conn.execute("UPDATE discounts SET is_active = false")  # see _discount_on_product
    brand_id, product_id, variant_id = await _catalog(conn, stock=10, price=5000)
    await factories.make_variant(conn, product_id=product_id, sku="AUD-ARCH", price=1, stock_on_hand=100, status="ARCHIVED")
    for _ in range(3):  # three order lines on the same variant used to triple the sum
        await orders_service.create_order(conn, user_id=user_id, lines=[CheckoutLine(variant_id=variant_id, quantity=1)])

    [item] = [i for i in await catalog_service.list_products(conn, limit=50) if i["id"] == product_id]
    assert item["total_available"] == 7
    assert item["min_price"] == 5000, "archived variant's price leaked into the card"


# --- H5 + search threshold: search returns card rows and matches single words -------


@pytest.mark.asyncio
async def test_h5_search_returns_card_shape_for_a_single_word_query(conn, clean_slate):
    brand_id, product_id, _ = await _catalog(conn, name="Poyandoz to'plami EVA", price=272_000, stock=4)
    await catalog_repository.rebuild_search_text(conn, product_id=product_id)
    await _discount_on_product(conn, product_id=product_id, percent=10)

    rows = await catalog_service.search_products(conn, query="poyandoz")
    assert [r["id"] for r in rows] == [product_id]
    hit = rows[0]
    assert hit["min_price"] == 244_800 and hit["old_price"] == 272_000
    assert hit["total_available"] == 4
    assert "primary_image_path" in hit and "brand_name" in hit


# --- H4: cart exposes the price checkout will charge -------------------------------


@pytest.mark.asyncio
async def test_h4_cart_current_price_checks_out_on_a_discounted_variant(conn, clean_slate):
    user_id = await factories.make_user(conn)
    _, product_id, variant_id = await _catalog(conn, price=100_000)
    await _discount_on_product(conn, product_id=product_id, percent=20)
    await cart_service.add_item(conn, user_id=user_id, variant_id=variant_id, quantity=1)

    [item] = await cart_service.get_cart(conn, user_id=user_id)
    assert item["price"] == 100_000 and item["current_price"] == 80_000 and item["discount_amount"] == 20_000

    with pytest.raises(orders_service.PriceMismatch):  # what the Mini App used to send
        await orders_service.create_order(conn, user_id=user_id, lines=[CheckoutLine(variant_id, 1, item["price"])])
    order = await orders_service.create_order(conn, user_id=user_id, lines=[CheckoutLine(variant_id, 1, item["current_price"])])
    assert order["total_amount"] == 80_000
    # M3: the ordered line left the cart in the same transaction
    assert await cart_service.get_cart(conn, user_id=user_id) == []


# --- M4: removed compatibilities no longer grant CAR_MODEL discounts at checkout ----


@pytest.mark.asyncio
async def test_m4_soft_deleted_compatibility_does_not_price_checkout(conn, clean_slate):
    user_id = await factories.make_user(conn)
    _, product_id, variant_id = await _catalog(conn, price=50_000)
    car_brand = await conn.fetchval("INSERT INTO car_brands (name) VALUES ($1) RETURNING id", f"CB-{uuid.uuid4().hex[:6]}")
    car_model = await conn.fetchval("INSERT INTO car_models (car_brand_id, name) VALUES ($1, 'M') RETURNING id", car_brand)
    gen = await conn.fetchval("INSERT INTO car_generations (car_model_id, name) VALUES ($1, 'G') RETURNING id", car_model)
    await conn.execute(
        "INSERT INTO product_compatibilities (product_id, generation_id, deleted_at) VALUES ($1, $2, now())", product_id, gen
    )
    await conn.execute("UPDATE discounts SET is_active = false")
    discount_id = await conn.fetchval(
        "INSERT INTO discounts (name, kind, value, priority, is_active) VALUES ('cm', 'PERCENT', 50, 1, true) RETURNING id"
    )
    await conn.execute(
        "INSERT INTO discount_targets (discount_id, target_type, target_id) VALUES ($1, 'CAR_MODEL', $2)", discount_id, car_model
    )
    order = await orders_service.create_order(conn, user_id=user_id, lines=[CheckoutLine(variant_id, 1, 50_000)])
    assert order["total_amount"] == 50_000
    [card] = [i for i in await catalog_service.list_products(conn, limit=50) if i["id"] == product_id]
    assert card["min_price"] == 50_000  # listing and checkout agree


# --- H6 / M2: payment review drives the order state; one PENDING payment per order --


@pytest.mark.asyncio
async def test_h6_rejected_payment_moves_order_to_rejected(conn, clean_slate, tmp_path):
    user_id = await factories.make_user(conn)
    admin_id = await factories.make_user(conn, role="ADMIN")
    _, _, variant_id = await _catalog(conn)
    order, payment = await _to_under_review(conn, user_id=user_id, variant_id=variant_id, uploads_root=str(tmp_path))

    await payments_service.review_payment(
        conn, payment_id=payment["id"], approve=False, rejection_reason="blurry", actor_id=admin_id, actor_role="ADMIN"
    )
    assert await conn.fetchval("SELECT status FROM orders WHERE id = $1", order["id"]) == "REJECTED"
    assert await conn.fetchval("SELECT count(*) FROM audit_logs WHERE action = 'order.reject' AND entity_id = $1", order["id"]) == 1
    # REJECTED -> CANCELLED (the only transition the TZ allows) still works
    await orders_service.cancel_order(conn, order_id=order["id"], reason="user gave up on it", actor_id=user_id, actor_role="USER")
    assert await conn.fetchval("SELECT count(*) FROM stock_reservations WHERE order_id = $1 AND released_at IS NULL", order["id"]) == 0


@pytest.mark.asyncio
async def test_h6_payment_on_cancelled_order_cannot_be_approved(conn, clean_slate, tmp_path):
    user_id = await factories.make_user(conn)
    admin_id = await factories.make_user(conn, role="ADMIN")
    _, _, variant_id = await _catalog(conn)
    order, payment = await _to_under_review(conn, user_id=user_id, variant_id=variant_id, uploads_root=str(tmp_path))
    await orders_service.cancel_order(conn, order_id=order["id"], reason="cancelled before review", actor_id=user_id, actor_role="USER")

    with pytest.raises(payments_service.OrderNotReviewable):
        await payments_service.review_payment(
            conn, payment_id=payment["id"], approve=True, rejection_reason=None, actor_id=admin_id, actor_role="ADMIN"
        )
    assert await conn.fetchval("SELECT paid_amount FROM orders WHERE id = $1", order["id"]) == 0
    assert await conn.fetchval("SELECT status FROM payments WHERE id = $1", payment["id"]) == "PENDING"


@pytest.mark.asyncio
async def test_m2_second_submit_returns_the_existing_pending_payment(conn, clean_slate):
    user_id = await factories.make_user(conn)
    _, _, variant_id = await _catalog(conn)
    order = await orders_service.create_order(conn, user_id=user_id, lines=[CheckoutLine(variant_id=variant_id, quantity=1)])
    first = await payments_service.submit_payment(conn, order_id=order["id"], actor_id=user_id, actor_role="USER")
    second = await payments_service.submit_payment(conn, order_id=order["id"], actor_id=user_id, actor_role="USER")
    assert first["id"] == second["id"]
    assert await conn.fetchval("SELECT count(*) FROM payments WHERE order_id = $1", order["id"]) == 1


# --- M1: concurrent same-key requests execute the Service call exactly once --------


@pytest.mark.asyncio
async def test_m1_concurrent_same_idempotency_key_creates_one_order(pool, conn, clean_slate, app_client):
    _, _, variant_id = await _catalog(conn, stock=10)
    async with AsyncClient(transport=ASGITransport(app=app_client), base_url="http://test") as client:
        token = await _token(client, 880_000_001)
        headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": str(uuid.uuid4())}
        body = {"lines": [{"variant_id": variant_id, "quantity": 1}]}
        responses = await asyncio.gather(*[client.post("/orders", json=body, headers=headers) for _ in range(5)])
    assert {r.status_code for r in responses} == {201}, [r.text for r in responses]
    assert len({r.json()["id"] for r in responses}) == 1
    assert await conn.fetchval("SELECT count(*) FROM orders") == 1
    assert await conn.fetchval("SELECT stock_reserved FROM product_variants WHERE id = $1", variant_id) == 1


@pytest.mark.asyncio
async def test_m1_failed_outcome_is_stored_and_replayed(conn, clean_slate, app_client):
    _, _, variant_id = await _catalog(conn, stock=1)
    async with AsyncClient(transport=ASGITransport(app=app_client), base_url="http://test") as client:
        token = await _token(client, 880_000_002)
        headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": str(uuid.uuid4())}
        body = {"lines": [{"variant_id": variant_id, "quantity": 5}]}
        first = await client.post("/orders", json=body, headers=headers)
        second = await client.post("/orders", json=body, headers=headers)
    assert first.status_code == second.status_code == 409
    assert first.json()["error"]["code"] == "INSUFFICIENT_STOCK"
    assert await conn.fetchval("SELECT count(*) FROM idempotency_keys") == 1


# --- H3: every error response carries the §13.5 envelope --------------------------


@pytest.mark.asyncio
async def test_h3_error_envelope_on_every_error_class(conn, clean_slate, app_client):
    _, product_id, variant_id = await _catalog(conn, price=100_000)
    await _discount_on_product(conn, product_id=product_id, percent=10)
    async with AsyncClient(transport=ASGITransport(app=app_client), base_url="http://test") as client:
        unauthenticated = await client.get("/cart")
        token = await _token(client, 880_000_003)
        auth = {"Authorization": f"Bearer {token}"}
        validation = await client.post("/cart/items", json={"variant_id": "abc"}, headers=auth)
        forbidden = await client.get("/admin/orders", headers=auth)
        mismatch = await client.post(
            "/orders",
            json={"lines": [{"variant_id": variant_id, "quantity": 1, "client_unit_price": 100_000}]},
            headers={**auth, "Idempotency-Key": str(uuid.uuid4())},
        )
        not_found = await client.get("/orders/999999", headers=auth)

    assert unauthenticated.status_code == 401 and unauthenticated.json()["error"]["code"] == "UNAUTHORIZED"
    assert validation.status_code == 422 and validation.json()["error"]["code"] == "VALIDATION_ERROR"
    assert forbidden.status_code == 403 and forbidden.json()["error"]["code"] == "FORBIDDEN"
    assert not_found.status_code == 404 and not_found.json()["error"]["code"] == "NOT_FOUND"
    assert mismatch.status_code == 409
    envelope = mismatch.json()["error"]
    assert envelope["code"] == "PRICE_MISMATCH"
    assert envelope["details"]["lines"][0] == {"variant_id": variant_id, "expected_unit_price": 90_000}
    # `detail` is still present for FastAPI-conventional clients
    assert "detail" in mismatch.json()


@pytest.mark.asyncio
async def test_m11_500_response_carries_the_real_request_id(conn, clean_slate, app_client, monkeypatch):
    async def boom(*args, **kwargs):
        raise RuntimeError("audit-induced failure")

    monkeypatch.setattr("app.domains.catalog.router.service.list_filters", boom)
    async with AsyncClient(transport=ASGITransport(app=app_client, raise_app_exceptions=False), base_url="http://test") as client:
        r = await client.get("/catalog/filters", headers={"X-Request-ID": "audit-req-42"})
    assert r.status_code == 500
    assert r.headers["x-request-id"] == "audit-req-42"
    assert r.json()["request_id"] == "audit-req-42"
    assert r.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "audit-induced" not in r.text


@pytest.mark.asyncio
async def test_m11_hostile_request_id_header_is_replaced(conn, clean_slate, app_client):
    async with AsyncClient(transport=ASGITransport(app=app_client), base_url="http://test") as client:
        r = await client.get("/health/live", headers={"X-Request-ID": "x" * 500 + "\"}"})
    assert r.status_code == 200
    echoed = r.headers["x-request-id"]
    assert len(echoed) <= 128 and '"' not in echoed


# --- M6: admin lists take a bounded limit -----------------------------------------


@pytest.mark.asyncio
async def test_m6_admin_orders_limit_param(conn, clean_slate, app_client):
    user_id = await factories.make_user(conn)
    _, _, variant_id = await _catalog(conn, stock=50)
    for _ in range(25):
        await orders_service.create_order(conn, user_id=user_id, lines=[CheckoutLine(variant_id=variant_id, quantity=1)])
    admin_id = await factories.make_user(conn, role="ADMIN")
    admin_tg = await conn.fetchval("SELECT telegram_id FROM users WHERE id = $1", admin_id)
    async with AsyncClient(transport=ASGITransport(app=app_client), base_url="http://test") as client:
        token = await _token(client, admin_tg)
        default = await client.get("/admin/orders", headers={"Authorization": f"Bearer {token}"})
        wide = await client.get("/admin/orders?limit=200", headers={"Authorization": f"Bearer {token}"})
        too_wide = await client.get("/admin/orders?limit=201", headers={"Authorization": f"Bearer {token}"})
    assert len(default.json()["items"]) == 20
    assert len(wide.json()["items"]) == 25
    assert too_wide.status_code == 422


# --- M10: concurrent set-primary never trips the partial unique index ---------------


@pytest.mark.asyncio
async def test_m10_concurrent_set_primary_serialises(pool, conn, clean_slate):
    admin_id = await factories.make_user(conn, role="ADMIN")
    _, product_id, _ = await _catalog(conn)
    image_ids = []
    for i in range(2):
        image = await catalog_service.admin_add_image(
            conn, product_id=product_id, storage_path=f"products/{product_id}/{i}.webp", width=1, height=1,
            actor_id=admin_id, actor_role="ADMIN",
        )
        image_ids.append(image["id"])

    async def flip(image_id: int) -> None:
        async with pool.acquire() as c:
            for _ in range(10):
                await catalog_service.admin_set_primary_image(
                    c, image_id=image_id, product_id=product_id, actor_id=admin_id, actor_role="ADMIN"
                )

    await asyncio.gather(flip(image_ids[0]), flip(image_ids[1]))  # must not raise UniqueViolationError
    primaries = await conn.fetchval(
        "SELECT count(*) FROM product_images WHERE product_id = $1 AND is_primary AND deleted_at IS NULL", product_id
    )
    assert primaries == 1


# --- Uploads: size cap enforced while reading, file modes per ADR-14 --------------


@pytest.mark.asyncio
async def test_upload_size_cap_is_enforced_before_buffering(conn, clean_slate, app_client, tmp_path, monkeypatch):
    monkeypatch.setenv("UPLOADS_ROOT", str(tmp_path))
    user_id = await factories.make_user(conn)
    user_tg = await conn.fetchval("SELECT telegram_id FROM users WHERE id = $1", user_id)
    _, _, variant_id = await _catalog(conn)
    order = await orders_service.create_order(conn, user_id=user_id, lines=[CheckoutLine(variant_id=variant_id, quantity=1)])
    payment = await payments_service.submit_payment(conn, order_id=order["id"], actor_id=user_id, actor_role="USER")
    huge = b"\x89PNG\r\n\x1a\n" + b"\0" * (5 * 1024 * 1024 + 10)
    async with AsyncClient(transport=ASGITransport(app=app_client), base_url="http://test") as client:
        token = await _token(client, user_tg)
        r = await client.post(
            f"/payments/{payment['id']}/receipt", files={"file": ("x.png", huge, "image/png")},
            headers={"Authorization": f"Bearer {token}"},
        )
        buf = io.BytesIO()
        Image.new("RGB", (16, 16), (1, 2, 3)).save(buf, format="PNG")
        ok = await client.post(
            f"/payments/{payment['id']}/receipt", files={"file": ("x.png", buf.getvalue(), "image/png")},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 422 and "exceeds" in r.json()["error"]["message"]
    assert ok.status_code == 200
    [written] = list((tmp_path / "receipts").iterdir())
    assert oct(written.stat().st_mode & 0o777) == "0o640"
    assert oct((tmp_path / "receipts").stat().st_mode & 0o777) == "0o750"


# --- Post-audit stabilization pass (docs/12_POST_AUDIT_STABILIZATION_REPORT.md) ------


@pytest.mark.asyncio
async def test_p1_multi_word_search_requires_every_word_and_maps_aliases(conn, clean_slate):
    brand_id = await factories.make_brand(conn, name=f"SB-{uuid.uuid4().hex[:6]}")
    car_brand = await conn.fetchval("INSERT INTO car_brands (name) VALUES ($1) RETURNING id", f"Chev-{uuid.uuid4().hex[:6]}")
    model = await conn.fetchval("INSERT INTO car_models (car_brand_id, name) VALUES ($1, 'Nexia') RETURNING id", car_brand)
    gen = await conn.fetchval("INSERT INTO car_generations (car_model_id, name) VALUES ($1, 'N150') RETURNING id", model)
    mat = await factories.make_product(conn, brand_id=brand_id, name="Salon gilamchasi")
    cover = await factories.make_product(conn, brand_id=brand_id, name="Salon qoplamasi")
    for pid in (mat, cover):
        await factories.make_variant(conn, product_id=pid, sku=f"S-{pid}", price=1000, stock_on_hand=1)
    await conn.execute("INSERT INTO product_compatibilities (product_id, generation_id) VALUES ($1, $2)", mat, gen)
    for pid in (mat, cover):
        await catalog_repository.rebuild_search_text(conn, product_id=pid)
    await conn.execute("INSERT INTO search_aliases (alias, canonical, entity_type) VALUES ('neksiya', 'nexia', 'car_model') ON CONFLICT DO NOTHING")

    ids = lambda rows: [r["id"] for r in rows]
    assert ids(await catalog_service.search_products(conn, query="nexia gilam")) == [mat]
    assert ids(await catalog_service.search_products(conn, query="neksiya gilam")) == [mat]  # alias per word
    assert ids(await catalog_service.search_products(conn, query="gilam nexia")) == [mat]  # order-free
    assert ids(await catalog_service.search_products(conn, query="nexia qoplama")) == []  # every word must match
    assert set(ids(await catalog_service.search_products(conn, query="salon"))) == {mat, cover}
    assert await catalog_service.search_products(conn, query="   ") == []


@pytest.mark.asyncio
async def test_p2_total_available_with_many_related_rows(conn, clean_slate):
    """product + 3 order lines + 2 compatibilities + 2 images + 2 discounts +
    1 archived variant: every join multiplier that could inflate the sum."""
    await conn.execute("UPDATE discounts SET is_active = false")
    user_id = await factories.make_user(conn)
    admin_id = await factories.make_user(conn, role="ADMIN")
    brand_id, product_id, variant_id = await _catalog(conn, stock=10, price=5000)
    v2 = await factories.make_variant(conn, product_id=product_id, sku="AUD-V2", price=7000, stock_on_hand=4)
    await factories.make_variant(conn, product_id=product_id, sku="AUD-ARCH2", price=1, stock_on_hand=99, status="ARCHIVED")
    car_brand = await conn.fetchval("INSERT INTO car_brands (name) VALUES ($1) RETURNING id", f"CB-{uuid.uuid4().hex[:6]}")
    model = await conn.fetchval("INSERT INTO car_models (car_brand_id, name) VALUES ($1, 'M') RETURNING id", car_brand)
    for g in ("G1", "G2"):
        gen = await conn.fetchval("INSERT INTO car_generations (car_model_id, name) VALUES ($1, $2) RETURNING id", model, g)
        await conn.execute("INSERT INTO product_compatibilities (product_id, generation_id) VALUES ($1, $2)", product_id, gen)
    for i in range(2):
        await catalog_service.admin_add_image(conn, product_id=product_id, storage_path=f"products/{product_id}/{i}.webp", width=1, height=1, actor_id=admin_id, actor_role="ADMIN")
    await _discount_on_product(conn, product_id=product_id, percent=5)  # deactivates everything else first
    second = await conn.fetchval(
        "INSERT INTO discounts (name, kind, value, priority, is_active) VALUES ('p2-ten', 'PERCENT', 10, 1, true) RETURNING id"
    )
    await conn.execute("INSERT INTO discount_targets (discount_id, target_type, target_id) VALUES ($1, 'PRODUCT', $2)", second, product_id)
    for _ in range(3):
        await orders_service.create_order(conn, user_id=user_id, lines=[CheckoutLine(variant_id=variant_id, quantity=1), CheckoutLine(variant_id=v2, quantity=1)])

    [card] = [i for i in await catalog_service.list_products(conn, limit=50) if i["id"] == product_id]
    assert card["total_available"] == (10 - 3) + (4 - 3)
    assert card["min_price"] == 4500 and card["old_price"] == 5000  # best discount (10%) on the cheapest ACTIVE variant
    [hit] = await catalog_service.search_products(conn, query="audit")
    assert hit["total_available"] == card["total_available"] and hit["min_price"] == card["min_price"]


@pytest.mark.asyncio
async def test_p3_idempotency_retry_after_server_error_gets_a_clean_run(conn, clean_slate, app_client, monkeypatch):
    """A 500 inside the scope must store nothing, so the client's retry with
    the same key executes for real instead of replaying an error."""
    _, _, variant_id = await _catalog(conn, stock=5)
    import app.domains.commerce.orders.router as orders_router

    real = orders_router.service.create_order
    calls = {"n": 0}

    async def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient failure after partial work")
        return await real(*args, **kwargs)

    monkeypatch.setattr(orders_router.service, "create_order", flaky)
    async with AsyncClient(transport=ASGITransport(app=app_client, raise_app_exceptions=False), base_url="http://test") as client:
        token = await _token(client, 880_000_004)
        headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": str(uuid.uuid4())}
        body = {"lines": [{"variant_id": variant_id, "quantity": 1}]}
        first = await client.post("/orders", json=body, headers=headers)
        second = await client.post("/orders", json=body, headers=headers)
        third = await client.post("/orders", json=body, headers=headers)
    assert first.status_code == 500 and first.json()["error"]["code"] == "INTERNAL_ERROR"
    assert second.status_code == 201
    assert third.status_code == 201 and third.json()["id"] == second.json()["id"]
    assert await conn.fetchval("SELECT count(*) FROM orders") == 1
    assert await conn.fetchval("SELECT count(*) FROM idempotency_keys") == 1


@pytest.mark.asyncio
async def test_p4_duplicate_approval_never_double_counts(conn, clean_slate, tmp_path):
    user_id = await factories.make_user(conn)
    admin_id = await factories.make_user(conn, role="ADMIN")
    _, _, variant_id = await _catalog(conn)
    order, payment = await _to_under_review(conn, user_id=user_id, variant_id=variant_id, uploads_root=str(tmp_path))
    await payments_service.review_payment(conn, payment_id=payment["id"], approve=True, rejection_reason=None, actor_id=admin_id, actor_role="ADMIN")
    for approve in (True, False):
        with pytest.raises(ValueError):
            await payments_service.review_payment(conn, payment_id=payment["id"], approve=approve, rejection_reason="x", actor_id=admin_id, actor_role="ADMIN")
    row = await conn.fetchrow("SELECT paid_amount, total_amount, remaining_amount FROM orders WHERE id = $1", order["id"])
    assert row["paid_amount"] == row["total_amount"] and row["remaining_amount"] == 0
    assert await conn.fetchval("SELECT status FROM payments WHERE id = $1", payment["id"]) == "APPROVED"


@pytest.mark.asyncio
async def test_p5_last_page_has_no_next_cursor(conn, clean_slate, app_client):
    brand_id = await factories.make_brand(conn, name="LastPage")
    for i in range(3):
        pid = await factories.make_product(conn, brand_id=brand_id, name=f"LP {i}")
        await factories.make_variant(conn, product_id=pid, sku=f"LP-{i}", price=100, stock_on_hand=1)
    async with AsyncClient(transport=ASGITransport(app=app_client), base_url="http://test") as client:
        page1 = (await client.get("/catalog/products?limit=2")).json()
        page2 = (await client.get(f"/catalog/products?limit=2&cursor={page1['next_cursor']}")).json()
        exact = (await client.get("/catalog/products?limit=3")).json()
    assert len(page1["items"]) == 2 and page1["next_cursor"]
    assert len(page2["items"]) == 1 and page2["next_cursor"] is None
    assert len(exact["items"]) == 3 and exact["next_cursor"]  # a full page may still be followed by an empty one


@pytest.mark.asyncio
async def test_p6_reservation_ledger_invariant_across_all_paths(conn, clean_slate, tmp_path):
    """stock_reserved must always equal the sum of open reservations —
    across create, cancel, expiry, and confirm (consume)."""
    user_id = await factories.make_user(conn)
    admin_id = await factories.make_user(conn, role="ADMIN")
    _, _, variant_id = await _catalog(conn, stock=20)
    o_cancel = await orders_service.create_order(conn, user_id=user_id, lines=[CheckoutLine(variant_id=variant_id, quantity=2)])
    o_expire = await orders_service.create_order(conn, user_id=user_id, lines=[CheckoutLine(variant_id=variant_id, quantity=3)])
    o_keep = await orders_service.create_order(conn, user_id=user_id, lines=[CheckoutLine(variant_id=variant_id, quantity=4)])
    o_confirm, _ = await _to_under_review(conn, user_id=user_id, variant_id=variant_id, uploads_root=str(tmp_path))
    await orders_service.cancel_order(conn, order_id=o_cancel["id"], reason="ledger invariant test", actor_id=user_id, actor_role="USER")
    await conn.execute("UPDATE stock_reservations SET expires_at = now() - interval '1 hour' WHERE order_id = $1", o_expire["id"])
    await reservation_expiry.run_once(conn)
    await orders_service.confirm_order(conn, order_id=o_confirm["id"], actor_id=admin_id, actor_role="ADMIN")

    stock = await conn.fetchrow("SELECT stock_on_hand, stock_reserved FROM product_variants WHERE id = $1", variant_id)
    open_sum = await conn.fetchval("SELECT COALESCE(SUM(quantity), 0) FROM stock_reservations WHERE variant_id = $1 AND released_at IS NULL", variant_id)
    assert stock["stock_reserved"] == open_sum == 4
    assert stock["stock_on_hand"] == 19
    ledger = await conn.fetch("SELECT movement_type, quantity_change FROM inventory_movements WHERE variant_id = $1 ORDER BY id", variant_id)
    assert sum(m["quantity_change"] for m in ledger if m["movement_type"] == "OUT") == -1
    assert await conn.fetchval("SELECT count(*) FROM stock_reservations WHERE order_id = $1 AND released_at IS NULL", o_keep["id"]) == 1
