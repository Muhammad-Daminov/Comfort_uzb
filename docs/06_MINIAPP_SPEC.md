# 06 — Mini App Spec (Phase 05, USER screens)

**Purpose:** Screen-by-screen contract for the User Mini App, matching `miniapp/src/screens/*` exactly.
**Owner:** frontend
**Last updated:** 2026-08-18
**Dependencies:** [00_MASTER_TZ.md](00_MASTER_TZ.md) §14, [04_API_SPEC.md](04_API_SPEC.md), [02_FEATURE_INVENTORY.md](02_FEATURE_INVENTORY.md), [06_OPEN_DECISIONS.md](06_OPEN_DECISIONS.md) OPEN-7

## Stack
Vanilla TypeScript + Vite, no UI framework — decision confirmed with the user before implementation (no framework named in Master TZ §13.2; smallest footprint against the <400KB budget, §18). Production bundle: ~23KB (~7.4KB gzip), file-verified, not assumed.

## Scope: 13 P0 screens (`02_FEATURE_INVENTORY.md` line 111)
Home, Catalog, Search, Filter, Product detail, Cart, Checkout, Payment, Receipt upload, Order detail, Profile, Settings — **built**, except:
- **Notifications**: deferred. Tagged P0 in the feature inventory but its endpoint is explicitly `backend-engagement`-owned (P1) in `AGENTS/backend-engagement.md` — a genuine doc contradiction, logged as **OPEN-7**, not silently resolved.
- **Settings**: merged into the Profile screen (`screens/profile-settings.ts`) — the TZ names both but gives no USER-specific Settings content beyond profile display, and phone capture is explicitly the bot's job (ADR-2), not the Mini App's.

P1-tagged screens (Favorites, **Order history list**, Sell, Chat) are not built — deferred to Phase 10 with `backend-engagement`. Order *detail* (P0) is reachable without the list screen: directly after checkout, and via a "most recent order" link on Home (`GET /orders`, taking `items[0]`).

## Screens

### Home (`screens/home.ts`)
First page of `GET /catalog/products`, a link to the most recent order (if any), navigation to Catalog/Cart/Profile.

### Catalog (`screens/catalog.ts`)
`GET /catalog/products` with cursor pagination ("Ko'proq ko'rsatish" load-more, not infinite scroll — simplest correct behavior, no premature complexity) + `GET /catalog/filters` (brand/sort/in-stock). Empty/loading/error states throughout.

### Search (`screens/search.ts`)
`GET /catalog/search?q=`, 300ms debounce, in-flight request aborted on a new keystroke (`AbortController`) — no stale-result race, no duplicate requests (verified: `tests/dom/search-screen.test.ts`).

### Filter
Implemented inline within Catalog (`GET /catalog/filters`, `GET /vehicles/*` wrappers exist in `api/vehicles.ts` for a dedicated vehicle-compatibility filter UI — car brand/model/generation selects are wired the same way as the brand filter).

### Product detail (`screens/product-detail.ts`)
`GET /catalog/products/{id}`. Variant selector disables inactive/out-of-stock options; price/availability shown per selected variant using the server's `current_price`/`discount_amount` (never computed client-side). Signed product image (ADR-13, `images[].signed_url` — added this phase) with expiry re-fetch on load failure.

### Cart (`screens/cart.ts`)
`GET/POST/PATCH/DELETE /cart*`. Every mutation re-fetches the cart (no optimistic local patch) — stale price/stock is never assumed still valid (verified: `tests/unit/cart-state.test.ts`).

### Checkout (`screens/checkout.ts`)
`POST /orders` with `Idempotency-Key`. On `409 PRICE_MISMATCH`: shows the corrected price and updates the pending submission in place — the corrected price is what's actually resubmitted, not the stale one (this was caught as a real bug during test-writing and fixed — see `tests/dom/checkout-screen.test.ts`). On `409 INSUFFICIENT_STOCK`: clear message + path back to Cart.

### Payment (`screens/payment.ts`)
`POST /payments` with `Idempotency-Key`.

