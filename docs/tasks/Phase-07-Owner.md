# Phase 07 — Owner (P2)

**Owner:** backend-core (finance/analytics/admin-activity endpoints — read-only reporting, no new tables; explicit ownership per [../05_AGENT_ARCHITECTURE.md](../05_AGENT_ARCHITECTURE.md) and [AGENTS/backend-core.md](../../AGENTS/backend-core.md)), frontend (OWNER screens)
**Status:** ✅ Complete
**Last updated:** 2026-08-18
**Dependencies:** [Phase-06-Admin.md](Phase-06-Admin.md)

## Objective
Ship OWNER-exclusive capability (P2, §2): financial report, analytics/top products, admin management, audit panel, settings.

## Prerequisites
- Phase 06 complete — OWNER screens are additive on top of the ADMIN screen set.
- Sufficient order/payment history exists to make finance/analytics meaningful (real usage data, not just schema).

## Deliverables
- `/owner/dashboard`, `/owner/finance`, `/owner/analytics`, `/owner/admins` (CRUD), `/owner/audit-logs`, `/owner/settings` (GET/PUT).
- OWNER screens: Finance, Analytics, Admins, Audit, Settings.
- `docs/07_ADMIN_PANEL_SPEC.md` extended with the OWNER-only screens (or a dedicated section — coordinate with `docs`).

## Definition of Done
- [x] Finance figures are computed from order/payment **snapshot** data (ADR-5), not live catalog joins — reads `orders.paid_amount`, the already-authoritative running total Phase 03's payment-approval path maintains.
- [x] Audit panel correctly surfaces the ⚠️ "hidden before review" warning per ADR-9's timestamp comparison — implemented in the Finance payment listing (not `audit_logs`, which has no `hidden_at` column); forward-compatible logic, always `false` today since no receipt-hide endpoint has shipped yet.
- [x] Admin management supports create/deactivate/reactivate but cannot create a second OWNER (ADR-11 enforced, tested) — `tests/integration/test_owner_admin_management.py::test_create_admin_cannot_reassign_the_owner`.
- [x] Only OWNER role can reach any `/owner/*` endpoint — tested (`tests/integration/test_owner_authorization_matrix.py` + a full HTTP-level OWNER/ADMIN/USER trace).

## Known limitations (explicit, not hidden)
- **Settings has no content yet, by design.** Master TZ §14.1 names a "Sozlamalar" screen for OWNER but never once states what a setting actually *is*, anywhere in the document (confirmed by exhaustive search during planning). This phase ships the persistence mechanism and OWNER-only `GET/PUT /owner/settings` contract as a generic, empty-by-default key/value store — zero business fields invented. Populating real settings is a future, content-driven task.
- **Low-stock threshold (`5`) is an operational display default, not a TZ business rule** — clearly labeled as such in the API response (`low_stock_threshold` field) so it's never mistaken for a requirement.
- **Pre-existing `cart_items` DELETE-vs-`comfort_app` bug (found in Phase 06)** — out of scope for Owner functionality (zero dependency on cart removal) and was not touched by this phase's work; subsequently fixed in the Phase 08 hardening pass via soft-delete migration `0016_cart_items_soft_delete.py` (see `backend/README.md`).

## Verification pass (2026-08-20)
- Added DOM test coverage for the three OWNER screens that previously had none: `miniapp/tests/dom/owner-finance-screen.test.ts`, `owner-analytics-screen.test.ts`, `owner-audit-screen.test.ts` (dashboard/admins/settings already had coverage). Full frontend suite: 15 files, 57 tests, all passing; `tsc -b && vite build` clean.
- Backend unit suite (59 tests, no DB) passing; static review of `app/domains/owner/{router,service,repository}.py`, `app/security/{permissions,audit}.py`, and the `0001_identity` permission seed found no deviation from `docs/04_API_SPEC.md` / Master TZ §3 / ADR-5 / ADR-9 / ADR-11.
- Backend integration/DB suites (`tests/integration/test_owner_*.py`, `tests/db/`) were **NOT VERIFIED** in this session — no Postgres superuser credentials, role passwords, or passwordless sudo were available in the execution environment to provision `comfort_app`/`comfort_migrate`/`comfort_backup` or run migrations. This is an environment access limitation, not a code or documentation gap.
- **Update (2026-08-20, Phase 08 verification pass):** this gap is closed. A disposable Postgres 16 cluster was provisioned independently of the system instance (own `initdb` data directory, own OS-user superuser, no sudo needed), and every backend suite was genuinely executed: `tests/integration/test_owner_*.py` and `tests/db/` all pass as part of the full 148-test integration run and 34-test DB run — see `docs/tasks/Phase-08-Security.md` "Verification pass (2026-08-20)" for full counts and the one test bug found and fixed along the way (unrelated to Owner functionality).
