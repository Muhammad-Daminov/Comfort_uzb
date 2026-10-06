# Phase 02 — Database

**Owner:** database
**Status:** ✅ Complete
**Last updated:** 2026-08-17
**Dependencies:** [Phase-01-Architecture.md](Phase-01-Architecture.md), [../04_DOMAIN_ARCHITECTURE.md](../04_DOMAIN_ARCHITECTURE.md), ADR-003/004/005/006/007/008/009/011, [../03_DB_SCHEMA_PLAN.md](../03_DB_SCHEMA_PLAN.md) (implementation record)

## Objective
Stand up the full ~20-table MVP schema (P0 domains from `04_DOMAIN_ARCHITECTURE.md`) with all constraints, indexes, and least-privilege roles, versioned through Alembic from the first migration.

## Prerequisites
- Phase 01 complete.
- Local dev Postgres instance available.

**Corrected per Phase 0 review:** `OPEN-3` (asyncpg vs SQLAlchemy Core) is **NOT** a prerequisite for this phase. It's a Repository/application-layer convention question (see `../06_OPEN_DECISIONS.md`), not a schema/DDL question — Alembic migrations, constraints, and indexes are unaffected by which library the app later uses to query the database. It must be resolved before Phase-03 Repository-layer code is written (see `Phase-03-Backend.md`), but Phase-02 schema/migrations/constraints/indexes/roles/storage-related structures may proceed without it.

