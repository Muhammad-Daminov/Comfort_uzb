# 07 — Admin Panel Spec (Phase 06 ADMIN screens + Phase 07 OWNER screens)

**Purpose:** Screen-by-screen contract for the Admin Panel and Owner Panel, matching `miniapp/src/screens/admin/*` and `miniapp/src/screens/owner/*` exactly.
**Owner:** frontend (screens), backend-core/backend-commerce (endpoints)
**Last updated:** 2026-08-18
**Dependencies:** [00_MASTER_TZ.md](00_MASTER_TZ.md) §14.1, [04_API_SPEC.md](04_API_SPEC.md), [02_FEATURE_INVENTORY.md](02_FEATURE_INVENTORY.md), [06_MINIAPP_SPEC.md](06_MINIAPP_SPEC.md) (shared frontend app/conventions)

## Scope: 7 P0 screens (`02_FEATURE_INVENTORY.md` line 113)
Dashboard, Orders, Order detail, Payments, Products, Product editor, Stock — all built. Sell-requests/Chats/Broadcast are explicitly P1 (`AGENTS/backend-engagement.md`), deferred to Phase 10.

## Deployment boundary
The Admin Panel lives in the **same** `miniapp/` Vite app as the USER screens (Phase-06-Admin.md doesn't specify a separate deployment target, and Master TZ §14.4 describes one static build, one Nginx root). `/admin/*` routes are only *shown* in navigation when the session's role is `ADMIN`/`OWNER` (`state/session.ts::isAdminRole`) — this is UX only. Every admin screen's data calls hit endpoints independently gated by `require_permission` server-side; a USER navigating to an admin URL directly gets 403s from the API, not a working screen with a hidden nav link (verified: `backend/tests/integration/test_admin_permissions_boundary.py`, and the Phase 06 manual end-to-end trace).

## Screens

### Dashboard (`screens/admin/dashboard.ts`)
Deliberately not a metrics dashboard — ADMIN has neither `finance.view` nor `analytics.view` (§3; that's OWNER-only, Phase 07). Shows two operational counts (`GET /admin/orders?status=UNDER_REVIEW`, `GET /admin/payments?status=PENDING`) with links into the corresponding screens, plus Products/Stock shortcuts. No new backend endpoint — composed from two existing list calls.

### Orders (`screens/admin/orders.ts`) / Order detail (`screens/admin/order-detail.ts`)
`GET /admin/orders?status=` (status-filter buttons, defaults to `UNDER_REVIEW`), `GET /orders/{id}` (already admin-capable via `orders.view.all` — no separate admin detail endpoint needed), `POST /admin/orders/{id}/confirm` (MainButton, only shown while `UNDER_REVIEW`), `POST /admin/orders/{id}/cancel` (reason prompt, only shown while cancellable).

### Payments (`screens/admin/payments.ts`)
`GET /admin/payments?status=PENDING` (new this phase — Phase 03 never built a list). Per row: view receipt (signed URL via `GET /admin/payments/{id}/receipt`, opened in a new tab — never streamed through the Mini App), approve, reject (reason prompt, required).

### Products (`screens/admin/products.ts`) / Product editor (`screens/admin/product-editor.ts`)
List reuses `GET /catalog/products` (a known simplification — see "Known limitations" in the Phase 06 report: this only surfaces `ACTIVE` products, since that's the only status the public listing endpoint returns; a newly created `DRAFT` product is still reachable directly via the id `POST /admin/products` returns). The editor is one screen covering: product fields + status transitions, variant list + create form (price/SKU only — stock fields are never exposed here, by construction), image grid (upload/remove/set-primary), vehicle-compatibility manager (cascading car brand → model → generation selects via the existing `GET /vehicles/*`, then `POST/DELETE /admin/products/{id}/compatibilities`).

### Stock (`screens/admin/stock.ts`)
Search (`GET /catalog/search`, reused) → pick a product → see each variant's `stock_on_hand`/`stock_reserved` → submit an adjustment via the existing `POST /admin/inventory/adjust` (quantity delta + mandatory reason, §9).

## Security
No admin screen trusts a client-side role check as authorization — every action's actual gate is the backend's `require_permission` dependency, unchanged from Phase 03. No price/stock value is computed client-side and sent as authoritative (inventory adjustments send a delta + reason; the backend's guarded UPDATE and CHECK constraints are what's actually enforced).

---

## Owner Panel (Phase 07) — 6 screens (`02_FEATURE_INVENTORY.md` line 115, P2)
Dashboard, Finance, Analytics, Admins, Audit, Settings — all built. Lives in the same `miniapp/` app; `/owner/*` routes are only shown in navigation when `state/session.ts::isOwnerRole()` is true (role === `OWNER` exactly — **not** `isAdminRole()`, which intentionally includes OWNER for Admin-Panel access but must not leak Owner-only nav to a plain ADMIN). Same discipline as Phase 06: every screen's data calls are independently gated server-side (`backend/tests/integration/test_owner_authorization_matrix.py`, plus a full HTTP-level trace covering OWNER/ADMIN/USER for all six areas).

### Dashboard (`screens/owner/dashboard.ts`)
`GET /owner/dashboard`. Revenue, order-status counts, product counts, low-stock list, quick links into the other five screens.

### Finance (`screens/owner/finance.ts`)
`GET /owner/finance?from=&to=` with a date-range picker (defaults to trailing 30 days). Revenue, payment-status breakdown, payment listing with the ADR-9 "⚠️ hidden before review" flag shown inline per row.

### Analytics (`screens/owner/analytics.ts`)
`GET /owner/analytics?from=&to=`. Order-status distribution, best-selling products, orders-over-time (daily).

### Admins (`screens/owner/admins.ts`)
`GET/POST /owner/admins`, `POST /owner/admins/{id}/{de,re}activate`. Create form takes only `telegram_id` + optional name — there is no role selector in the UI because there is no role field in the API at all (§4 "Admin Management").

### Audit (`screens/owner/audit.ts`)
`GET /owner/audit-logs`, keyset "load more" pagination (no page numbers — matches the cursor contract, never `OFFSET`).

### Settings (`screens/owner/settings.ts`)
`GET/PUT /owner/settings`. A generic key/value editor, not a form of named fields — see `docs/04_API_SPEC.md`'s settings entry and `docs/tasks/Phase-07-Owner.md` "Known limitations" for why: the TZ never specifies actual setting content, so none was invented. Starts empty.

## Deferred to later phases
Sell-requests/Chats/Broadcast admin screens (P1, Phase 10).
