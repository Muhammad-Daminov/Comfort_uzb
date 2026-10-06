"""Phase 02 database verification.

Covers every item in docs/tasks/Phase-02-Database.md's Definition of Done
that can be checked structurally: table/index/constraint existence, and
that constraints actually reject the inputs the Master TZ says they must
reject (§12.6's spirit — this suite is the DB-layer slice of that; the
full 14-case suite is QA's, Phase-08).
"""

import os
import threading
import uuid

import psycopg
import pytest

P0_TABLES = {
    # IDENTITY
    "roles", "permissions", "role_permissions", "users",
    # CATALOG
    "brands", "colors", "products", "product_variants", "product_images",
    # VEHICLE
    "car_brands", "car_models", "car_generations", "product_compatibilities",
    # PRICING
    "discounts", "discount_targets",
    # SEARCH
    "search_aliases",
    # COMMERCE
    "carts", "cart_items", "orders", "order_items", "stock_reservations",
    # INVENTORY
    "inventory_movements",
    # PAYMENTS
    "payments", "payment_receipts",
    # COMMUNICATION (P0 slice)
    "notifications",
    # SECURITY
    "audit_logs", "idempotency_keys",
}


def _table_names(cur) -> set[str]:
    cur.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_type = 'BASE TABLE';"
    )
    return {row[0] for row in cur.fetchall()}


class TestSchemaShape:
    def test_all_p0_tables_exist(self, conn):
        with conn.cursor() as cur:
            existing = _table_names(cur)
        missing = P0_TABLES - existing
        assert not missing, f"P0 tables missing from schema: {missing}"

    def test_no_unexpected_p1_p3_tables_created_early(self, conn):
        """Phase-02 scope is P0 only — favorites, sell_requests,
        conversations etc. must not exist yet (docs/04_DOMAIN_ARCHITECTURE.md
        "Domain -> phase mapping"; Phase-02-Database.md "do not create
        unnecessary tables"). `refunds` was P3 when this list was written but
        ADR-017 (2026-09-29) deliberately promotes it: a paid order's
        cancellation must be able to reference an independently-tracked
        refund from P0 onward (v2 rebuild brief §11), so it is no longer
        deferred — see docs/adr/ADR-017-post-confirmation-cancellation-refund.md."""
        deferred = {
            "favorites", "stock_notifications", "conversations", "messages",
            "broadcasts", "broadcast_targets", "sell_requests",
            "sell_request_images",
        }
        with conn.cursor() as cur:
            existing = _table_names(cur)
        assert not (deferred & existing), (
            f"P1/P3 tables created ahead of schedule: {deferred & existing}"
        )

    def test_no_native_enum_types(self, conn):
        """§5.6: status fields are TEXT + CHECK, never native Postgres
        ENUM types — evolving the allowed list must never require ALTER
        TYPE."""
        with conn.cursor() as cur:
            cur.execute("SELECT typname FROM pg_type WHERE typtype = 'e';")
            enums = cur.fetchall()
        assert enums == [], f"Native enum types found (forbidden by §5.6): {enums}"

    def test_money_columns_are_bigint(self, conn):
        """ADR-3: every money column is BIGINT, never FLOAT/REAL/DOUBLE PRECISION."""
        money_columns = [
            ("product_variants", "price"),
            ("product_variants", "required_initial_payment"),
            ("discounts", "value"),
            ("orders", "total_amount"),
            ("orders", "required_initial_amount"),
            ("orders", "paid_amount"),
            ("orders", "remaining_amount"),
            ("order_items", "unit_price"),
            ("order_items", "discount_amount"),
            ("order_items", "line_total"),
            ("order_items", "required_initial_payment"),
            ("payments", "amount"),
        ]
        with conn.cursor() as cur:
            for table, column in money_columns:
                cur.execute(
                    "SELECT data_type FROM information_schema.columns "
                    "WHERE table_name = %s AND column_name = %s;",
                    (table, column),
                )
                row = cur.fetchone()
                assert row is not None, f"{table}.{column} does not exist"
                assert row[0] == "bigint", (
                    f"{table}.{column} is {row[0]}, must be bigint (ADR-3)"
                )

    def test_no_floating_point_columns_anywhere(self, conn):
        """Blanket check: no `real`/`double precision` column exists in the
        whole schema — a stronger guarantee than checking only the known
        money columns above."""
        with conn.cursor() as cur:
            cur.execute(
                "SELECT table_name, column_name, data_type FROM information_schema.columns "
                "WHERE table_schema = 'public' AND data_type IN ('real', 'double precision');"
            )
            offenders = cur.fetchall()
        assert offenders == [], f"Floating-point columns found (forbidden by ADR-3): {offenders}"


