# Phase 08 — Security Hardening & Testing

**Owner:** security (hardening), qa (test execution)
**Status:** PASS WITH LIMITATIONS — see "Phase 08-FINAL completion pass" and "Verification pass (2026-08-20)" below. `docs/08_SECURITY.md` and `docs/10_TESTING.md` are written; OPEN-2 is resolved at the mechanism/code level. All backend test suites (unit/integration/DB/migration-role E2E, 243 tests) have now been genuinely executed against a real disposable PostgreSQL 16 instance, not merely read. Load testing, browser/device testing, and 3 of the 14 §12.6 cases (Nginx-dependent) remain genuinely untestable in this repository and are explicitly documented as such, not silently marked done.
**Last updated:** 2026-08-20

## Hardening pass (2026-08-18) — production-readiness audit, not the full security sign-off
A system-wide hardening/audit pass was run against the Phase 07 baseline, distinct from (and narrower than) this file's original full deploy-gate scope below. Full findings, fixes, and verification: see the Phase 08 implementation report (files changed, bugs found/fixed, test results) and the updated `docs/04_API_SPEC.md` cart section.

**Fixed:** `app/domains/commerce/cart/repository.py`'s cart-item removal used a real `DELETE`, which `comfort_app` cannot execute (§12.2, zero DELETE privilege, blanket) — identical failure mode to the Phase 06 `product_compatibilities` bug. Fixed via `alembic/versions/0016_cart_items_soft_delete.py` (additive: `cart_items.deleted_at` + a matching partial unique index), same pattern as every other soft-deleted table.

**Audited, no other production-path DELETE found:** exhaustive `grep` across `app/` and `bot/` (excluding migrations, which run as `comfort_migrate`, and test code) confirms the cart repository was the only offender.

**Audited and verified already-correct (no change needed), each backed by a new or existing test:** order state machine transitions (the brief's own named examples: cancelled→confirmed, confirmed→cancelled, already-confirmed→confirmed, already-cancelled→cancelled — all already rejected); payment one-way approval (Phase 03); inventory-adjust concurrency (two genuinely concurrent adjustments, no lost update, verified with real concurrent connections, not simulated); `GET /orders/{id}` cross-user IDOR (403, new HTTP-level regression test — no prior test exercised this specific path); cart cross-user IDOR (structurally impossible, `cart_id` always server-derived); upload path-traversal (server-generated UUIDs only, no user-controlled path segment); API error consistency (no raw DB error reaches any response); frontend resilience (every screen already routes through the shared `error-state.ts` component).

**Not done this pass — closed in the Phase 08-FINAL completion pass below.**
**Dependencies:** [Phase-03-Backend.md](Phase-03-Backend.md) through [Phase-07-Owner.md](Phase-07-Owner.md)

## Phase 08-FINAL completion pass (2026-08-18) — security & deploy-readiness debt closeout

Closes out the items the hardening pass above left outstanding, within this phase's own strict scope (no Nginx/systemd/VPS/production deployment/load-generation infrastructure — those remain genuinely Phase-09's job).

**Bug found and fixed (new this pass, unrelated to the cart bug):** `GET /catalog/products` — the primary, unfiltered product-listing endpoint — crashed with `asyncpg.exceptions.UndefinedTableError: missing FROM-clause entry for table "p"` on every call using the default `sort=newest`. Root cause: `catalog/repository.py`'s `_SORT_COLUMNS` mapped `"newest"` to `"p.created_at"`, but that expression is evaluated in the outer query against a subquery alias (`listing`) whose exposed columns have no table qualifier — `p` doesn't exist at that scope. This endpoint had **zero test coverage of any kind** before this pass (only `GET /catalog/products/{id}` was tested), which is how it went undetected through Phases 03–08. Fixed by changing the mapping to the subquery's actual exposed column name (`"created_at"`). Regression coverage: `tests/integration/test_security_suite.py::test_request_id_header_present_on_every_response` and `test_performance_smoke.py::test_catalog_listing_is_bounded_and_fast` both exercise this exact code path against real data.

