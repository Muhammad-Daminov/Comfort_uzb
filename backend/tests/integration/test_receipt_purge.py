"""`comfort-receipt-purge` worker logic (ADR-9) — deletes receipt files
past their retention date, stamps `file_purged_at`, is idempotent, never
touches a file outside the managed uploads root, and never deletes a file
whose retention hasn't expired yet."""
from __future__ import annotations

import pytest

from app.domains.payments import repository as payments_repository
from app.workers import receipt_purge
from tests.integration import factories

pytestmark = pytest.mark.asyncio


async def _make_payment_with_receipt(conn, *, uploads_root, retention_past: bool):
    user_id = await factories.make_user(conn)
    brand_id = await factories.make_brand(conn, name="PurgeBrand")
    product_id = await factories.make_product(conn, brand_id=brand_id, name="Purge Product")
    variant_id = await factories.make_variant(conn, product_id=product_id, sku="PURGE-SKU-1", price=10_000, stock_on_hand=5)

    from app.domains.commerce.orders import service as orders_service

    order = await orders_service.create_order(
        conn, user_id=user_id, lines=[orders_service.CheckoutLine(variant_id=variant_id, quantity=1)]
    )
    payment = await payments_repository.create_payment(conn, order_id=order["id"], amount=order["total_amount"])

    receipts_dir = uploads_root / "receipts"
    receipts_dir.mkdir(parents=True, exist_ok=True)
    file_path = receipts_dir / "test-receipt.webp"
    file_path.write_bytes(b"fake-webp-bytes")

    receipt = await payments_repository.create_receipt(conn, payment_id=payment["id"], storage_path="receipts/test-receipt.webp")
    if retention_past:
        await conn.execute(
            "UPDATE payment_receipts SET retention_until = now() - interval '1 day' WHERE id = $1", receipt["id"]
        )
    return receipt, file_path


async def test_purges_file_and_stamps_file_purged_at_past_retention(conn, clean_slate, tmp_path):
    receipt, file_path = await _make_payment_with_receipt(conn, uploads_root=tmp_path, retention_past=True)
    assert file_path.exists()

    purged_count = await receipt_purge.run_once(conn, uploads_root=str(tmp_path))

    assert purged_count == 1
    assert not file_path.exists()
    row = await conn.fetchrow("SELECT file_purged_at FROM payment_receipts WHERE id = $1", receipt["id"])
    assert row["file_purged_at"] is not None


async def test_receipt_not_yet_past_retention_is_left_alone(conn, clean_slate, tmp_path):
    receipt, file_path = await _make_payment_with_receipt(conn, uploads_root=tmp_path, retention_past=False)

    purged_count = await receipt_purge.run_once(conn, uploads_root=str(tmp_path))

    assert purged_count == 0
    assert file_path.exists()
    row = await conn.fetchrow("SELECT file_purged_at FROM payment_receipts WHERE id = $1", receipt["id"])
    assert row["file_purged_at"] is None


async def test_running_worker_twice_is_a_noop_second_time(conn, clean_slate, tmp_path):
    receipt, file_path = await _make_payment_with_receipt(conn, uploads_root=tmp_path, retention_past=True)

    first_run = await receipt_purge.run_once(conn, uploads_root=str(tmp_path))
    second_run = await receipt_purge.run_once(conn, uploads_root=str(tmp_path))

    assert first_run == 1
    assert second_run == 0  # the guarded-update no-op contract


async def test_missing_file_on_disk_is_handled_idempotently(conn, clean_slate, tmp_path):
    """A file could already be gone (manual cleanup, a prior partial run
    that deleted the file but crashed before the guarded UPDATE committed)
    — the worker must still mark the row purged, not raise."""
    receipt, file_path = await _make_payment_with_receipt(conn, uploads_root=tmp_path, retention_past=True)
    file_path.unlink()  # simulate the file already being gone

    purged_count = await receipt_purge.run_once(conn, uploads_root=str(tmp_path))

    assert purged_count == 1
    row = await conn.fetchrow("SELECT file_purged_at FROM payment_receipts WHERE id = $1", receipt["id"])
    assert row["file_purged_at"] is not None


async def test_never_deletes_a_file_outside_the_uploads_root(conn, clean_slate, tmp_path):
    """Defense-in-depth: even though storage_path is always server-generated,
    a corrupted/malicious value must never cause a delete outside the
    managed uploads root."""
    outside_root = tmp_path / "outside"
    outside_root.mkdir()
    escape_target = outside_root / "should-not-be-deleted.webp"
    escape_target.write_bytes(b"do-not-delete")

    uploads_root = tmp_path / "uploads"
    uploads_root.mkdir()

    user_id = await factories.make_user(conn)
    brand_id = await factories.make_brand(conn, name="EscapeBrand")
    product_id = await factories.make_product(conn, brand_id=brand_id, name="Escape Product")
    variant_id = await factories.make_variant(conn, product_id=product_id, sku="ESCAPE-SKU-1", price=10_000, stock_on_hand=5)

    from app.domains.commerce.orders import service as orders_service

    order = await orders_service.create_order(
        conn, user_id=user_id, lines=[orders_service.CheckoutLine(variant_id=variant_id, quantity=1)]
    )
    payment = await payments_repository.create_payment(conn, order_id=order["id"], amount=order["total_amount"])
    receipt = await payments_repository.create_receipt(
        conn, payment_id=payment["id"], storage_path="../outside/should-not-be-deleted.webp"
    )
    await conn.execute(
        "UPDATE payment_receipts SET retention_until = now() - interval '1 day' WHERE id = $1", receipt["id"]
    )

    purged_count = await receipt_purge.run_once(conn, uploads_root=str(uploads_root))

    assert purged_count == 0
    assert escape_target.exists()