## Deliverables
- Alembic project scaffolding, migration 001 (schema + OWNER bootstrap per ADR-011).
- All P0 tables from `04_DOMAIN_ARCHITECTURE.md`, with constraints from Master TZ §5–§10.
- All indexes from Master TZ §18.2.
- `comfort_app`/`comfort_migrate`/`comfort_backup` roles with grants per §12.2 — **owned and executed by `database`** as DDL (per §17.4, all DDL is `database`'s domain); `security` defines the least-privilege policy this DDL implements and reviews it for compliance, but does not write it. `devops` is not involved in this deliverable — it owns only `pg_hba.conf`/`postgresql.conf` runtime config, addressed in Phase-09. (Ownership clarified per Phase 0 review; see `../05_AGENT_ARCHITECTURE.md`.)
- `search_aliases` seed data and `pg_trgm` extension enabled.
- `docs/03_DB_SCHEMA_PLAN.md` written (split out of Master TZ §5–§10, §18.2).
- `brands` and `colors` implemented as normalized lookup tables with stable surrogate IDs (not free-text columns) — see `REQ-CAT-005` in `01_REQUIREMENTS_MAP.md`, required so `discount_targets.target_type='BRAND'` can reference a stable `target_id` (§7.1).

## Definition of Done
- [x] `alembic upgrade head` produces a schema matching every P0 table in `04_DOMAIN_ARCHITECTURE.md` — 27 tables, verified against a real disposable PostgreSQL 16 instance (not just written and assumed correct).
- [x] Every `CHECK` constraint named in the TZ exists (money ≥0, stock ≥0, `stock_reserved ≤ stock_on_hand`, phone format, year_to ≥ year_from, cancellation reason ≥10 chars, inventory-movement quantity math, etc.) — each one's rejection path exercised by `backend/tests/db/test_schema.py`.
- [x] Every partial unique index for soft-delete exists for tables that exist in P0 (SKU, primary image, single OWNER, phone, brand/color/car-brand/car-model/car-generation names). ~~Favorites, stock notifications~~ — corrected: those tables are P1 (ENGAGEMENT domain, not created this phase per `04_DOMAIN_ARCHITECTURE.md`); their unique indexes are `backend-engagement`'s responsibility in `Phase-10-Optimization.md`. This line's earlier wording incorrectly implied they belonged to Phase-02 — fixed here.
- [x] `comfort_app` role has no DELETE, no DDL grants; verified by attempting a DELETE and a DDL statement as that role against a live cluster and confirming rejection (`InsufficientPrivilege` in both cases). `comfort_backup` similarly confirmed read-only.
- [x] OWNER row seeded from `OWNER_TELEGRAM_ID` env var, single-OWNER constraint verified (a second `OWNER` insert attempt raises `UniqueViolation` against `idx_single_owner`).
- [x] Migrations are reproducible **as a superuser/dev-owner role** (schema/constraint correctness): a full `alembic downgrade base` → `alembic upgrade head` round trip was run, and `upgrade head` was independently run against a second, never-touched database, producing an identical schema both times.
- [x] **Migrations are reproducible as `comfort_migrate` specifically** (the actual production procedure — added after the Phase 02 acceptance audit found this had never been checked): `tests/db/test_migration_role_e2e.py` provisions roles via the real `provision_roles.sql` in its documented order, then runs `alembic upgrade head` genuinely connected as `comfort_migrate`, and runs the full `upgrade head → downgrade base → upgrade head` lifecycle the same way. This is the check that caught and now guards against the CRITICAL/HIGH findings below.
- [x] `brands`/`colors` implemented as normalized lookup tables (REQ-CAT-005).
- [x] No native Postgres ENUM types anywhere (§5.6) — verified.
- [x] No floating-point columns anywhere (ADR-3) — verified with a blanket schema-wide check, not just the known money columns.
- [x] 36/36 database-level tests pass (`backend/tests/db/test_schema.py` + `test_migration_role_e2e.py`): schema shape, constraints (both rejection and valid-insert cases), audit append-only trigger, index existence (§18.2 spot-check), role privilege boundaries, reservation double-release regression (concurrent), and the full migration-as-`comfort_migrate` lifecycle.
- [x] No API/frontend/bot/worker-application-logic code was introduced (`backend/` contains only `alembic/`, `db/provision_roles.sql`, and `tests/db/`).
- [x] No other agent's business ownership was silently changed.

## Phase 02 acceptance audit — findings and fixes

An independent acceptance audit (re-verifying against the actual files and a fresh PostgreSQL 16 instance, deliberately running migrations *as* `comfort_migrate` rather than the superuser role the original verification pass used) found two real, live-reproducible bugs the checklist above did not catch the first time, plus a real concurrency gap and a documentation-accuracy gap. All are now fixed and re-verified:

1. **CRITICAL — `comfort_migrate` couldn't complete `alembic upgrade head`**: missing database-level `CREATE` privilege (needed for migration `0006_search`'s `CREATE EXTENSION pg_trgm`). Fixed in `provision_roles.sql`.
2. **HIGH — `audit_logs` REVOKE silently no-op'd** in the documented run order (script runs before the table exists), leaving `comfort_app` with unintended `UPDATE` access at the grant level. Fixed at the root in migration `0011_security` (which now applies the narrowing itself, since it owns the table it just created), with `provision_roles.sql`'s own copy made a safe, guarded, non-load-bearing reapplication.
3. **HIGH — no test ever ran the migration chain as `comfort_migrate`**, which is exactly what let #1 and #2 ship. Fixed by adding `tests/db/test_migration_role_e2e.py`.
4. **MEDIUM — reservation double-release** has no CHECK-constraint defense (documented as a concurrency correctness note, not a schema bug — see `../03_DB_SCHEMA_PLAN.md`). Fixed by documenting the mandatory guarded-release pattern in `AGENTS/backend-commerce.md` and adding a concurrent regression test proving the pattern works.
5. **MEDIUM — documentation overstated verification completeness** (didn't disclose that "reproducible" claims used a superuser role, not `comfort_migrate`). Fixed by rewriting this file's and `../03_DB_SCHEMA_PLAN.md`'s verification sections to explicitly distinguish the two, and by updating `backend/README.md`'s quick-start to make the migration-role distinction unambiguous.

See [../03_DB_SCHEMA_PLAN.md](../03_DB_SCHEMA_PLAN.md) for the full implementation record, including all bugs the live-cluster verification caught (the `psql` `DO $$...$$` variable-interpolation limitation from the original pass, plus the two above from the acceptance audit) and every place this implementation had to decide something the TZ leaves implicit.