### Receipt upload (`screens/receipt-upload.ts`)
Client-side compression before upload (§14.3: canvas, max 1600px, WebP q0.85) — UX/speed only; `POST /payments/{id}/receipt` still runs the backend's own independent validation/processing pipeline (`app/security/uploads.py`), which is authoritative.

### Order detail (`screens/order-detail.ts`)
`GET /orders/{id}`, `POST /orders/{id}/cancel` (reason prompt, ≥10 chars enforced client-side for UX, backend CHECK constraint is authoritative). MainButton context-sensitive: "Pay now" while payable, "Cancel order" while cancellable, hidden otherwise.

### Profile/Settings (`screens/profile-settings.ts`)
`GET /auth/me` (added this phase — see below). Read-only: name, username, role, phone (or a note to set it via the bot).

## Backend addition: `GET /auth/me`
`POST /auth/session`'s response is deliberately `{token, user_id, role}` only — no endpoint returned the caller's own phone/name. Added in `app/domains/identity/router.py`, reusing the existing `get_current_user` dependency and a single new `identity.repository.get_by_id` read. Same domain (`backend-core`/IDENTITY), no schema change, no ownership boundary crossed. Tests: `tests/unit/test_identity_me_shape.py`, `tests/integration/test_auth_me.py`.

## Backend addition: signed product images
`GET /catalog/products/{id}` previously returned raw `storage_path` for images — contradicts ADR-13 ("no file served unsigned"). Fixed by signing each image's URL in the router using the already-built `app/security/signing.py` (same module Phase 03 built for receipts), `products` folder, 24h TTL per §11.1. Test: `tests/integration/test_catalog_images.py`.

## Telegram integration (`src/telegram.ts`)
`initData` read once at startup (`window.Telegram.WebApp.initData`) and sent to `POST /auth/session` — the only auth mechanism, no second one introduced. `themeParams`/`colorScheme` mapped to CSS custom properties (`src/styles/theme.css`), safe-area insets applied to the app root, MainButton/BackButton wired per-screen (context-sensitive primary action + back navigation), no `localStorage` (session token held in memory only, `state/session.ts`).

## State management
Server state (products, cart, orders, payments, user) is never cached beyond a single screen's lifetime except the cart module's re-fetch-on-mutation cache (`state/cart.ts`) — deliberately re-fetched rather than optimistically patched, so a stale price/stock value is never displayed as current. Local UI state (selected variant, form inputs, loading flags) lives in each screen's closure, not shared globally.

## Security
Every price/stock/permission decision is server-computed and server-enforced; the frontend only displays what the backend returns and never computes a price it then asks the backend to trust (checkout sends `client_unit_price` purely so the backend can *detect* a mismatch, per §7.3 — the field is never trusted). No admin/owner surface exists in this Mini App build. No `localStorage`. No `innerHTML` with dynamic content anywhere (`textContent` only, per §12.1).

## Error handling
`api/client.ts` maps every HTTP status to a typed `ApiErrorKind` (`unauthorized`/`forbidden`/`not_found`/`conflict`/`validation`/`server_error`/`network`); `components/error-state.ts` renders one of `src/locale.ts`'s generic Uzbek messages per kind, plus a retry action where applicable — no raw backend error body, stack trace, or internal URL is ever rendered.

## Tests
28 Vitest tests (`miniapp/tests/unit/`, `miniapp/tests/dom/`) — API client error mapping, cart reconciliation, price formatting, debounced search (no duplicate/stale requests), checkout price-mismatch/insufficient-stock recovery, loading/empty/error states. No real-browser/Playwright E2E this phase (see Phase-05 report "Known limitations") — end-to-end correctness verified instead via a real HTTP trace against the live backend (same rigor as Phase 03/04's manual traces).

## Deferred to later phases
Notifications (blocked on OPEN-7), Favorites/Order-history-list/Sell/Chat (P1, Phase 10), Admin Panel (Phase 06), Owner Dashboard (Phase 07), production Nginx/systemd serving (Phase 09).
