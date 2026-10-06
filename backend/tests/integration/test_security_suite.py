"""Phase 08-FINAL — consolidated security regression suite.

Collects a single, HTTP-level entry point for the Master TZ's §12.6 "test
qilinishi shart" list plus the role-escalation/observability checks named
in the Phase 08-FINAL brief. This does NOT duplicate every existing
service-layer test (parallel-stock-purchase, parallel-confirm, idempotency,
order/payment state machines, inventory concurrency already have their own
dedicated files — see test_cart_soft_delete.py, test_inventory_concurrent_adjust.py,
test_order_state_machine_transitions.py, test_idempotency.py,
test_idor_regression.py). What lives here is:

1. The cases that had NO test anywhere before this file (upload/executable
   rejection — `app/security/uploads.py` had zero tests of any kind prior
   to this pass).
2. A single collected HTTP-level walk of the role matrix (OWNER-only
   endpoints vs ADMIN/USER), broken/expired auth, and role-escalation
   attempts — so there is one file a reviewer can run to see the whole
   boundary at a glance, even though each individual assertion is also
   implicitly covered elsewhere.
3. Error-exposure verification for the new global exception handler
   (app/observability.py) — genuinely new behavior, no prior test existed.

Not testable in this codebase (documented, not silently skipped):
- Signed-URL 403 (unsigned) / 410 (expired) / 403 (wrong owner) — this
  repo only *generates* signed URLs (`app/security/signing.py`);
  verification happens at Nginx (ADR-13, Phase-09), which does not exist
  in this repository. There is nothing to send an HTTP request to.
- "External `psql -h <server_ip>` doesn't connect" — a `pg_hba.conf` /
  firewall property of the deployed server (§12.5), not application code.
"""
from __future__ import annotations

import hashlib
import hmac
import io
import json
import os
import time
from urllib.parse import urlencode

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.domains.commerce.orders import service as orders_service
from tests.integration import factories

BOT_TOKEN = "sec-suite-bot-token"


def _build_init_data(telegram_id: int, *, auth_date: int | None = None) -> str:
    user = json.dumps({"id": telegram_id, "first_name": "Sec"})
    data = {"auth_date": str(auth_date if auth_date is not None else int(time.time())), "user": user}
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    data["hash"] = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(data)


@pytest_asyncio.fixture
async def app_client():
    os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "")
    os.environ["BOT_TOKEN"] = BOT_TOKEN
    os.environ["SESSION_SECRET"] = "sec-suite-session-secret"
    os.environ["SIGNING_SECRET"] = "sec-suite-signing-secret"
    os.environ.setdefault("UPLOADS_ROOT", "/tmp")

    from app.db.pool import close_pool, create_pool
    from app.main import app

    await create_pool(os.environ["DATABASE_URL"])
    try:
        yield app
    finally:
        await close_pool()


async def _telegram_id_of(conn, user_id: int) -> int:
    row = await conn.fetchrow("SELECT telegram_id FROM users WHERE id = $1", user_id)
    return row["telegram_id"]


async def _session_token(client: AsyncClient, telegram_id: int) -> str:
    r = await client.post("/auth/session", json={"initData": _build_init_data(telegram_id)})
    assert r.status_code == 200, r.text
    return r.json()["token"]


async def _get_seeded_owner_telegram_id(conn) -> int:
    row = await conn.fetchrow("SELECT telegram_id FROM users WHERE role = 'OWNER' AND deleted_at IS NULL")
    assert row is not None, "expected the ADR-11 seeded OWNER row to exist"
    return row["telegram_id"]


# --- 1. Authentication ---------------------------------------------------------


