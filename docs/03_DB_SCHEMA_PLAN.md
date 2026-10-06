# 03 — Database Schema Plan

**Purpose:** Implementation record of the Phase 02 database layer — what was built, why each non-obvious decision was made, and how to verify it. This is `database`'s deliverable per `docs/tasks/Phase-02-Database.md`.
**Owner:** database
**Last updated:** 2026-08-17
**Dependencies:** [00_MASTER_TZ.md](00_MASTER_TZ.md), [01_REQUIREMENTS_MAP.md](01_REQUIREMENTS_MAP.md), [04_DOMAIN_ARCHITECTURE.md](04_DOMAIN_ARCHITECTURE.md), [tasks/Phase-02-Database.md](tasks/Phase-02-Database.md), `docs/adr/ADR-003` through `ADR-014`

This document records decisions and rationale. For the literal schema, read the migrations themselves in `backend/alembic/versions/` — they're written to be self-explanatory, with a module docstring per file citing the TZ section/ADR each table comes from and calling out every place this implementation had to make a judgment call beyond the literal TZ text.

## Where the code lives

```
backend/
  alembic.ini
  alembic/
    env.py                      -- reads DATABASE_URL from env, never hardcoded (REQ-OPS-008)
    versions/
      0001_identity.py          -- roles, permissions, role_permissions, users (+ seed)
      0002_owner_bootstrap.py   -- ADR-11 OWNER seed from OWNER_TELEGRAM_ID
      0003_catalog.py           -- brands, colors, products, product_variants, product_images
      0004_vehicle.py           -- car_brands, car_models, car_generations, product_compatibilities
      0005_pricing.py           -- discounts, discount_targets
      0006_search.py            -- pg_trgm, search_text index, search_aliases
      0007_commerce.py          -- carts, cart_items, orders, order_items, stock_reservations
      0008_inventory.py         -- inventory_movements
      0009_payments.py          -- payments, payment_receipts
      0010_communication_p0.py  -- notifications (P0 slice only)
      0011_security.py          -- audit_logs (+ append-only trigger), idempotency_keys
      0012_seed_search_aliases.py -- ADR-8's own worked examples
  db/
    provision_roles.sql         -- comfort_app/comfort_migrate/comfort_backup DDL (§12.2)
  tests/db/
    conftest.py
    test_schema.py              -- 36 tests (incl. reservation double-release regression tests), run against a real Postgres 16
    test_migration_role_e2e.py  -- genuinely runs provision_roles.sql + `alembic upgrade head` AS comfort_migrate against a fresh disposable DB (not a superuser)
  requirements.txt
```

## Table inventory (27 P0 tables, by domain)

Matches `docs/04_DOMAIN_ARCHITECTURE.md`'s "Domain → phase mapping" exactly. TZ's own "~20 tables" (§4) is a rough estimate; the actual literal P0 count across the 11 P0-shipping domains is 27 — recounted here for precision, not a scope change.

| Domain | Tables | Migration |
|---|---|---|
| IDENTITY | `roles`, `permissions`, `role_permissions`, `users` | 0001 |
| CATALOG | `brands`, `colors`, `products`, `product_variants`, `product_images` | 0003 |
| VEHICLE | `car_brands`, `car_models`, `car_generations`, `product_compatibilities` | 0004 |
| PRICING | `discounts`, `discount_targets` | 0005 |
| SEARCH | `search_aliases` (+ `products.search_text` trgm index) | 0006 |
| COMMERCE | `carts`, `cart_items`, `orders`, `order_items`, `stock_reservations` | 0007 |
| INVENTORY | `inventory_movements` | 0008 |
| PAYMENTS | `payments`, `payment_receipts` | 0009 |
| COMMUNICATION (P0 slice) | `notifications` | 0010 |
| SECURITY | `audit_logs`, `idempotency_keys` | 0011 |

**Deliberately not created in Phase 02** (P1/P3, per `04_DOMAIN_ARCHITECTURE.md`): `favorites`, `stock_notifications` (ENGAGEMENT), `conversations`, `messages`, `broadcasts`, `broadcast_targets` (COMMUNICATION beyond notifications), `sell_requests`, `sell_request_images` (MARKETPLACE), `refunds` (PAYMENTS/P3). `tests/db/test_schema.py::test_no_unexpected_p1_p3_tables_created_early` asserts this stays true. `products.source_sell_request_id` (ADR-10) is likewise deferred — see migration 0003's docstring — added by ALTER TABLE when MARKETPLACE ships.

## Where this implementation had to decide something the TZ leaves implicit