**Observability (OPEN-2) resolved at the mechanism/code level:** `backend/app/observability.py` — structured JSON logging, per-request `X-Request-ID` correlation, and a global exception handler guaranteeing every unexpected exception is logged server-side (full traceback) and never leaks to the client (fixed generic body only). Chooses the log-based resolution (b) already recommended in `docs/06_OPEN_DECISIONS.md` OPEN-2, no new external dependency. Actually shipping these log lines to a human (Telegram/journald forwarding) is Phase-09 deployment wiring, explicitly out of this phase's scope — see `docs/08_SECURITY.md` "Observability" for the precise boundary.

**Consolidated security suite added:** `tests/integration/test_security_suite.py` (20 tests) — single entry point for the Master TZ §12.6 matrix plus role-escalation/observability checks. Includes the first-ever tests for `app/security/uploads.py` (executable-upload rejection, oversized/empty rejection, filename-derivation safety) — that module had no test coverage at all before this pass.

**Performance smoke test added:** `tests/integration/test_performance_smoke.py` (8 tests) — bounded-result-set + non-flaky-timing checks against a small fixed dataset for every critical listing endpoint. Explicitly not a load test; §18's concurrent-load targets remain unverified (no load-generation environment exists).

**Documentation written:** `docs/08_SECURITY.md` (full §12 content, with explicit "verified by test / verified by review / not tested" labeling per claim) and `docs/10_TESTING.md` (full §19 content, environment requirements, §12.6 case-to-test mapping, exact current test counts).

**Not done — genuinely out of reach without Phase-09 infrastructure, documented not silently claimed:** load testing under §18's concurrency targets; 3 of the 14 §12.6 cases (unsigned/expired/wrong-owner receipt URL — Nginx-side verification doesn't exist in this repo); browser/device testing; production deployment of any kind; in-app rate limiting (§12.4 — no framework exists to add it to, and building one was judged out of this hardening pass's scope).

## Verification pass (2026-08-20)

Unlike the Phase-07 verification session (blocked on missing DB credentials), this pass provisioned a genuinely fresh, disposable PostgreSQL 16 cluster (own `initdb` data directory, own port, own OS-user superuser — no system Postgres or sudo access needed) and ran `db/provision_roles.sql` + `alembic upgrade head` exactly as `comfort_migrate`, per this file's own documented bootstrap procedure. This let every backend suite actually execute for the first time in this project's session history, not just be read:

- `tests/unit`: **59/59 passed**.
- `tests/integration`: **148/148 passed** (143 pre-existing + 5 new `test_receipt_purge.py` cases) — includes `test_owner_*`, `test_security_suite.py`, `test_performance_smoke.py`, concurrency, idempotency, and rollback suites, all genuinely executed against live Postgres as `comfort_app`.
- `tests/db/test_schema.py`: **34/34 passed** (after a fix — see below).
- `tests/db/test_migration_role_e2e.py`: **2/2 passed** — the real `provision_roles.sql` → `alembic upgrade head` bootstrap, executed as `comfort_migrate` against its own throwaway database, not simulated.

**Bug found and fixed:** `tests/db/test_schema.py::TestAuditAppendOnly`'s two mutation-rejection tests had never actually been run against real `comfort_app` credentials before (Phase 07's session was blocked before reaching them). Both asserted `psycopg.errors.RaiseException` (the `prevent_audit_mutation()` trigger's exception), but `comfort_app` has no UPDATE/DELETE grant on `audit_logs` at all (§12.2) — Postgres denies the mutation at the privilege layer before the trigger is ever reached, raising `InsufficientPrivilege` instead. The append-only *behavior* was always correct (two independent layers enforce it); only the test's expected exception type was wrong. Fixed to accept either exception, since which layer catches the mutation first is not the invariant under test — that the mutation is rejected, is.

**Gap found and closed:** `comfort-receipt-purge` (ADR-9) had no implementation anywhere in the codebase — `docs/09_DEPLOYMENT.md` and `Phase-09-Deploy.md` already flagged this honestly rather than hiding it. ADR-9 fully specifies the logic (delete files past `retention_until`, stamp `file_purged_at`), and `payment_receipts` already carries a partial index built for exactly this query. Implemented `backend/app/workers/receipt_purge.py`, following the exact callable-function, no-systemd-dependency, guarded-update-idempotent pattern already established by `reservation_expiry.py`; added a path-traversal backstop (storage_path is always server-generated, never client input, but the worker still verifies the resolved path stays inside the uploads root before unlinking); 5 new integration tests cover purge, not-yet-due, idempotent re-run, missing-file-on-disk, and the path-traversal backstop. Systemd/timer scheduling remains Phase-09, per ADR-9's own division of ownership. Product-image file purge remains genuinely unimplemented and is **not** addressed by this fix — no ADR defines a retention policy for product images (unlike receipts' explicit 30-day `retention_until`), so inventing one was out of scope; this stays documented as deferred debt, not silently missing.

