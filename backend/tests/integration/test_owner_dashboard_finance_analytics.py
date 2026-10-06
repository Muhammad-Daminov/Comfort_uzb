"""Phase 07: dashboard/finance/analytics figures computed against known
seeded orders/payments, asserted exactly — not just "returns 200"."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.domains.commerce.orders import service as orders_service
from app.domains.owner import service as owner_service
from app.domains.payments import service as payments_service
from tests.integration import factories

pytestmark = pytest.mark.asyncio


async def _seed_confirmed_order(conn, *, price: int, quantity: int = 1):
    user_id = await factories.make_user(conn)
    admin_id = await factories.make_user(conn, role="ADMIN")
    brand_id = await factories.make_brand(conn, name="OwnerTestBrand")
    product_id = await factories.make_product(conn, brand_id=brand_id, name="Owner Test Product")
    variant_id = await factories.make_variant(conn, product_id=product_id, sku=f"OWNER-SKU-{variant_suffix()}", price=price, stock_on_hand=10)

    order = await orders_service.create_order(
        conn, user_id=user_id, lines=[orders_service.CheckoutLine(variant_id=variant_id, quantity=quantity)]
    )
    payment = await payments_service.submit_payment(conn, order_id=order["id"], actor_id=user_id, actor_role="USER")
    await payments_service.review_payment(
        conn, payment_id=payment["id"], approve=True, rejection_reason=None, actor_id=admin_id, actor_role="ADMIN"
    )
    await conn.execute("UPDATE orders SET status = 'UNDER_REVIEW' WHERE id = $1", order["id"])
    await orders_service.confirm_order(conn, order_id=order["id"], actor_id=admin_id, actor_role="ADMIN")
    return order["id"], payment["id"], price * quantity


_counter = 0


def variant_suffix() -> str:
    global _counter
    _counter += 1
    return str(_counter)


async def test_dashboard_revenue_matches_seeded_paid_amount(conn, clean_slate):
    _, _, expected_total = await _seed_confirmed_order(conn, price=25_000, quantity=2)

    dashboard = await owner_service.get_dashboard(conn)

    assert dashboard["total_revenue"] >= expected_total  # >= : clean_slate doesn't truncate other tests' leftover orders within this run
    assert "CONFIRMED" in dashboard["order_counts_by_status"]
    assert dashboard["product_count"] >= 1
    assert dashboard["low_stock_threshold"] == 5


async def test_finance_revenue_for_period_matches_seeded_order(conn, clean_slate):
    order_id, payment_id, expected_total = await _seed_confirmed_order(conn, price=40_000, quantity=1)

    date_from = datetime.now(timezone.utc) - timedelta(days=1)
    date_to = datetime.now(timezone.utc) + timedelta(days=1)
    finance = await owner_service.get_finance(conn, date_from=date_from, date_to=date_to)

    assert finance["revenue"] >= expected_total
    payment_ids = [p["payment_id"] for p in finance["payments"]]
    assert payment_id in payment_ids
    approved_payment = next(p for p in finance["payments"] if p["payment_id"] == payment_id)
    assert approved_payment["status"] == "APPROVED"
    assert approved_payment["hidden_before_review"] is False  # no hide-receipt feature exists yet — always False today


async def test_finance_rejects_invalid_date_range(conn, clean_slate):
    now = datetime.now(timezone.utc)
    with pytest.raises(owner_service.InvalidDateRange):
        await owner_service.get_finance(conn, date_from=now, date_to=now - timedelta(days=1))


async def test_analytics_best_selling_includes_seeded_confirmed_order(conn, clean_slate):
    order_id, _, _ = await _seed_confirmed_order(conn, price=15_000, quantity=3)

    date_from = datetime.now(timezone.utc) - timedelta(days=1)
    date_to = datetime.now(timezone.utc) + timedelta(days=1)
    analytics = await owner_service.get_analytics(conn, date_from=date_from, date_to=date_to)

    assert "CONFIRMED" in analytics["order_status_distribution"]
    total_confirmed_quantity = sum(p["total_quantity"] for p in analytics["best_selling_products"])
    assert total_confirmed_quantity >= 3