Every one of these is called out in the relevant migration's module docstring too; collected here for a single-page view. None of them change a business rule — they're schema-shape decisions the TZ's prose doesn't pin down.

1. **`users.role` is `TEXT REFERENCES roles(name)`**, not `role_id BIGINT REFERENCES roles(id)` — preserves ADR-11's literal `INSERT ... (telegram_id, role, status) VALUES (...)` example while still satisfying §3's "roles must be data, not hardcoded" requirement via the FK.
2. **`users.status` values** (`ACTIVE`/`DEACTIVATED`) — `ACTIVE` is confirmed by ADR-11's seed SQL; `DEACTIVATED` is inferred from the §12.6 test case "deactivated admin acts → 403." Not enumerated anywhere else in the TZ.
3. **Permission keys** are more granular than §3's table header (e.g. `products.create`/`products.update`/`products.archive` instead of one combined key) — each independently grantable, matching §3's intent.
4. **`brands`/`colors` as normalized lookup tables** (REQ-CAT-005, added by the Phase 0 review) rather than free-text columns — required so `discount_targets(target_type='BRAND', target_id)` can reference a stable ID.
5. **`carts`: one row per user** (`UNIQUE(user_id)`) — inferred from `GET /cart` being singular/parameterless in §13.4; TZ never describes a multi-cart scenario.
6. **Stock quantities are `INTEGER`, money is `BIGINT`** — TZ only mandates a type for money (ADR-3); INTEGER's ~2.1B range is not a realistic constraint for one store's stock.
7. **`notifications` columns beyond `user_id`/`read_at`/`created_at`** (`type`, `title`, `body`, `entity_type`, `entity_id`) — only those three columns come from §18.2's index; the rest are implementation necessities for a notification to carry content.
8. **No DB-level state-machine enforcement** for `orders.status` transitions or `payments.status`'s one-way `APPROVED` rule — TZ explicitly places the order transition table "kodda" (in code, §8.1), and a CHECK constraint can only validate a single row, not a transition; enforcing the full graph would need a stateful trigger the TZ doesn't ask for. Enforced by the Service layer's guarded `UPDATE ... WHERE status = <expected>` pattern instead (Phase 03, `backend-commerce`).
9. **No append-only trigger on `inventory_movements`**, unlike `audit_logs` — §12.3's trigger requirement is explicitly scoped to `audit_logs`; `inventory_movements` is described as append-only in prose (§9) without the same explicit DB-trigger mandate.
10. **Max-5-images-per-product** (§6.3) is not DB-enforced — a per-row CHECK can't express a per-group count; would need a trigger not explicitly requested. The one-primary-image-per-product rule from the same section IS DB-enforced (a simple partial unique index), since it's a single-row invariant.
11. **`product_compatibilities` has no `UNIQUE(product_id, generation_id)`** — deliberately, since a product can legitimately have multiple compatibility rows for the same generation with different year sub-ranges (§6.4's `year_from`/`year_to`/`note` fields exist for exactly this).

## Concurrency correctness notes (found by the Phase 02 acceptance audit)

- **Reservation double-release.** `stock_reserved >= 0` is the only CHECK guarding `stock_reservations`/`product_variants`, and it does not catch a reservation being released twice: if a variant has multiple active reservations, double-releasing one of them silently steals `stock_reserved` headroom from an unrelated, still-active reservation without ever going negative — live-reproduced during the audit (`stock_on_hand=10, stock_reserved=4`, two reservations of 2 each; naively double-releasing one drove `stock_reserved` to 0 while the other reservation still showed `released_at IS NULL`). This is not a schema defect to fix here — no CHECK constraint can express "this specific row was already processed" without becoming a stateful trigger the TZ doesn't ask for (the same reasoning as item 8 above) — it's a mandatory application-layer pattern, now documented in `AGENTS/backend-commerce.md` ("Mandatory release pattern") for Phase 03 to implement: guarded `UPDATE ... WHERE released_at IS NULL`, then only decrement `stock_reserved` if the row count was 1. Regression-tested at the DB layer under true concurrent execution in `tests/db/test_schema.py::TestReservationRelease` — that test proves the *pattern* is safe, not that Phase 03's eventual Python code will follow it; Phase 03/08 needs its own Service-layer test for that.

## Constraints implemented at the DB layer (vs. left to the Service layer)

Per Phase-02's brief ("prefer database-enforced integrity where appropriate... do not encode complex application business workflows into database constraints unless the TZ explicitly requires it"), every table's module docstring states which category each non-obvious constraint falls into. Summary of the DB-enforced ones that map directly to a named requirement:

- `CHECK (price >= 0)`, no float columns anywhere (ADR-3) — verified by `test_money_columns_are_bigint`, `test_no_floating_point_columns_anywhere`.
- `stock_reserved <= stock_on_hand`, both `>= 0` (ADR-6) — verified by `test_stock_reserved_cannot_exceed_on_hand`.
- Exactly one `OWNER` (ADR-11, partial unique index) — verified by `test_single_owner_enforced`.
- SKU/primary-image/phone/single-OWNER soft-delete + UNIQUE pattern (§5.4).
- `cancellation_reason` mandatory + ≥10 chars whenever `status = 'CANCELLED'` (§8.4/REQ-BIZ-013) — verified by `test_order_cancellation_requires_reason` and `test_order_cancellation_with_short_reason_rejected`.
- `orders.remaining_amount = total_amount - paid_amount` (ADR-5).
- `inventory_movements.quantity_after = quantity_before + quantity_change` (§9) — verified by `test_inventory_movement_quantity_math_enforced`.
- `audit_logs` append-only via trigger, copied verbatim from §12.3 — verified by `test_audit_log_update_rejected`/`test_audit_log_delete_rejected`/`test_audit_log_insert_allowed`.
- `idempotency_keys.key` as `PRIMARY KEY` (ADR-7) — verified by `test_idempotency_key_is_unique_pk`.
- No native Postgres `ENUM` types anywhere (§5.6) — verified by `test_no_native_enum_types`.

**Architectural rule honored (Phase 0 review, "audit transaction safety"):** `audit_logs` has no separate write path or queueing mechanism — it's a plain table with one `INSERT` statement type. This is deliberate: it means any caller (e.g. `backend-commerce`'s order-confirm) that includes the audit `INSERT` in the same transaction as its other statements gets atomicity for free from Postgres itself, with nothing in the schema that could tempt a fire-and-forget implementation. See migration `0011_security`'s docstring.