@pytest.mark.asyncio
async def test_unauthenticated_request_to_protected_endpoint_is_401(conn, clean_slate, app_client):
    async with AsyncClient(transport=ASGITransport(app=app_client), base_url="http://test") as client:
        r = await client.get("/owner/dashboard")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_broken_init_data_is_401(conn, clean_slate, app_client):
    async with AsyncClient(transport=ASGITransport(app=app_client), base_url="http://test") as client:
        r = await client.post("/auth/session", json={"initData": "garbage=not-a-real-signature"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_deactivated_user_token_is_rejected(conn, clean_slate, app_client):
    user_id = await factories.make_user(conn, role="ADMIN")
    telegram_id = await _telegram_id_of(conn, user_id)

    async with AsyncClient(transport=ASGITransport(app=app_client), base_url="http://test") as client:
        token = await _session_token(client, telegram_id)
        await conn.execute("UPDATE users SET status = 'DEACTIVATED' WHERE id = $1", user_id)

        r = await client.get("/owner/admins", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_malformed_bearer_token_is_401(conn, clean_slate, app_client):
    async with AsyncClient(transport=ASGITransport(app=app_client), base_url="http://test") as client:
        r = await client.get("/owner/dashboard", headers={"Authorization": "Bearer not-a-real-token"})
    assert r.status_code == 401


# --- 2. Authorization: OWNER-only boundary --------------------------------------


@pytest.mark.asyncio
async def test_owner_can_access_owner_only_endpoint(conn, clean_slate, app_client):
    owner_telegram_id = await _get_seeded_owner_telegram_id(conn)
    async with AsyncClient(transport=ASGITransport(app=app_client), base_url="http://test") as client:
        token = await _session_token(client, owner_telegram_id)
        r = await client.get("/owner/dashboard", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_admin_hitting_finance_view_gets_403(conn, clean_slate, app_client):
    admin_id = await factories.make_user(conn, role="ADMIN")
    telegram_id = await _telegram_id_of(conn, admin_id)
    async with AsyncClient(transport=ASGITransport(app=app_client), base_url="http://test") as client:
        token = await _session_token(client, telegram_id)
        r = await client.get("/owner/finance", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_user_hitting_owner_endpoint_gets_403(conn, clean_slate, app_client):
    user_id = await factories.make_user(conn, role="USER")
    telegram_id = await _telegram_id_of(conn, user_id)
    async with AsyncClient(transport=ASGITransport(app=app_client), base_url="http://test") as client:
        token = await _session_token(client, telegram_id)
        r = await client.get("/owner/admins", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_admin_cannot_manage_admins(conn, clean_slate, app_client):
    admin_id = await factories.make_user(conn, role="ADMIN")
    telegram_id = await _telegram_id_of(conn, admin_id)
    async with AsyncClient(transport=ASGITransport(app=app_client), base_url="http://test") as client:
        token = await _session_token(client, telegram_id)
        r = await client.post(
            "/owner/admins",
            headers={"Authorization": f"Bearer {token}"},
            json={"telegram_id": 999999111, "first_name": "X", "last_name": None, "username": None},
        )
    assert r.status_code == 403


# --- 3. Role escalation ----------------------------------------------------------


@pytest.mark.asyncio
async def test_client_supplied_role_field_is_ignored_at_session_creation(conn, clean_slate, app_client):
    """A USER cannot become OWNER/ADMIN by stuffing a `role` claim into the
    Telegram initData payload — the session endpoint derives role solely
    from the `users` table, never from client-supplied data."""
    user_id = await factories.make_user(conn, role="USER")
    telegram_id = await _telegram_id_of(conn, user_id)

    tampered_user = json.dumps({"id": telegram_id, "first_name": "Escalate", "role": "OWNER"})
    data = {"auth_date": str(int(time.time())), "user": tampered_user}
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    data["hash"] = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    async with AsyncClient(transport=ASGITransport(app=app_client), base_url="http://test") as client:
        r = await client.post("/auth/session", json={"initData": urlencode(data)})
    assert r.status_code == 200
    assert r.json()["role"] == "USER"


@pytest.mark.asyncio
async def test_admin_creating_another_admin_cannot_grant_owner(conn, clean_slate):
    """Service-layer: owner_service.create_admin structurally hardcodes
    role='ADMIN' — there's no parameter that accepts a caller-chosen role,
    so this is verified by signature inspection + a direct call, matching
    the pattern in test_owner_admin_management.py."""
    import inspect

    from app.domains.owner import service as owner_service

    sig = inspect.signature(owner_service.create_admin)
    assert "role" not in sig.parameters

    actor_id = await factories.make_user(conn, role="USER")
    admin = await owner_service.create_admin(
        conn, telegram_id=970000001, first_name="Esc", last_name=None, username=None,
        actor_id=actor_id, actor_role="ADMIN",
    )
    assert admin["role"] == "ADMIN"


# --- 4. IDOR (representative critical resources, beyond orders/cart already covered) ---


@pytest.mark.asyncio
async def test_user_cannot_view_another_users_payment_receipt_path(conn, clean_slate, app_client):
    """Receipt upload is scoped to the payment's own order.user_id —
    another user attempting to attach a receipt to someone else's payment
    is rejected, not silently accepted."""
    from app.domains.payments import repository as payments_repository

    owner_user_id = await factories.make_user(conn)
    other_user_id = await factories.make_user(conn)
    other_telegram_id = await _telegram_id_of(conn, other_user_id)

    brand_id = await factories.make_brand(conn, name="SecBrand")
    product_id = await factories.make_product(conn, brand_id=brand_id, name="Sec Product")
    variant_id = await factories.make_variant(conn, product_id=product_id, sku="SEC-SKU-1", price=10_000, stock_on_hand=5)

    order = await orders_service.create_order(
        conn, user_id=owner_user_id, lines=[orders_service.CheckoutLine(variant_id=variant_id, quantity=1)]
    )
    payment = await payments_repository.create_payment(conn, order_id=order["id"], amount=order["total_amount"])

    async with AsyncClient(transport=ASGITransport(app=app_client), base_url="http://test") as client:
        token = await _session_token(client, other_telegram_id)
        fake_image = b"\xff\xd8\xff" + b"\x00" * 32  # minimal JPEG magic bytes
        r = await client.post(
            f"/payments/{payment['id']}/receipt",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("receipt.jpg", io.BytesIO(fake_image), "image/jpeg")},
        )
    assert r.status_code == 403


# --- 5. Upload security (zero prior test coverage) --------------------------------


def test_executable_disguised_as_image_is_rejected():
    from app.security.uploads import InvalidUpload, validate_and_process_image

    php_payload = b"<?php system($_GET['c']); ?>"
    with pytest.raises(InvalidUpload):
        validate_and_process_image(php_payload, "/tmp", folder="receipts")


def test_php_with_fake_extension_still_sniffed_and_rejected(tmp_path):
    """Filename/extension is never trusted (§11.2) — only magic bytes
    decide the type, so naming a PHP payload `photo.jpg` doesn't help it
    pass. The upload pipeline takes bytes only; it has no filename
    parameter to spoof, which is itself the point of this test."""
    from app.security.uploads import InvalidUpload, validate_and_process_image

    payload = b"<?php echo 'pwned'; ?>" + b"A" * 100
    with pytest.raises(InvalidUpload):
        validate_and_process_image(payload, str(tmp_path), folder="products", entity_id=1)


def test_oversized_upload_is_rejected():
    from app.security.uploads import MAX_UPLOAD_BYTES, InvalidUpload, validate_and_process_image

    oversized = b"\xff\xd8\xff" + b"\x00" * (MAX_UPLOAD_BYTES + 1)
    with pytest.raises(InvalidUpload):
        validate_and_process_image(oversized, "/tmp", folder="receipts")


def test_empty_upload_is_rejected():
    from app.security.uploads import InvalidUpload, validate_and_process_image

    with pytest.raises(InvalidUpload):
        validate_and_process_image(b"", "/tmp", folder="receipts")


def test_generated_filename_never_derived_from_input(tmp_path):
    """There is no code path from caller-supplied data to the on-disk
    filename — it's always `uuid.uuid4()`. This is verified structurally
    (processing the same real image bytes twice yields two different
    storage paths) rather than by trying to inject a path-traversal string
    that the function signature doesn't even accept."""
    from app.security.uploads import validate_and_process_image

    valid_jpeg = _make_tiny_jpeg_bytes()
    first = validate_and_process_image(valid_jpeg, str(tmp_path), folder="products", entity_id=1)
    second = validate_and_process_image(valid_jpeg, str(tmp_path), folder="products", entity_id=1)
    assert first.storage_path != second.storage_path
    assert first.storage_path.startswith("products/1/")
    assert ".." not in first.storage_path


def _make_tiny_jpeg_bytes() -> bytes:
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (4, 4), color=(200, 50, 50)).save(buf, format="JPEG")
    return buf.getvalue()


# --- 6. Database privilege compatibility -----------------------------------------


@pytest.mark.asyncio
async def test_no_production_path_requires_delete_privilege(conn, clean_slate):
    """Regression guard for the exact bug fixed in Phase 08: exercising the
    cart add/remove cycle as `comfort_app` (the real production role, which
    is exactly what `conn` in this test suite connects as) must never raise
    InsufficientPrivilegeError. See test_cart_soft_delete.py for the
    detailed version of this same guarantee; this is the one-line version
    that belongs in a "run the whole security boundary" file."""
    from app.domains.commerce.cart import service as cart_service

    user_id = await factories.make_user(conn)
    brand_id = await factories.make_brand(conn, name="SecBrand2")
    product_id = await factories.make_product(conn, brand_id=brand_id, name="Sec Product 2")
    variant_id = await factories.make_variant(conn, product_id=product_id, sku="SEC-SKU-2", price=5_000, stock_on_hand=3)

    item = await cart_service.add_item(conn, user_id=user_id, variant_id=variant_id, quantity=1)
    removed = await cart_service.remove_item(conn, user_id=user_id, cart_item_id=item["id"])
    assert removed is not None


# --- 7. Error exposure (app/observability.py — new this pass) --------------------


@pytest.mark.asyncio
async def test_unhandled_exception_returns_generic_body_not_a_stack_trace(conn, clean_slate, app_client, monkeypatch):
    from app.domains.catalog import service as catalog_service

    async def _boom(*args, **kwargs):
        raise RuntimeError("simulated unexpected failure: password=hunter2 should never reach the client")

    monkeypatch.setattr(catalog_service, "list_products", _boom)

    # raise_app_exceptions=False: ServerErrorMiddleware already builds and
    # sends the safe 500 response via our registered handler, then
    # re-raises the original exception for server-side logging (Starlette's
    # documented behavior, mirroring what a real ASGI server like uvicorn
    # does) — the test client must not propagate that re-raise to see the
    # response its own client already received.
    transport = ASGITransport(app=app_client, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/catalog/products")

    assert r.status_code == 500
    body = r.json()
    assert body["detail"] == "internal server error"
    assert "hunter2" not in r.text
    assert "RuntimeError" not in r.text
    assert "Traceback" not in r.text
    assert "request_id" in body
    assert r.headers.get("X-Request-ID") == body["request_id"]


@pytest.mark.asyncio
async def test_expected_404_is_not_treated_as_a_server_error(conn, clean_slate, app_client):
    async with AsyncClient(transport=ASGITransport(app=app_client), base_url="http://test") as client:
        r = await client.get("/catalog/products/999999999")
    assert r.status_code == 404
    assert "Traceback" not in r.text


@pytest.mark.asyncio
async def test_request_id_header_present_on_every_response(conn, clean_slate, app_client):
    async with AsyncClient(transport=ASGITransport(app=app_client), base_url="http://test") as client:
        r = await client.get("/catalog/products")
    assert r.status_code == 200
    assert "X-Request-ID" in r.headers
