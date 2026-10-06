# Phase 03 — Backend

**Owner:** backend-core, backend-commerce (joint phase — see split below)
**Status:** ✅ Complete
**Last updated:** 2026-08-17
**Dependencies:** [Phase-02-Database.md](Phase-02-Database.md), [../05_AGENT_ARCHITECTURE.md](../05_AGENT_ARCHITECTURE.md)

## Objective
Build the P0 backend: Router/Service/Repository layering (§13.1), auth, catalog, cart, order, payment, stock — the full API surface a P0 client needs, per Master TZ §13.4.

## Prerequisites
- Phase 02 complete (schema exists).
- `security` primitives available: initData verification, permission-check helper, idempotency middleware, audit helper, signed-URL signer (can be built in parallel as its own workstream — see Phase-08 for full security hardening, but the primitives themselves are needed here first).
- `OPEN-3` (asyncpg vs SQLAlchemy Core, see `../06_OPEN_DECISIONS.md`) resolved before Repository-layer code is written — this is where it actually applies, not Phase-02 (corrected per Phase 0 review; Phase-02's schema/DDL work does not depend on this choice). **Resolved**: raw asyncpg, formalized in [ADR-015](../adr/ADR-015-repository-data-access.md) before any Repository-layer code was written.

## Deliverables
- `backend-core`: `/auth/session`, `/catalog/*`, `/vehicles/*`, discount resolution.
- `backend-commerce`: `/cart/*`, `/orders/*`, `/payments/*`, `/admin/orders/*`, `/admin/payments/*`, `/admin/inventory/adjust`.
- `backend-commerce`: **`comfort-reservation-expiry` worker BUSINESS LOGIC** (release TTL-expired reservations, order → `EXPIRED`, REQ-WRK-001, ADR-6) — the callable function/Service method, built and unit-tested alongside the order/reservation code it shares a domain with. Corrected per Phase 0 review: this must not be deferred to Phase-09 — TZ §22 itself sequences workers immediately after order/payment backend work, not at deploy time. `devops` wires this function into a systemd timer later (Phase-09); the logic itself ships here.
- `docs/04_API_SPEC.md` written (split from Master TZ §13.4, with request/response/error detail per endpoint).
- Server-side checkout re-validation (§7.3) and order-confirm concurrency handling (§8.2) implemented and unit/integration tested.

## Definition of Done
- [x] Every endpoint in §13.4's non-admin/non-owner block within Phase-03 scope responds correctly, enforces §3 permissions server-side (`app/security/permissions.py`, checked live via `role_permissions` on every request, not cached in the session token).
- [x] Checkout price mismatch returns `409` with the corrected price (§7.3) — `tests/integration/test_order_creation.py::test_stale_client_price_is_rejected_with_409_style_error`.
- [x] Parallel-confirm and parallel-last-unit-purchase tests pass (§8.2, §12.6) — `tests/integration/test_order_confirm.py`, `tests/integration/test_order_creation.py::test_parallel_last_unit_purchase_exactly_one_succeeds`, both using two genuinely concurrent asyncpg connections via `asyncio.gather`, not a simulated/sequential stand-in.
- [x] Order snapshot fields are correct and immune to later product edits (ADR-5) — `tests/integration/test_order_creation.py::test_successful_checkout_writes_snapshot_and_reservation`.
- [x] `docs/04_API_SPEC.md` matches the implemented endpoints exactly (no drift) — written this phase, one entry per route in `app/domains/*/router.py`.
- [x] `comfort-reservation-expiry` business logic is implemented and unit-tested (callable directly, independent of whether the systemd timer exists yet): a reservation past `expires_at` is released and its order moves to `EXPIRED` within one invocation — `app/workers/reservation_expiry.py`, `tests/integration/test_reservation_expiry.py` (including a same-reservation-twice no-op test).

Test totals: 28 unit (`backend/tests/unit/`, no DB) + 22 integration (`backend/tests/integration/`, live Postgres, exercised as `comfort_app` — the actual production application role) + the pre-existing 36 database tests (`backend/tests/db/`, unaffected) = 86 automated tests, plus one manual end-to-end HTTP trace (cart → order → payment submit → receipt upload → admin approve → admin confirm → stock decremented) through the real FastAPI app via `httpx.ASGITransport`.

## Audit corrections (2026-09-19)
Full detail, evidence and regression tests: `docs/11_FULL_SYSTEM_AUDIT_REPORT.md`.
- Order confirm now consumes its `stock_reservations` rows (H2 — the expiry worker double-released them 24h later, corrupting `stock_reserved`); the confirm stock decrement is guarded (409 instead of a CHECK-violation 500).
- Catalog cursor pagination raised `UndefinedTableError` on every second page for every sort (H1) — fixed; malformed cursors are 422.
- `GET /catalog/search` matched with whole-string `%` similarity (a one-word query scored ~0.2, under the 0.3 threshold, so search returned nothing) and returned bare rows — now word similarity and the listing card shape (H5).
- Every error response now carries the §13.5 `error` envelope (H3); `POST /orders`, `/payments`, `/admin/inventory/adjust` really return 201.
- Cart items expose `current_price`/`discount_amount` (H4); ordered lines leave the cart at checkout (M3); idempotent endpoints run check→execute→store atomically (M1); one PENDING payment per order (M2); payment reject → order REJECTED, review refused on CANCELLED/EXPIRED orders (H6); listing `total_available` no longer multiplied by order lines (H7); soft-deleted compatibilities no longer price CAR_MODEL discounts (M4); admin lists take `limit` (M6); concurrent set-primary serialised (M10); 500 responses carry the real request id (M11); uploads capped while streaming and written 0640/0750 (H8).