## Indexes

Every index named in Master TZ §18.2 exists — see each migration's `CREATE INDEX` statements, and `tests/db/test_schema.py::TestIndexes` for a spot-check covering one index per table plus the `pg_trgm` search index. A few indexes beyond §18.2's literal list were added where a query pattern the TZ describes in prose would otherwise force a sequential scan (each documented inline in its migration): `idempotency_keys(created_at)` for the 24h-cleanup worker's TTL scan (REQ-WRK-004), and a couple of dedup-guard unique indexes on vehicle lookup tables.

## Roles & grants (§12.2)

`backend/db/provision_roles.sql` — owned and authored by `database` (per the Phase 0 review's ownership correction; `security` defines the least-privilege policy it implements, `devops` owns only `pg_hba.conf`/`postgresql.conf` runtime config, not this file). Implements `comfort_app` (SELECT/INSERT/UPDATE, no DELETE, no DDL, narrower still on `audit_logs`), `comfort_migrate` (full DDL, Alembic-only), `comfort_backup` (SELECT-only), plus `ALTER DEFAULT PRIVILEGES` so every future migration's new tables inherit the same grants automatically.

**Not an Alembic migration, deliberately:** `comfort_migrate` is the role Alembic itself connects as for every migration (§12.2), which means it can't be the thing that creates itself — this script runs once, by a Postgres superuser, during initial server provisioning, before the first `alembic upgrade head`. See the file's own header comment for the exact invocation.

**Real bugs this caught, all found by actually running the script and migrations, not by reading them:**

- **`psql` variable interpolation inside `DO $$ ... $$`.** An earlier draft used `:'variable'` interpolation inside a dollar-quoted block to conditionally `CREATE ROLE`. That fails silently with a syntax error — psql's variable substitution doesn't reach inside dollar-quoted blocks. Fixed using `SELECT ... WHERE NOT EXISTS (...) \gexec`, which keeps the variable substitution in a plain statement psql actually rewrites.
- **Missing database-level `CREATE` for `comfort_migrate` (Phase 02 acceptance audit, CRITICAL).** The original script granted `comfort_migrate` only `GRANT ALL ON SCHEMA public` — schema-level. `CREATE EXTENSION pg_trgm` (migration `0006_search`) requires database-level `CREATE`, which schema-level grants don't cover. Running `alembic upgrade head` genuinely as `comfort_migrate` (not a superuser) failed at 0006 with `permission denied to create extension "pg_trgm"`, and because `env.py` wraps the whole run in one transaction, it rolled back migrations 0001–0005 too — a clean failure, but `head` was unreachable via the only role the design permits for migrations. Fixed with `SELECT format('GRANT CREATE ON DATABASE %I TO comfort_migrate;', current_database()) \gexec` — uses the database the script is already connected to (per its own documented `psql ... -d <db> ...` invocation), no hardcoded name.
- **`audit_logs` REVOKE silently no-op'ing (Phase 02 acceptance audit, HIGH).** The script is documented to run *before* the first migration, so its `audit_logs`-specific `REVOKE UPDATE, DELETE ... FROM comfort_app` referenced a table that didn't exist yet. psql doesn't abort a script on a statement error by default, so this failed silently and never reapplied — `comfort_app` ended up with `UPDATE` on `audit_logs` via the blanket `ALTER DEFAULT PRIVILEGES` grant, contradicting §12.2. **Root-caused, not just patched:** the authoritative narrowing now lives in migration `0011_security` itself — since `comfort_migrate` creates `audit_logs`, it owns the table and can `REVOKE`/`GRANT` on it regardless of what order this script ran in, guarded by `IF EXISTS (... pg_roles ...)` so local dev without any roles provisioned still migrates cleanly. This script's own `audit_logs` block is now a defensive, `\gexec`-guarded reapplication (for the case the script is re-run later, e.g. to rotate a password) — it no longer errors, but it's no longer load-bearing for correctness either.

All three found and fixed by running the actual script and the actual migration chain against a real, disposable Postgres 16 cluster — see "Verification strategy" below, which now explicitly distinguishes verification that used a superuser role from verification that genuinely ran as `comfort_migrate`.

## RLS

Not introduced. TZ's §12.2 rationale (Postgres reachable only from `localhost` by the backend, unlike Supabase's internet-facing REST API) is preserved verbatim in `provision_roles.sql`'s closing comment, so a future reader doesn't have to go back to the TZ to find out why RLS is absent.