class TestConstraints:
    def _fresh_product_variant(self, cur, **overrides):
        cur.execute("INSERT INTO brands (name) VALUES (%s) RETURNING id;", (f"B-{uuid.uuid4()}",))
        brand_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO products (name, brand_id) VALUES (%s, %s) RETURNING id;",
            (f"P-{uuid.uuid4()}", brand_id),
        )
        return cur.fetchone()[0]

    def test_single_owner_enforced(self, autocommit_conn):
        with autocommit_conn.cursor() as cur:
            with pytest.raises(psycopg.errors.UniqueViolation):
                cur.execute(
                    "INSERT INTO users (telegram_id, role, status) VALUES (%s, 'OWNER', 'ACTIVE');",
                    (999999001,),
                )

    def test_negative_price_rejected(self, autocommit_conn):
        with autocommit_conn.cursor() as cur:
            product_id = self._fresh_product_variant(cur)
            with pytest.raises(psycopg.errors.CheckViolation):
                cur.execute(
                    "INSERT INTO product_variants (product_id, sku, price) VALUES (%s, %s, -1);",
                    (product_id, f"SKU-{uuid.uuid4()}"),
                )

    def test_stock_reserved_cannot_exceed_on_hand(self, autocommit_conn):
        with autocommit_conn.cursor() as cur:
            product_id = self._fresh_product_variant(cur)
            with pytest.raises(psycopg.errors.CheckViolation):
                cur.execute(
                    "INSERT INTO product_variants "
                    "(product_id, sku, price, stock_on_hand, stock_reserved) "
                    "VALUES (%s, %s, 1000, 5, 10);",
                    (product_id, f"SKU-{uuid.uuid4()}"),
                )

    def test_valid_variant_insert_succeeds(self, autocommit_conn):
        with autocommit_conn.cursor() as cur:
            product_id = self._fresh_product_variant(cur)
            cur.execute(
                "INSERT INTO product_variants "
                "(product_id, sku, price, stock_on_hand, stock_reserved) "
                "VALUES (%s, %s, 100000, 10, 2) RETURNING id;",
                (product_id, f"SKU-{uuid.uuid4()}"),
            )
            assert cur.fetchone() is not None

    def test_order_cancellation_requires_reason(self, autocommit_conn):
        with autocommit_conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (telegram_id, role) VALUES (%s, 'USER') RETURNING id;",
                (uuid.uuid4().int % 2_000_000_000,),
            )
            user_id = cur.fetchone()[0]
            with pytest.raises(psycopg.errors.CheckViolation):
                cur.execute(
                    "INSERT INTO orders (order_number, user_id, status) VALUES (%s, %s, 'CANCELLED');",
                    (f"CU-{uuid.uuid4().hex[:6].upper()}", user_id),
                )

    def test_order_cancellation_with_short_reason_rejected(self, autocommit_conn):
        with autocommit_conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (telegram_id, role) VALUES (%s, 'USER') RETURNING id;",
                (uuid.uuid4().int % 2_000_000_000,),
            )
            user_id = cur.fetchone()[0]
            with pytest.raises(psycopg.errors.CheckViolation):
                cur.execute(
                    "INSERT INTO orders (order_number, user_id, status, cancellation_reason) "
                    "VALUES (%s, %s, 'CANCELLED', 'too short');",
                    (f"CU-{uuid.uuid4().hex[:6].upper()}", user_id),
                )

    def test_order_cancellation_with_valid_reason_succeeds(self, autocommit_conn):
        with autocommit_conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (telegram_id, role) VALUES (%s, 'USER') RETURNING id;",
                (uuid.uuid4().int % 2_000_000_000,),
            )
            user_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO orders (order_number, user_id, status, cancellation_reason) "
                "VALUES (%s, %s, 'CANCELLED', 'Customer changed their mind') RETURNING id;",
                (f"CU-{uuid.uuid4().hex[:6].upper()}", user_id),
            )
            assert cur.fetchone() is not None

    def test_inventory_movement_quantity_math_enforced(self, autocommit_conn):
        with autocommit_conn.cursor() as cur:
            product_id = self._fresh_product_variant(cur)
            cur.execute(
                "INSERT INTO product_variants (product_id, sku, price) VALUES (%s, %s, 1000) RETURNING id;",
                (product_id, f"SKU-{uuid.uuid4()}"),
            )
            variant_id = cur.fetchone()[0]
            with pytest.raises(psycopg.errors.CheckViolation):
                cur.execute(
                    "INSERT INTO inventory_movements "
                    "(variant_id, movement_type, quantity_change, quantity_before, quantity_after) "
                    "VALUES (%s, 'IN', 5, 10, 999);",  # 10 + 5 != 999
                    (variant_id,),
                )

    def test_idempotency_key_is_unique_pk(self, autocommit_conn):
        with autocommit_conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (telegram_id, role) VALUES (%s, 'USER') RETURNING id;",
                (uuid.uuid4().int % 2_000_000_000,),
            )
            user_id = cur.fetchone()[0]
            key = str(uuid.uuid4())
            cur.execute(
                "INSERT INTO idempotency_keys (key, endpoint, user_id, request_hash) "
                "VALUES (%s, '/orders', %s, 'hash1');",
                (key, user_id),
            )
            with pytest.raises(psycopg.errors.UniqueViolation):
                cur.execute(
                    "INSERT INTO idempotency_keys (key, endpoint, user_id, request_hash) "
                    "VALUES (%s, '/orders', %s, 'hash2');",
                    (key, user_id),
                )


