"""Fixtures for Phase 03 integration tests. Require a real, disposable
PostgreSQL 16 instance with roles provisioned via `db/provision_roles.sql`
and `alembic upgrade head` already applied — same convention as
`tests/db/conftest.py`. Point `TEST_DATABASE_URL` at a connection string
usable as `comfort_app` (the role the application actually runs as in
production); tests that specifically need superuser/dev-owner access use
`SUPERUSER_DATABASE_URL` (matches `tests/db`'s existing pattern).

Tests here exercise the asyncpg-based application code (ADR-015) directly,
not through HTTP — Service-layer integration, not Router-layer HTTP tests
(no ASGI test client is used; the Router layer is thin enough that its
correctness is covered by the unit tests plus manual verification, per the
plan's Verification section).
"""
from __future__ import annotations

import os

import asyncpg
import pytest
import pytest_asyncio

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
SUPERUSER_DATABASE_URL = os.environ.get("SUPERUSER_DATABASE_URL")

# `pytestmark` is a no-op inside a conftest (it only marks the module it
# is defined in, and a conftest collects no tests) — without this hook the
# suites *errored* in their fixtures when the env var was unset instead of
# skipping as documented.
_SKIP_MARK = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason=(
        "TEST_DATABASE_URL not set — point it at a disposable Postgres DB, "
        "provisioned via db/provision_roles.sql and migrated with "
        "`alembic upgrade head` as comfort_migrate, to run Phase 03 "
        "integration tests. Connect as comfort_app (asyncpg DSN, e.g. "
        "postgresql://comfort_app:<pw>@/<db>?host=<socket_dir>)."
    ),
)


@pytest_asyncio.fixture
async def conn():
    connection = await asyncpg.connect(TEST_DATABASE_URL)
    try:
        yield connection
    finally:
        await connection.close()


@pytest_asyncio.fixture
async def pool():
    created_pool = await asyncpg.create_pool(dsn=TEST_DATABASE_URL, min_size=1, max_size=5)
    try:
        yield created_pool
    finally:
        await created_pool.close()


@pytest_asyncio.fixture
async def clean_slate():
    """Truncates the P0 transactional tables between tests. Runs via
    SUPERUSER_DATABASE_URL, not the `conn`/`pool` fixtures' comfort_app
    connection — comfort_app deliberately has no DELETE/DDL/TRUNCATE grant
    (§12.2), so cleanup needs a separate, more-privileged connection, same
    as tests/db's existing pattern of using different roles for different
    purposes. Each test still exercises the actual application code through
    the `conn`/`pool` fixtures as comfort_app; only the *cleanup* step uses
    elevated privilege."""
    yield
    admin_dsn = SUPERUSER_DATABASE_URL or TEST_DATABASE_URL
    admin_conn = await asyncpg.connect(admin_dsn)
    try:
        # Deliberately does NOT truncate `users` — migration 0002's ADR-11
        # OWNER seed row lives there, and tests/db's own suite (run against
        # the same disposable database in CI) depends on it still existing.
        # Every test in this suite already uses distinct telegram_id values,
        # so leaving `users` alone doesn't reintroduce cross-test coupling.
        await admin_conn.execute(
            """
            TRUNCATE TABLE
                audit_logs, idempotency_keys, inventory_movements, stock_reservations,
                order_items, orders, payment_receipts, payments, cart_items, carts,
                brands, products, product_variants, notifications, store_settings
            RESTART IDENTITY CASCADE
            """
        )
    finally:
        await admin_conn.close()


def pytest_collection_modifyitems(items):
    for item in items:
        item.add_marker(_SKIP_MARK)
