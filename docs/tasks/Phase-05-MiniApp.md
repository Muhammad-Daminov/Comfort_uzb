# Phase 05 — Mini App (User)

**Owner:** frontend
**Status:** ✅ Complete (Notifications screen deferred — OPEN-7)
**Last updated:** 2026-08-18
**Dependencies:** [Phase-03-Backend.md](Phase-03-Backend.md)

## Objective
Build the USER-facing Mini App screens (§14.1): Home, Catalog, Search, Filter, Product detail, Favorites, Cart, Checkout, Payment, Receipt upload, Order history/detail, Sell, Chat, Profile, Notifications, Settings — P0 screens first, P1 (favorites, chat, sell) layered once `backend-engagement` ships.

## Prerequisites
- Phase 03 API surface stable enough to build against (`docs/04_API_SPEC.md`).

## Deliverables
- USER screen set, mobile-first from 375px, Telegram theme-adaptive.
- Client-side image compression for uploads (§14.3).
- Signed-URL image handling with expiry re-fetch.
- `docs/06_MINIAPP_SPEC.md` written (screen-by-screen).

## Definition of Done
- [x] All P0 USER screens implemented and functional against the real backend (not mocked), except Notifications (OPEN-7, blocked — see `docs/06_OPEN_DECISIONS.md`). Order history *list* not built (P1-tagged); Order detail (P0) is reachable via a direct post-checkout link and a "most recent order" link on Home.
- [x] First-load payload <400KB (§18) — production bundle measured at ~23KB (~7.4KB gzip), file-verified. First-paint timing not measured (no real-device profiling tool run this phase — see final report "Known limitations").
- [x] No `localStorage` usage; no client-trusted price/permission logic — `client_unit_price` is sent only so the backend can *detect* a mismatch (§7.3), never trusted back.
- [ ] Real-device (mobile) UX check performed, not simulator-only (§24 DoD item) — not performed this phase; verification was a real HTTP trace against the live backend plus automated tests, not an on-device visual check. Flagged as a known limitation, not silently skipped.

## OPEN-7 (new, this phase)
Notifications screen tagged P0 in `docs/02_FEATURE_INVENTORY.md`, but its endpoint is explicitly `backend-engagement`-owned (P1) — a genuine contradiction between two source-of-truth docs, not resolved silently. See `docs/06_OPEN_DECISIONS.md` OPEN-7.

Test totals: 28 Vitest (frontend, new) + 112 backend (46 unit + 33 db + 33 integration — 4 new integration tests for `GET /auth/me` and signed product images) = 140 automated tests, plus one manual end-to-end HTTP trace of the full customer journey against the live backend.

## Audit corrections (2026-09-19)
Full detail, evidence and regression tests: `docs/11_FULL_SYSTEM_AUDIT_REPORT.md`.
- `api/client.ts` never parsed the backend's `{"detail": …}` bodies, so `ApiError.code` was always null and the checkout's PRICE_MISMATCH/INSUFFICIENT_STOCK branches were dead (F1); checkout sent the base price so discounted items could not be ordered (F2).
- Router now mounts a fresh element per navigation and resets the MainButton (F3/F4 — a stale screen's async render clobbered the new screen; "Savatga qo'shish" stayed live on Home). Mutating MainButton handlers have an in-flight guard and a stable Idempotency-Key per attempt (F6); `uuid()` helper replaces bare `crypto.randomUUID` (F7); broken signed images refetch once (F5); cart/product-detail/product-editor failures are shown instead of swallowed (F8); retry no longer stacks a second copy of the screen (F9); receipt upload falls back to the raw file when the WebView cannot decode it (F10); unpaid orders can be cancelled from order detail (F11); owner finance/analytics `to` day is inclusive and admin dashboard counters use `limit=200` (F12).