class TestAuditAppendOnly:
    """Append-only is enforced by two independent layers (§12.2/§12.3):
    the REVOKE UPDATE, DELETE grant denies comfort_app the privilege
    outright, and the `prevent_audit_mutation()` trigger raises even for a
    role that *does* hold the privilege (e.g. if a grant were ever
    misconfigured). `autocommit_conn` connects as comfort_app, so the
    grant layer is what actually fires here — InsufficientPrivilege — and
    that is what a test connecting as comfort_app must assert; asserting
    RaiseException here would be asserting a layer this connection can
    never reach. Both exception types are accepted so the test keeps
    passing regardless of which layer catches the mutation."""

    def test_audit_log_update_rejected(self, autocommit_conn):
        with autocommit_conn.cursor() as cur:
            cur.execute(
                "INSERT INTO audit_logs (action, entity_type) VALUES ('test.append_only', 'test') RETURNING id;"
            )
            row_id = cur.fetchone()[0]
            with pytest.raises((psycopg.errors.RaiseException, psycopg.errors.InsufficientPrivilege)):
                cur.execute("UPDATE audit_logs SET action = 'changed' WHERE id = %s;", (row_id,))

    def test_audit_log_delete_rejected(self, autocommit_conn):
        with autocommit_conn.cursor() as cur:
            cur.execute(
                "INSERT INTO audit_logs (action, entity_type) VALUES ('test.append_only_2', 'test') RETURNING id;"
            )
            row_id = cur.fetchone()[0]
            with pytest.raises((psycopg.errors.RaiseException, psycopg.errors.InsufficientPrivilege)):
                cur.execute("DELETE FROM audit_logs WHERE id = %s;", (row_id,))

    def test_audit_log_insert_allowed(self, autocommit_conn):
        with autocommit_conn.cursor() as cur:
            cur.execute(
                "INSERT INTO audit_logs (action, entity_type) VALUES ('test.insert_ok', 'test') RETURNING id;"
            )
            assert cur.fetchone() is not None


