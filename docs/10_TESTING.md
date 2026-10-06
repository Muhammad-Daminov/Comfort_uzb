# 10 — Testing

**Purpose:** Splits Master TZ §19 test-matrix requirements out into their own document, as `docs/00_INDEX.md` names as owed by this phase. Documents the actual test architecture that exists — how to run it, what it requires, what each suite proves.
**Owner:** qa
**Last updated:** 2026-08-18
**Dependencies:** [00_MASTER_TZ.md](00_MASTER_TZ.md) §19, [08_SECURITY.md](08_SECURITY.md), [../backend/README.md](../backend/README.md)

## Test architecture

Four backend suites, one frontend suite. Commands below are exactly what `backend/README.md`'s "Quick start"/"Migration-role verification"/"Tests" sections already document; this file adds *what each suite proves* and *what it requires*, rather than duplicating the run commands as a second source of truth.

| Suite | Path | Connects as | Requires |
|---|---|---|---|
| Unit | `backend/tests/unit/` | nothing (no DB) | nothing — pure functions, mocked bot/DB handler logic |
| Integration | `backend/tests/integration/` | `comfort_app` (`TEST_DATABASE_URL`) | a live Postgres 16 with all migrations applied; `SUPERUSER_DATABASE_URL` for test-data cleanup only (`comfort_app` itself has no DELETE/TRUNCATE grant, by design — see 08_SECURITY.md) |
| DB / schema | `backend/tests/db/test_schema.py` | your own dev/superuser role (`TEST_DATABASE_URL`); `TestRolePrivileges` additionally needs `TEST_DATABASE_URL_AS_APP`/`_AS_BACKUP` | a live Postgres 16 — this suite verifies schema shape and trigger behavior at a privilege level the app role itself doesn't have (e.g. proving `audit_logs`'s append-only trigger fires even for a role that *would* otherwise have UPDATE/DELETE, not just proving `comfort_app`'s grant is absent) |
| Migration-role E2E | `backend/tests/db/test_migration_role_e2e.py` | a throwaway DB it creates/drops itself, bootstrapped as `comfort_migrate` | `SUPERUSER_DATABASE_URL` with `CREATEDB` (not necessarily a full superuser) |
| Frontend | `miniapp/` (`npx vitest run`) | nothing (jsdom) | Node + the `miniapp/` `devDependencies` installed |

### What each suite proves, concretely

- **Unit**: pure logic in isolation — state-machine transition rules, price/discount resolution, phone/search-text normalization, session token encode/decode, Telegram `initData` HMAC verification, bot handler/poller logic against a mocked bot client. No network, no DB — fast, runs on every change.
- **Integration**: the thing that matters most for this project's own stated risk (§12.2's whole reason for existing) — that the application's actual SQL genuinely works *as the actual production role* (`comfort_app`), not as a superuser standing in for it. This is what caught the cart-item DELETE bug (Phase 08) and would catch any future DELETE/DDL creeping into a repository function. It also carries all business-flow, concurrency, authorization, IDOR, and (as of Phase 08-FINAL) security-boundary and performance-smoke coverage.
- **DB/schema**: the schema itself — every P0 table exists, constraints/indexes are in place, the audit-log append-only trigger actually blocks mutation (not just role privilege), reservation-release safety, etc. Deliberately run as a role that *does* hold grants the trigger still has to override, so the trigger — not the grant — is what's under test.
- **Migration-role E2E**: the actual documented production bootstrap procedure (`provision_roles.sql` then `alembic upgrade head`, both as `comfort_migrate`, never a superuser) genuinely works end to end — upgrade → downgrade → upgrade — against a database it creates and destroys itself, so it never touches a shared database by accident.
- **Frontend**: DOM-level behavior of every screen module — rendering, loading/error/retry states, role-based navigation gating, form validation, price-mismatch recovery — via `jsdom`, no real browser.

## Environment requirements

