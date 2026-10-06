"""Phase 06: admin catalog mutations' audit rows must roll back with the
rest of the transaction — same pattern as
tests/integration/test_audit_transaction.py for order-confirm."""
from __future__ import annotations

import pytest

from app.domains.catalog import service as catalog_service
from tests.integration import factories

pytestmark = pytest.mark.asyncio


async def test_product_create_audit_rolls_back_with_outer_transaction(conn, clean_slate):
    brand_id = await factories.make_brand(conn, name="RollbackBrand")
    admin_id = await factories.make_user(conn, role="ADMIN")

    tx = conn.transaction()
    await tx.start()
    try:
        product = await catalog_service.admin_create_product(
            conn, name="Should Roll Back", description=None, brand_id=brand_id, actor_id=admin_id, actor_role="ADMIN"
        )
        raise RuntimeError("forced failure after create to test rollback")
    except RuntimeError:
        await tx.rollback()

    product_row = await conn.fetchrow("SELECT id FROM products WHERE id = $1", product["id"])
    assert product_row is None  # the product itself rolled back too

    audit_row = await conn.fetchrow(
        "SELECT * FROM audit_logs WHERE entity_type = 'product' AND entity_id = $1 AND action = 'product.create'",
        product["id"],
    )
    assert audit_row is None  # not orphaned