class TestReservationRelease:
    """Regression test for the Phase 02 acceptance audit finding
    "reservation double-release safety requirement" — see
    AGENTS/backend-commerce.md's "Mandatory release pattern" for the full
    writeup. The schema has no CHECK constraint that catches a
    double-release (0 is a valid `stock_reserved` value), so this proves
    the *documented application pattern* — guarded
    `WHERE released_at IS NULL` + rowcount check — is what actually makes
    it safe, under a real concurrent race (two threads, two separate
    connections), not just sequential simulation.
    """

    TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

    def _setup_two_reservations(self, cur):
        """One variant with two independent active reservations, each
        holding part of stock_reserved — mirrors the exact audit scenario
        (on_hand=10, reserved=4, order A holds 2, order B holds 2)."""
        cur.execute("INSERT INTO brands (name) VALUES (%s) RETURNING id;", (f"B-{uuid.uuid4()}",))
        brand_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO products (name, brand_id) VALUES (%s, %s) RETURNING id;",
            (f"P-{uuid.uuid4()}", brand_id),
        )
        product_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO product_variants (product_id, sku, price, stock_on_hand, stock_reserved) "
            "VALUES (%s, %s, 1000, 10, 4) RETURNING id;",
            (product_id, f"SKU-{uuid.uuid4()}"),
        )
        variant_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO users (telegram_id, role) VALUES (%s, 'USER') RETURNING id;",
            (uuid.uuid4().int % 2_000_000_000,),
        )
        user_id = cur.fetchone()[0]

        reservation_ids = []
        for suffix in ("A", "B"):
            cur.execute(
                "INSERT INTO orders (order_number, user_id, status) VALUES (%s, %s, 'CREATED') RETURNING id;",
                (f"CU-{uuid.uuid4().hex[:5].upper()}{suffix}", user_id),
            )
            order_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO stock_reservations (order_id, variant_id, quantity, expires_at) "
                "VALUES (%s, %s, 2, now() + interval '1 day') RETURNING id;",
                (order_id, variant_id),
            )
            reservation_ids.append(cur.fetchone()[0])
        return variant_id, reservation_ids[0], reservation_ids[1]

    @staticmethod
    def _guarded_release(dsn, reservation_id, variant_id, quantity, barrier, results, index):
        """The pattern mandated in AGENTS/backend-commerce.md: guarded
        UPDATE, rowcount check, conditional decrement — exactly what
        comfort-reservation-expiry and order-cancellation's release path
        must both do."""
        with psycopg.connect(dsn, autocommit=False) as conn, conn.cursor() as cur:
            barrier.wait()  # maximize the chance both threads overlap
            cur.execute(
                "UPDATE stock_reservations SET released_at = now() "
                "WHERE id = %s AND released_at IS NULL;",
                (reservation_id,),
            )
            affected = cur.rowcount
            if affected == 1:
                cur.execute(
                    "UPDATE product_variants SET stock_reserved = stock_reserved - %s WHERE id = %s;",
                    (quantity, variant_id),
                )
            conn.commit()
        results[index] = affected

    @pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL not set")
    def test_concurrent_double_release_of_same_reservation_is_a_noop(self, autocommit_conn):
        """Two threads race to release the SAME reservation (simulating a
        worker retry / duplicate run). With the guarded pattern, exactly
        one must actually decrement stock; the other must observe
        rowcount=0 and skip — final stock_reserved must reflect exactly
        one release, and the OTHER reservation (untouched) must be
        unaffected."""
        with autocommit_conn.cursor() as cur:
            variant_id, res_a, res_b = self._setup_two_reservations(cur)

        barrier = threading.Barrier(2)
        results = [None, None]
        threads = [
            threading.Thread(
                target=self._guarded_release,
                args=(self.TEST_DATABASE_URL, res_a, variant_id, 2, barrier, results, i),
            )
            for i in range(2)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Exactly one of the two concurrent attempts actually released it.
        assert sorted(results) == [0, 1], (
            f"expected exactly one release to succeed (rowcount 1) and the "
            f"other to be a no-op (rowcount 0), got {results}"
        )

        with autocommit_conn.cursor() as cur:
            cur.execute("SELECT stock_reserved FROM product_variants WHERE id = %s;", (variant_id,))
            # Started at 4 (order A's 2 + order B's 2). Only order A was
            # released (exactly once, despite two concurrent attempts) —
            # order B's 2 units must still be held.
            assert cur.fetchone()[0] == 2, (
                "stock_reserved was decremented more than once for a single "
                "reservation release — the guarded pattern did not prevent "
                "the double-release this test targets"
            )

            cur.execute(
                "SELECT released_at IS NOT NULL FROM stock_reservations WHERE id = %s;", (res_b,)
            )
            assert cur.fetchone()[0] is False, (
                "order B's untouched reservation was incorrectly marked released"
            )

    def test_sequential_double_release_is_a_noop_without_live_db_dependency(self, autocommit_conn):
        """Same guarantee, exercised sequentially (no threading) so this
        specific assertion doesn't depend on true concurrency to catch a
        regression — a belt-and-suspenders companion to the concurrent
        test above."""
        with autocommit_conn.cursor() as cur:
            variant_id, res_a, _res_b = self._setup_two_reservations(cur)

            cur.execute(
                "UPDATE stock_reservations SET released_at = now() "
                "WHERE id = %s AND released_at IS NULL;",
                (res_a,),
            )
            assert cur.rowcount == 1
            cur.execute(
                "UPDATE product_variants SET stock_reserved = stock_reserved - 2 WHERE id = %s;",
                (variant_id,),
            )

            # Naive second attempt at releasing the SAME reservation again.
            cur.execute(
                "UPDATE stock_reservations SET released_at = now() "
                "WHERE id = %s AND released_at IS NULL;",
                (res_a,),
            )
            assert cur.rowcount == 0, "second release of an already-released reservation must be a no-op"
            # Per the mandated pattern: rowcount 0 means the stock UPDATE
            # must NOT run. (Not executing it here IS the correct behavior
            # under test — asserting the guard rather than the absence of
            # a decrement, since there's nothing to run.)

            cur.execute("SELECT stock_reserved FROM product_variants WHERE id = %s;", (variant_id,))
            assert cur.fetchone()[0] == 2


class TestIndexes:
    """Spot-checks against the §18.2 index list (REQ-PERF-003)."""

    @pytest.mark.parametrize(
        "table,indexdef_substring",
        [
            ("users", "telegram_id"),
            ("products", "search_text"),
            ("product_variants", "sku"),
            ("product_images", "is_primary"),
            ("orders", "status"),
            ("order_items", "order_id"),
            ("stock_reservations", "expires_at"),
            ("payments", "status"),
            ("payment_receipts", "retention_until"),
            ("notifications", "read_at"),
            ("audit_logs", "entity_type"),
        ],
    )
    def test_index_exists(self, conn, table, indexdef_substring):
        with conn.cursor() as cur:
            cur.execute(
                "SELECT indexdef FROM pg_indexes WHERE tablename = %s;", (table,)
            )
            defs = [row[0] for row in cur.fetchall()]
        assert any(indexdef_substring in d for d in defs), (
            f"No index on {table} referencing '{indexdef_substring}' "
            f"(required by §18.2). Found: {defs}"
        )

    def test_trigram_search_index_exists(self, conn):
        with conn.cursor() as cur:
            cur.execute(
                "SELECT indexname FROM pg_indexes WHERE indexname = 'idx_products_search_trgm';"
            )
            assert cur.fetchone() is not None


class TestRolePrivileges:
    """Requires provision_roles.sql to already have been run against
    TEST_DATABASE_URL's database with the credentials below (see
    docs/tasks/Phase-02-Database.md). Skipped independently of the rest of
    this file if those env vars aren't set, since most CI/dev setups won't
    have provisioned roles on a throwaway DB by default."""

    APP_URL = os.environ.get("TEST_DATABASE_URL_AS_APP")
    BACKUP_URL = os.environ.get("TEST_DATABASE_URL_AS_BACKUP")

    @pytest.mark.skipif(not APP_URL, reason="TEST_DATABASE_URL_AS_APP not set")
    def test_comfort_app_cannot_delete(self):
        with psycopg.connect(self.APP_URL, autocommit=True) as c, c.cursor() as cur:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                cur.execute("DELETE FROM roles WHERE id = -1;")

    @pytest.mark.skipif(not APP_URL, reason="TEST_DATABASE_URL_AS_APP not set")
    def test_comfort_app_cannot_create_tables(self):
        with psycopg.connect(self.APP_URL, autocommit=True) as c, c.cursor() as cur:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                cur.execute("CREATE TABLE hack (id int);")

    @pytest.mark.skipif(not BACKUP_URL, reason="TEST_DATABASE_URL_AS_BACKUP not set")
    def test_comfort_backup_cannot_write(self):
        with psycopg.connect(self.BACKUP_URL, autocommit=True) as c, c.cursor() as cur:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                cur.execute("INSERT INTO roles (name) VALUES ('HACK');")