## Migration strategy

- One migration per business domain, in dependency order (IDENTITY → CATALOG → VEHICLE → PRICING → SEARCH → COMMERCE → INVENTORY → PAYMENTS → COMMUNICATION(P0) → SECURITY), plus a dedicated `0002_owner_bootstrap` kept separate from `0001_identity`'s schema so schema and data changes are never mixed in one migration, and a dedicated `0012_seed_search_aliases`.
- Every migration is raw SQL via `op.execute()` — no ORM model layer, no autogenerate. This is deliberate (see `alembic/env.py`'s docstring): it means there's no risk of drift between "what the models say" and "what's actually in the DB," and it keeps this phase from making an implicit call on OPEN-3 (asyncpg vs. SQLAlchemy Core) — SQLAlchemy is present only as Alembic's own migration-runtime dependency, not as a schema-definition or query-building layer the app is committed to.
- Every migration has a real `downgrade()` — verified by actually running `alembic downgrade base` end-to-end (see below), not just written and assumed correct.
- `DATABASE_URL` is read from the environment only, never hardcoded, so dev and prod (REQ-OPS-008) can't collide.

## Seed strategy

Only two things are seeded, both explicitly evidenced by the TZ text (Phase-02's "do not invent production catalog data" rule):
1. The role/permission/role_permission catalog (§3's own data-driven-roles requirement — this is reference/config data, not product content).
2. Three `search_aliases` rows taken directly from ADR-8's own worked example ("Nexia, Neksiya, Нексия, ... Lasetti, Ласетти"). No car-model/brand catalog rows are seeded to go with them — populating real vehicle/product data is catalog content, out of Phase 02's scope.

Both are idempotent (`ON CONFLICT DO NOTHING`), verified by re-running the full migration chain against an already-seeded database.

## Verification strategy

**This section deliberately distinguishes two different things that were verified, because conflating them is exactly what let two real bugs (see "Roles & grants" above) ship undetected in the original Phase 02 pass.** "Migrations run cleanly" and "migrations run cleanly as the actual `comfort_migrate` role with actual `provision_roles.sql`-granted privileges" are different claims — the first was verified early; the second was not verified until the Phase 02 acceptance audit, and that gap is precisely where the CRITICAL and HIGH findings lived.

### Clean-database migration verification (schema/migration correctness — does not exercise role privileges)
Run as a superuser/database-owner dev role, so this tests the *migrations* in isolation, not the production privilege model:
1. `alembic upgrade head` run against two separate brand-new databases — one that had never seen a migration, and one that had been through a full `alembic downgrade base` first. Both produced an identical 27-table schema.
2. `alembic downgrade base` run end-to-end from `head`, confirmed to leave only Alembic's own bookkeeping table behind, then re-upgraded to `head` successfully.
3. 36 pytest tests in `tests/db/test_schema.py` (table existence, P1/P3 tables *not* existing yet, money-column typing, the full floating-point ban, every constraint — rejection and valid-insert cases, the audit append-only trigger, idempotency-key uniqueness, `§18.2` index existence, and the reservation double-release regression tests under true concurrent execution). All 36 pass.

### Migration-role verification (the actual production bootstrap procedure, genuinely exercised)
This is the check that was missing originally, and the one that found the CRITICAL/HIGH bugs:
4. `tests/db/test_migration_role_e2e.py` — provisions a genuinely fresh, disposable database, runs the real `provision_roles.sql` (in its documented order — roles *before* any migration), then runs `alembic upgrade head` with `DATABASE_URL` pointed at `comfort_migrate` credentials specifically (never a superuser, and never "migrate as superuser then switch role afterward"). Verifies: the migration reaches `head` (all 12 revisions actually ran, checked by name, not just "process exit code 0"), `pg_trgm` was actually installed by `comfort_migrate` itself, no partial state remains after a failure, `audit_logs` privileges on `comfort_app` are exactly `{INSERT, SELECT}` (not `UPDATE`), and `comfort_app`/`comfort_backup`'s boundaries hold when connected to directly. A second test in the same file runs the full `upgrade head → downgrade base → upgrade head` lifecycle, also genuinely as `comfort_migrate`, and re-confirms the `audit_logs` narrowing survives a second clean cycle.
5. **This test was confirmed to actually catch a regression**, not just pass by construction: the `GRANT CREATE ON DATABASE` fix was temporarily reverted and the test suite re-run, which failed with the exact `permission denied to create extension "pg_trgm"` error the original bug produced; the fix was then restored and the suite re-run to confirm it passes again.

Reproduce locally:
```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# --- Clean-database migration verification (superuser/dev-owner role) ---
export DATABASE_URL="postgresql+psycopg://<your-dev-user>@/<db>?host=<socket_dir>&port=<port>"
export OWNER_TELEGRAM_ID="<any bigint for local dev>"
alembic upgrade head

export TEST_DATABASE_URL="$DATABASE_URL"
python3 -m pytest tests/db/test_schema.py -v

# --- Migration-role verification (the actual production procedure) ---
# Requires a role with CREATEDB (NOT the same as comfort_migrate — this is
# used only to provision/tear down the throwaway test database).
export SUPERUSER_DATABASE_URL="postgresql://<a-createdb-role>@/postgres?host=<socket_dir>&port=<port>"
python3 -m pytest tests/db/test_migration_role_e2e.py -v
```

To exercise `provision_roles.sql` and the role-boundary checks manually rather than through the e2e test:
```bash
psql <connection-args-as-a-superuser> \
     -v comfort_app_password="<pw>" -v comfort_migrate_password="<pw>" \
     -v comfort_backup_password="<pw>" -f db/provision_roles.sql

export TEST_DATABASE_URL_AS_APP="postgresql://comfort_app:<pw>@/<db>?host=<socket>&port=<port>"
export TEST_DATABASE_URL_AS_BACKUP="postgresql://comfort_backup:<pw>@/<db>?host=<socket>&port=<port>"
python3 -m pytest tests/db/test_schema.py::TestRolePrivileges -v
```

## What Phase 02 does not cover (by design)

No API/Repository/Service code, no bot, no frontend, no worker application logic, no production infrastructure — see `docs/tasks/Phase-02-Database.md` "Do NOT implement" list. The Repository layer that will eventually query these tables (Phase 03) still has an open question about its own internals (OPEN-3, asyncpg vs. SQLAlchemy Core) that this phase does not resolve and does not need to.

## Audit corrections (2026-09-19)
- Migrations 0013–0016 (`notification_delivery`, `compatibility_soft_delete`, `store_settings`, `cart_items_soft_delete`) exist in `backend/alembic/versions/` in addition to the 0001–0012 listed above; the schema is 28 tables + `alembic_version` (as `tests/db/test_migration_role_e2e.py` asserts).
- The password arguments to `provision_roles.sql` are passed **raw** (`-v comfort_app_password="<pw>"`) — the double-quoted-with-embedded-apostrophes form this document previously showed is the bootstrap-breaking bug `tests/db/test_provision_roles_quoting.py` guards against. The script now also sets `\set ON_ERROR_STOP on`, so a forgotten `-v` fails loudly instead of silently skipping role creation.
- `TEST_DATABASE_URL` for `tests/db` must be a plain `postgresql://` DSN (psycopg), not the `postgresql+psycopg://` Alembic form.
- `alembic/env.py` escapes `%` in `DATABASE_URL` (ConfigParser interpolation) — URL-encoded passwords and `?options=` clauses previously made every `alembic` command fail.
