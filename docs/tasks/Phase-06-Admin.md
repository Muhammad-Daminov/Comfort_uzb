# Phase 06 — Admin Panel

**Owner:** frontend (screens), backend-core/backend-commerce (endpoints)
**Status:** ✅ Complete (P0 scope; Sell-requests/Chats/Broadcast remain P1, Phase-10)
**Last updated:** 2026-08-18
**Dependencies:** [Phase-03-Backend.md](Phase-03-Backend.md), [Phase-05-MiniApp.md](Phase-05-MiniApp.md)

## Objective
Build the ADMIN screen set (§14.1): Dashboard, Orders, Order detail, Payments, Products, Product editor, Stock, Sell-requests, Chats, Broadcast — and the `/admin/*` endpoints backing them.

## Prerequisites
- Phase 03 admin endpoints exist or are built alongside this phase.
- Permission matrix (§3) enforced server-side for every admin action before any admin UI ships.

## Deliverables
- `/admin/*` endpoints per §13.4 (orders confirm/cancel, payments review, product/variant/image CRUD, inventory adjust, sell-requests review — P1 items land when `backend-engagement` is ready).
- ADMIN Mini App screens.
- `docs/07_ADMIN_PANEL_SPEC.md` written.

## Definition of Done
- [x] ADMIN role cannot reach `finance.view`/`analytics.view`/`admins.manage`/`audit.view`/`settings.manage` — tested, not just hidden in UI (§12.6 case) — `tests/integration/test_admin_permissions_boundary.py::test_admin_still_cannot_reach_owner_only_permissions`.
- [x] Admin order-confirm decrements stock atomically and is race-safe (Phase 03 backend work, verified again here end-to-end) — reused as-is, no changes; existing `tests/integration/test_order_confirm.py` still green.
- [x] Manual stock adjustment requires and records a reason (§9) — reused as-is (Phase 03's `POST /admin/inventory/adjust`), Stock screen wired to it.
- [x] `docs/07_ADMIN_PANEL_SPEC.md` matches implemented screens exactly.

## Database change (one migration, not anticipated at Phase-06 planning time)
`0014_compatibility_soft_delete`: adds `product_compatibilities.deleted_at`. **Root cause, proven not assumed:** `comfort_app` has zero `DELETE` privilege on any table, blanket (§12.2) — the admin compatibility-removal endpoint's first implementation used a real `DELETE` (matching migration `0004_vehicle`'s own original reasoning that this table is "a pure association row, not a business entity"), which fails in production with `permission denied for table product_compatibilities` (live-reproduced while building this phase's integration tests). Fixed with the smallest change that preserves the existing privilege architecture: soft-delete, same pattern as every other table.

**Related finding, not fixed this phase (out of scope, flagged instead):** `app/domains/commerce/cart/repository.py`'s cart-item removal has the identical underlying problem — a real `DELETE FROM cart_items` — and would fail against `comfort_app` in production the same way. This is pre-existing Phase 03 code; per this phase's explicit "do not modify unrelated Phase 02/03 code" instruction, it was not touched, but is reported here and in the Phase 06 final report as a known, separately-fixable bug.