- **Postgres 16**, reachable via Unix socket (the project's own `listen_addresses='localhost'` convention — see 08_SECURITY.md). A disposable cluster works fine for local dev/CI; never point any of these at a shared or production database (REQ-OPS-008).
- **`OWNER_TELEGRAM_ID`** must be set before `alembic upgrade head` — migration `0002_owner_bootstrap` seeds the one ADR-11 OWNER row from it.
- Integration tests deliberately never truncate `users` between runs (see `tests/integration/conftest.py`'s `clean_slate` fixture) — it preserves the seeded OWNER row other suites depend on. **Consequence for anyone writing a new test**: never hardcode a literal `telegram_id`/phone number/other-uniquely-constrained value; always let `factories.make_user(conn)` generate a random one (or use a distinct, commented literal if a fixed value is genuinely required), or a second run of the same test file within the same session will collide on a leftover row from the first run. This exact bug has been hit and fixed at least three times across this project's phases (Phase 05's phone test, Phase 06/08's compatibility/IDOR tests) — it is the single most common test-authoring mistake in this codebase.

## How to run each suite

See `backend/README.md`'s "Quick start", "Migration-role verification", and "Tests" sections for the exact commands — reproduced in one place there deliberately, not duplicated here as a second copy that can drift out of sync.

Frontend:
```bash
cd miniapp
npm install
npm test          # vitest run — DOM/unit tests
npm run build     # production build — tsc -b && vite build
```

## Security-focused entry point

`backend/tests/integration/test_security_suite.py` is the single consolidated file for the Master TZ §12.6 test matrix plus the Phase 08-FINAL role-escalation/observability checks — run it alone for a fast walk of the authentication/authorization/IDOR/upload/error-exposure boundary:

```bash
python3 -m pytest tests/integration/test_security_suite.py -v
```

It does not duplicate every individual case covered elsewhere (parallel-stock-purchase, parallel-confirm, idempotency, order/payment state machines, and inventory concurrency each have their own dedicated file — see the table below); it exists so a reviewer has one file that demonstrates the whole security boundary without having to know the project's full test-file layout.

### §12.6 case → test file mapping

| §12.6 case | Test |
|---|---|
| Parallel last-unit stock purchase (2 users, 1 unit) → only one succeeds | `test_order_creation.py` |
| Two admins confirm simultaneously → only one transition | `test_order_confirm.py` |
| User requests another user's order → 403 | `test_idor_regression.py`, `test_security_suite.py` |
| ADMIN hits `finance.view` → 403 | `test_security_suite.py::test_admin_hitting_finance_view_gets_403`, `test_owner_authorization_matrix.py` |
| Unsigned `/files/receipts/...` → 403 | **Not testable in this repo** — signed-URL verification is Nginx-side (Phase-09); see 08_SECURITY.md |
| Expired signature → 410 | **Not testable in this repo** — same reason |
| Another person's receipt signature → 403 | **Not testable in this repo** — same reason |
| Frontend-tampered price → backend rejects | `test_order_creation.py` (`PriceMismatch` → 409) |
| Negative quantity/price → 422 | `test_inventory_concurrent_adjust.py`, `test_order_creation.py`, unit validation tests |
| Duplicate Idempotency-Key → executes once | `test_idempotency.py` |
| Deactivated admin still acting → 403 | `test_security_suite.py::test_deactivated_user_token_is_rejected`, `test_owner_admin_management.py` |
| Broken/expired `initData` → 401 | `test_security_suite.py::test_broken_init_data_is_401`, `test_telegram_auth.py` |
| `.php`/executable upload → rejected | `test_security_suite.py::test_executable_disguised_as_image_is_rejected`, `::test_php_with_fake_extension_still_sniffed_and_rejected` |
| External `psql -h <server_ip>` doesn't connect | **Not testable in this repo** — a deployed-server firewall/`pg_hba.conf` property (Phase-09) |

11 of 14 cases are automated in this repository; the remaining 3 require infrastructure (Nginx, a deployed firewall) that does not exist here and is explicitly Phase-09's responsibility — documented, not silently skipped.

## Performance verification

`backend/tests/integration/test_performance_smoke.py` — a smoke test against a small, fixed, documented dataset (250 products, 60 orders/payments), not a load test. Asserts two properties per critical listing endpoint (catalog, search, orders, payments, owner dashboard/finance/analytics, audit log): the result set stays bounded by its own `limit` even though the table holds far more rows, and the query completes within a generous non-flaky bound (catches a catastrophic regression like an accidental N+1, not a throughput number). **Load testing not production-representative** — no realistic load-generation environment (Locust/k6/production-scale data) exists in or for this repository; §18's "50 browse + 10 checkout parallel" target from the Master TZ is not verified here and should not be treated as met.

## Production smoke test (Phase 09)

`deploy/scripts/smoke_test.py` — a standalone, zero-dependency script (stdlib only, runnable without a Python venv) that walks the USER/ADMIN/OWNER flows named in the Phase 09 deployment brief against a *running instance* (local or deployed), not the pytest suite. USER performs one real but harmless write (cart + order against existing catalog data, never a payment); ADMIN/OWNER are read-only checks. Run it against a deployed instance with:
```bash
python3 deploy/scripts/smoke_test.py --base-url https://comfort.example.uz \
    --bot-token "$BOT_TOKEN" --user-telegram-id <id> \
    [--admin-telegram-id <id>] [--owner-telegram-id <id>]
```
Exercised this phase against the local disposable stack only (all 15 checks passed) — never against a real deployed production instance, since none exists. See `docs/09_DEPLOYMENT.md` "Production smoke test".

## What "done" looks like for a suite run

A full local verification pass, in order:
1. `alembic upgrade head` as `comfort_migrate` against a fresh database — clean.
2. `pytest tests/unit` — no DB needed.
3. `pytest tests/integration` as `comfort_app` — run twice in direct succession (existing project convention) to catch test-data leakage that only shows up on a second pass against the same (deliberately-not-fully-truncated) database.
4. `pytest tests/db/test_schema.py` as a dev/superuser role (plus `TEST_DATABASE_URL_AS_APP`/`_AS_BACKUP` for the three role-privilege cases).
5. `pytest tests/db/test_migration_role_e2e.py` — upgrade → downgrade → upgrade as `comfort_migrate` against its own throwaway database.
6. `npx vitest run` and `npm run build` in `miniapp/`.
7. (Against a real deployment only) `deploy/scripts/smoke_test.py`.

As of Phase 09: 59 unit (56 + 3 new webhook-router tests) + 143 integration (140 + 3 new `/health` tests) + 34 db (0 skipped when `TEST_DATABASE_URL_AS_APP`/`_AS_BACKUP` are set) + 2 migration-role E2E = 238 backend tests, all green, run twice around integration. 46 frontend tests, unchanged. Production build unchanged (48.04KB/12.26KB gzip). Full numbers for this specific run: see the Phase 09 report.