**Frontend bug found and fixed:** `miniapp/src/telegram.ts`'s `setBackButton`/`setMainButton` called the real Telegram WebApp SDK's `.onClick()`, which *adds* a listener rather than replacing the previous one — `.offClick()` with the same function reference is required to remove it. No screen or the router ever called the returned disposer between navigations, so every screen visited during a session left its BackButton/MainButton handler (a stale closure, potentially referencing an already-unmounted screen) registered alongside the current one. Fixed by having `telegram.ts` itself track and clear the single most-recently-registered handler before registering a new one, so cleanup no longer depends on ~23 screens or the router remembering to do it. 3 new unit tests (`tests/unit/telegram.test.ts`) prove the previous handler is removed before the next is registered, and that the returned disposer still works standalone.

**Frontend polish:** `checkout.ts` now shows an empty-cart state (`emptyState`) instead of silently hiding the main button with no visible feedback; both `checkout.ts` and `payment.ts` now show a loading skeleton during their initial data fetch, matching the pattern every other screen already used. 1 new test for the empty-cart state; `payment.ts` gained its first-ever dedicated test file (4 tests) — it previously had zero coverage.

**Frontend full suite after this pass:** 17 test files, **65/65 passed**; `tsc -b && vite build` clean; bundle 48.31 kB JS / 12.35 kB gzip + 1.51 kB CSS — still well under the §18 400 KB budget. First-paint-under-2s-on-4G remains **NOT VERIFIED** — no real browser/network-throttling environment was available this pass either; bundle size is not a substitute for that measurement, and is not claimed as one.

**Still not testable in this environment:** the 3 Nginx-dependent §12.6 cases, load testing, browser/device testing, and anything requiring a real VPS — unchanged from the original Phase-08-FINAL pass, still Phase-09's job.

## Objective
Close out every item in §12 (Xavfsizlik) and run the full §19 test matrix against the assembled system before deploy.

## Prerequisites
- All P0 backend, bot, and frontend functionality implemented (Phases 03–06 at minimum; Phase 07 if in scope for this release).

## Deliverables
- `docs/08_SECURITY.md` written (full §12 content, split from Master TZ).
- `docs/10_TESTING.md` written (§19 content, split from Master TZ).
- All 14 §12.6 security test cases automated and passing.
- Unit/integration/E2E/load test suites implemented and passing.
- OPEN-2 (Sentry vs error-log→Telegram) resolved and implemented.

## Definition of Done
- [x] 11 of 14 §12.6 cases pass, automated (`tests/integration/test_security_suite.py` + the files it cross-references — see `docs/10_TESTING.md`'s case-to-test mapping). The remaining 3 (unsigned/expired/wrong-owner receipt URL) require Nginx `secure_link` verification, which does not exist in this repository — Phase-09.
- [x] E2E flow (user→cart→order→payment→admin confirm→stock decrement) passes — covered across `test_order_creation.py`, `test_order_confirm.py`, `test_payment_review.py`, exercised together in each phase's manual HTTP trace.
- [ ] Load test (50 browse + 10 checkout parallel) meets §18 performance targets under load — **not done**, no load-generation environment exists; a non-representative performance *smoke* test exists instead (`test_performance_smoke.py`) and is explicitly labeled as such.
- [x] Error tracking mechanism (per OPEN-2 resolution) is implemented and live at the application level (`app/observability.py` — every unexpected exception is now logged, never silently lost). Delivery of those logs to a human-facing alert channel (the owner's Telegram, per OPEN-2's own recommended resolution) is **not wired up** — that requires Phase-09 process/systemd wiring this phase's scope explicitly excludes.
