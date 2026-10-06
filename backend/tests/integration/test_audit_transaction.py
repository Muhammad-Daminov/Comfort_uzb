"""Security's DoD requirement: the shared audit-write helper must be a
transaction participant, not a fire-and-forget/separate-transaction write —
forcing a rollback mid order-confirm must roll the audit row back too."""
from __future__ import annotations

import pytest

from app.domains.commerce.orders import service as orders_service
from tests.integration import factories

pytestmark = pytest.mark.asyncio


async def test_audit_row_participates_in_order_confirm_transaction(conn, clean_slate):
    user_id = await factories.make_user(conn)
    admin_id = await factories.make_user(conn, role="ADMIN")
    brand_id = await factories.make_brand(conn, name="AuditTxBrand")
    product_id = await factories.make_product(conn, brand_id=brand_id, name="Audit Tx Product")
    variant_id = await factories.make_variant(
        conn, product_id=product_id, sku="AUDITTX-SKU-1", price=10_000, stock_on_hand=5
    )

    order = await orders_service.create_order(
        conn, user_id=user_id, lines=[orders_service.CheckoutLine(variant_id=variant_id, quantity=1)]
    )
    await conn.execute("UPDATE orders SET status = 'UNDER_REVIEW' WHERE id = $1", order["id"])

    # Wrap the confirm in an outer transaction we deliberately roll back —
    # simulates a failure after the Service function's own inner work.
    tx = conn.transaction()
    await tx.start()
    try:
        await orders_service.confirm_order(conn, order_id=order["id"], actor_id=admin_id, actor_role="ADMIN")
        raise RuntimeError("forced failure after confirm to test rollback")
    except RuntimeError:
        await tx.rollback()

    order_status = await conn.fetchrow("SELECT status FROM orders WHERE id = $1", order["id"])
    assert order_status["status"] == "UNDER_REVIEW"  # confirm itself rolled back

    audit_row = await conn.fetchrow(
        "SELECT * FROM audit_logs WHERE entity_type = 'order' AND entity_id = $1 AND action = 'order.confirm'",
        order["id"],
    )
    assert audit_row is None  # the audit insert rolled back with everything else, not orphaned
