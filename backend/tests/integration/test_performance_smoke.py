"""Phase 08-FINAL — performance smoke test, explicitly NOT a load test.

**Load testing not production-representative.** This seeds a small, fixed,
documented dataset (a few hundred rows per table, not production scale —
no production traffic pattern or data volume exists to test against yet)
and asserts two things per critical query, both cheap to make
deterministic and CI-safe:

1. Each listing endpoint's *result set* stays bounded by its own `limit`
   even when the underlying table holds many more rows than that — the
   concrete, checkable form of "no unbounded listing / no full-table load."
2. Each query completes within a generous, non-flaky wall-clock bound on
   this fixed dataset — enough to catch a catastrophic regression (e.g. an
   accidental cross join or a per-row subquery loop = N+1), not a
   benchmark and not a throughput number. No number from this file should
   ever be reported as "production performance."

This is a smoke test, run once per suite execution — it does not simulate
concurrent users (see test_inventory_concurrent_adjust.py for genuine
concurrency testing of a different property: correctness under race, not
throughput).
"""
from __future__ import annotations

import time

import pytest
import pytest_asyncio

from app.domains.catalog import repository as catalog_repository
from app.domains.commerce.orders import repository as orders_repository
from app.domains.owner import repository as owner_repository
from app.domains.payments import repository as payments_repository
from tests.integration import factories

pytestmark = pytest.mark.asyncio

# Generous — this is a smoke bound to catch catastrophic regressions (an
# accidental N+1 turning a single query into hundreds), not a performance
# target. A healthy query against this dataset size runs in low
# single-digit milliseconds.
MAX_SECONDS = 2.0

_PRODUCT_COUNT = 250
_ORDER_COUNT = 60


@pytest_asyncio.fixture
async def seeded_catalog(conn, clean_slate):
    brand_id = await factories.make_brand(conn, name="PerfBrand")
    user_id = await factories.make_user(conn)
    variant_ids = []
    for i in range(_PRODUCT_COUNT):
        product_id = await factories.make_product(conn, brand_id=brand_id, name=f"Perf Product {i}")
        variant_id = await factories.make_variant(
            conn, product_id=product_id, sku=f"PERF-SKU-{i}", price=10_000 + i, stock_on_hand=20
        )
        variant_ids.append(variant_id)

    from app.domains.commerce.orders import service as orders_service

    for i in range(_ORDER_COUNT):
        order = await orders_service.create_order(
            conn, user_id=user_id,
            lines=[orders_service.CheckoutLine(variant_id=variant_ids[i % len(variant_ids)], quantity=1)],
        )
        await payments_repository.create_payment(conn, order_id=order["id"], amount=order["total_amount"])

    return {"user_id": user_id, "brand_id": brand_id}


async def _timed(coro):
    start = time.monotonic()
    result = await coro
    return result, time.monotonic() - start


async def test_catalog_listing_is_bounded_and_fast(conn, seeded_catalog):
    rows, elapsed = await _timed(catalog_repository.list_products(conn, limit=20))
    assert len(rows) == 20, "default-limit listing must stay bounded, not return all 250 rows"
    assert elapsed < MAX_SECONDS


async def test_catalog_search_is_bounded_and_fast(conn, seeded_catalog):
    rows, elapsed = await _timed(catalog_repository.search_products(conn, query="Perf", limit=20))
    assert len(rows) <= 20
    assert elapsed < MAX_SECONDS


async def test_order_listing_is_bounded_and_fast(conn, seeded_catalog):
    rows, elapsed = await _timed(orders_repository.list_all_orders(conn, limit=20))
    assert len(rows) == 20
    assert elapsed < MAX_SECONDS


async def test_payment_listing_is_bounded_and_fast(conn, seeded_catalog):
    rows, elapsed = await _timed(payments_repository.list_payments(conn, limit=20))
    assert len(rows) == 20
    assert elapsed < MAX_SECONDS


async def test_owner_dashboard_is_fast(conn, seeded_catalog):
    _, elapsed = await _timed(owner_repository.get_dashboard_summary(conn))
    assert elapsed < MAX_SECONDS


async def test_owner_finance_summary_is_fast(conn, seeded_catalog):
    import datetime

    date_from = datetime.date.today() - datetime.timedelta(days=30)
    date_to = datetime.date.today()
    _, elapsed = await _timed(owner_repository.get_finance_summary(conn, date_from=date_from, date_to=date_to))
    assert elapsed < MAX_SECONDS


async def test_owner_analytics_is_fast(conn, seeded_catalog):
    import datetime

    date_from = datetime.date.today() - datetime.timedelta(days=30)
    date_to = datetime.date.today()
    _, elapsed = await _timed(owner_repository.get_analytics(conn, date_from=date_from, date_to=date_to))
    assert elapsed < MAX_SECONDS


async def test_audit_log_listing_is_bounded_and_fast(conn, seeded_catalog):
    rows, elapsed = await _timed(owner_repository.list_audit_logs(conn, limit=20))
    assert len(rows) <= 20
    assert elapsed < MAX_SECONDS
