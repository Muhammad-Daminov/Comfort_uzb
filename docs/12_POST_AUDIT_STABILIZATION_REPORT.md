# COMFORT UZB — POST-AUDIT STABILIZATION & FULL VERIFICATION REPORT

**Date:** 2026-09-19 · **Predecessor:** `11_FULL_SYSTEM_AUDIT_REPORT.md` (treated as evidence only; every item re-verified independently on a fresh disposable database, `comfort_audit`, created → provisioned → migrated → seeded → exercised over real HTTP → dropped). No AI code was added.

---

## A. CURRENT SYSTEM STATUS

The system is internally consistent and its P0 flows work end to end under test: auth (initData HMAC, tamper/expiry/replay), RBAC for all three roles on every endpoint, catalog/pagination/search, cart, checkout with discounts, idempotency (including concurrent same-key and retry-after-500), payments and receipts, admin review with the full legal/illegal state-transition matrix, order confirm (sequential and 4-way concurrent), reservation consumption, expiry worker, inventory ledger invariants, owner reporting, bot webhook/poller (2 uvicorn workers), migrations up/down/up with a `%`-encoded DSN, backup and restore drill. All 37 previously reported fixes hold. This pass found **3 new implementation defects** (fixed) and **1 new design limitation** (documented, not fixed). The four previously open business decisions are still open and are restated in §D — none was decided here.

Current state map (entry points → services → data → auth → tests):

| Domain | Entry points | Service / data access | Authorization | Invariants | Tests |
|---|---|---|---|---|---|
| USER identity | `POST /auth/session`, `GET /auth/me`; bot `/start`, contact | `identity/{service,repository}` | HMAC initData (ADR-2), HMAC session token, role re-read per request | one USER row per telegram_id; deactivated → 403 | unit `test_telegram_auth/test_session`, integration `test_auth_me`, `test_security_suite` |
| ADMIN | `/admin/*` (orders, payments, inventory, catalog CRUD) | commerce/catalog/payments services | `require_permission(key)` from `role_permissions` | stock only via `/admin/inventory/adjust` | `test_admin_*`, `test_permissions`, matrix harness |
| OWNER | `/owner/*` | `owner/{service,repository}` (read-only aggregation + admins/settings writes) | `finance.view`, `analytics.view`, `admins.manage`, `audit.view`, `settings.manage` — OWNER only | exactly one OWNER (partial unique index); OWNER row never demotable | `test_owner_*`, matrix harness |
| BOT | `POST /telegram/webhook` (secret header), in-process poller | aiogram dispatcher; `notifications` outbox | webhook secret (constant-time) | exactly-once claim via `FOR UPDATE SKIP LOCKED` | unit poller/start/webhook, `test_notification_delivery` |
| FRONTEND | `miniapp/src/main.ts` → hash router → screens | `api/*.ts` over `client.ts` | bearer token in memory; UX gates only | fresh mount per navigation; MainButton reset; one in-flight mutation | vitest 127 |
| DATABASE | 16 Alembic migrations; roles `comfort_app` (no DELETE/DDL), `comfort_migrate`, `comfort_backup` | asyncpg pool | grants + default privileges | CHECKs on stock/money, audit trigger | `tests/db` 34 (+ E2E, env-blocked) |
| PAYMENTS | `POST /payments`, `/payments/{id}/receipt`, `/admin/payments*` | `payments/{service,repository}` | owner-of-order / `payments.review` | PENDING→APPROVED\|REJECTED one-way; one PENDING per order; order locked FOR UPDATE | `test_payment_review`, `test_audit_regressions` |
| ORDERS | `/orders*`, `/admin/orders*` | `orders/{service,repository,state_machine}` | owner / `orders.view.all|confirm|cancel` | §8.1 transition table; snapshot (ADR-5) | `test_order_*`, `test_audit_regressions` |
| INVENTORY | confirm, cancel, expiry worker, `/admin/inventory/adjust` | `reservations/repository`, `inventory/repository`, `workers/reservation_expiry` | as above | `stock_reserved == Σ open reservations`; never negative; append-only ledger | `test_inventory_concurrent_adjust`, `test_reservation_expiry`, p6 invariant test |
| CATALOG / SEARCH | `/catalog/*` (public), `/vehicles/*` | `catalog/{service,repository}`, `pricing/*` | public | §7.2 discount resolution in Python only, listing = search card shape | `test_catalog_images`, `test_audit_regressions` (H1/H5/H7/p1/p2/p5) |
| CHAT / NOTIFICATIONS (user-facing) | none (P1) | `notifications` table + poller consumer only | — | — | DEFERRED BY SPEC |
| ANALYTICS / FINANCE | `/owner/finance`, `/owner/analytics`, `/owner/dashboard` | `owner/repository` | OWNER | revenue = Σ `orders.paid_amount` | `test_owner_dashboard_finance_analytics` |
| DEPLOYMENT | `deploy/nginx`, `deploy/systemd`, `deploy/scripts` | — | — | — | `bash -n`, backup/restore drill; Nginx/systemd NOT runtime-verifiable here |

---

## B. PREVIOUS AUDIT FINDINGS

| ID | Finding | Current State | Evidence (this pass) | Fix | Test |
|---|---|---|---|---|---|
| H2 | Confirm never consumed reservations; worker double-released | FIXED AND VERIFIED | matrix: confirm → `unreleased=0`, worker `released=0`, stock unchanged; invariant `stock_reserved == Σ open` holds after create/cancel/expire/confirm | consume-on-confirm, guarded decrement, worker backstop | `test_h2_*` ×4, `test_p6_*` |
| H1 | Catalog page 2 → 500 (`p.id`), string timestamp cursor | FIXED AND VERIFIED | pagination walk: 4 sorts × 2 walks, all products once, stable, malformed cursor 422, empty page 200 | `id` in predicate, datetime decode | `test_h1_*` ×4, `test_p5_*` |
| H3 | `{"detail"}` vs spec `{"error"}` envelope | FIXED AND VERIFIED | 401/403/404/409/422/500 all carry `error.code`; frontend parses | `error_body()` | `test_h3_*`, `audit-regressions.test.ts` |
| H4 | Discounted items could not check out | FIXED AND VERIFIED | card `min_price` == detail `current_price` == cart `current_price` → 201, snapshot `unit_price/discount_amount/line_total` consistent, payment amount discounted | cart `current_price` | `test_h4_*`, checkout DOM test |
| H5 | Search: `%` threshold + bare rows ("NaN so'm") | FIXED AND VERIFIED, then **extended** (multi-word, see §C-1) | one-word, partial, typo, Cyrillic, multi-word all hit; prices numeric | per-word `<%` with alias mapping | `test_h5_*`, `test_p1_*` |
| H6 | Rejected payment left order UNDER_REVIEW; approve on dead orders | FIXED AND VERIFIED | matrix: reject → REJECTED; approve on CANCELLED/EXPIRED → 422; approve twice → 422, `paid_amount` counted once | lock + transition + guard | `test_h6_*` ×2, `test_p4_*` |
| H7 | `total_available` inflated by joins | FIXED AND VERIFIED | product + 3 order lines + 2 compat + 2 images + 2 discounts + archived variant → exact | correlated subquery | `test_h7_*`, `test_p2_*` |
| H8 | Nginx cannot read `/var/comfort` (ownership) | FIXED (config) — NOT VERIFIABLE at runtime | `bootstrap.sh` sets `comfort:www-data`, 0750, setgid; app writes 0640/0750 (verified on disk) | — | `test_upload_size_cap_*` (modes) |
| M1 | Idempotency race | FIXED AND VERIFIED | 5 concurrent same-key → 1 order (test), 4 concurrent (harness); cross-user replay 422; different payload 422; retry after 500 → clean run, then replay | `idempotent_scope` | `test_m1_*` ×2, `test_p3_*` |
| M2 | Duplicate PENDING payments | FIXED AND VERIFIED | second submit returns the same payment; 1 row | existing-PENDING return | `test_m2_*` |
| M3 | Cart never cleared | FIXED AND VERIFIED | cart empty after 201 | soft-delete ordered lines | inside `test_h4_*` |
| M4 | Soft-deleted compatibility priced discounts | FIXED AND VERIFIED | listing == checkout price | filter | `test_m4_*` |
| M5 | Duplicate/looping poller | FIXED AND VERIFIED (DB level) | `--workers 2` live: one send attempt per cycle, not two; SKIP LOCKED proof; permanent errors handled, 429 pauses | locked batch fetch | poller unit ×8 |
| M6 | Admin lists capped at 20 | FIXED AND VERIFIED | `limit=200` → 25 rows; 201 → 422 | `limit` param | `test_m6_*` |
| M7/F12 | Owner `to` day excluded | FIXED AND VERIFIED (frontend) | `exclusiveEnd` | — | `audit-regressions.test.ts` |
| M8 | Contact `user_id=None` accepted; no typed-phone path | FIXED AND VERIFIED | unit tests | reject + typed handler | `test_start_handler` +4 |
| M9 | Webhook 500 on malformed body | FIXED AND VERIFIED | smoke: 400; wrong secret 401 | 400 + `compare_digest` | `test_bot_webhook` +1 |
| M10 | Concurrent set-primary 500 | FIXED AND VERIFIED | 2×10 interleaved flips, exactly one primary | product row lock | `test_m10_*` |
| M11 | 500 request-id "-" ; hostile header | FIXED AND VERIFIED | `request_id` echoed on 500; 500-char header replaced | `_request_id_for` | `test_m11_*` ×2 |
| M12 | DB suites errored instead of skipping | FIXED AND VERIFIED | 247 skipped with env unset | collection hook | — |
| M13 | Alembic `%` in DSN | FIXED AND VERIFIED | `alembic current` with `%5F`-encoded password over TCP as `comfort_migrate` → head | `%%` escape | manual (documented command) |
| M14 | `provision_roles.sql` no ON_ERROR_STOP | FIXED AND VERIFIED | script ran with `-v ON_ERROR_STOP=1` semantics; suite passes | `\set` | `test_provision_roles_quoting` |
| U1 | Unbounded upload buffering | FIXED AND VERIFIED | 5 MB + 10 B → 422 | streamed cap | `test_upload_size_cap_*` |
| L1 | 200 vs 201 | FIXED AND VERIFIED | smoke | — | smoke |
| L2 | Purge path guard inverted | FIXED (reviewed) | code | — | existing `test_receipt_purge` traversal test |
| L3 | Malformed cursor 500 | FIXED AND VERIFIED | 422 | — | `test_h1_*` |
| F1–F12 | Frontend (envelope, prices, MainButton leak, async clobber, image loop, double tap, uuid, rejections, retry stacking, HEIC fallback, cancel button, dates/limits) | FIXED AND VERIFIED (jsdom) — on-device NOT VERIFIED | vitest 127/127, tsc, build | — | `audit-regressions.test.ts`, checkout/cart tests |
| D1 | Nginx zones shadowed; `cart/items` as upload; `http2 on`; HSTS on `/files/` | FIXED (config) — NOT VERIFIABLE at runtime | see §I | `^~`, nested receipt location | — |
| D2 | backup/deploy unrunnable from documented env | FIXED AND VERIFIED (backup) / FIXED (deploy guard) — but see §C-2 | `backup.sh` with the `.env.example` variables produced a dump + files archive; restore drill into a throwaway DB OK; without `DATABASE_NAME` it exits 1 with the documented message | — | manual |
| D3 | `receipt_purge` root guard | FIXED | code | — | — |
| Seed `search_text` | Seed left search empty | FIXED AND VERIFIED | 0/12 empty after seed | rebuild in seed | — |
| R-1 | Confirm without approved payment | BUSINESS DECISION REQUIRED (OPEN-8) | matrix: UNDER_REVIEW + PENDING payment → confirm 200, `paid_amount` 0 | — | — |
| R-2 | User cancel after approved payment | BUSINESS DECISION REQUIRED (OPEN-9) | matrix: APPROVED + UNDER_REVIEW → user cancel 200, reservation released, money stays | — | — |
| R-3 | `find_or_create_user` on soft-deleted row | NOT REPRODUCIBLE (no soft-delete path for users exists) | code | — | — |
| R-4 | Duplicate variant lines / opposite-order deadlock | NOT REPRODUCIBLE from the Mini App; still possible via raw API | code | — | — |
| DB-1, DB-2, D-4, D-5, S-1, S-2 | Downgrade 0016 data-dependent; 0002 non-numeric id; operator items; no idempotency-cleanup worker; token on CLI; disclosed dev token | NOT FIXED (unchanged, documented) | — | — | — |
| Docs (12) | see `11_…` §10 | 9 fixed previously + 3 fixed now (ADR-014 receipts layout, `smoke_test.py` claim, `AGENTS/devops.md` Restart=) → **0 remaining** from that list | — | — | — |

---

## C. NEW BUGS FOUND

**C-1 · MEDIUM · `backend/app/domains/catalog/repository.py::search_products`** — Multi-word queries only matched when the words were adjacent in `search_text`: `"nexia gilam"` (car model + product) returned nothing although both terms are present. · Repro: seed, `GET /catalog/search?q=camry%20gilam` → `[]`. · Root cause: a single phrase-level `<%` against the whole query. · Fix: query split into words, each mapped through `search_aliases` (normalized and as typed), every word must `<%`-match, ranked by average word similarity. · Test: `test_p1_multi_word_search_requires_every_word_and_maps_aliases`.

**C-2 · HIGH (deploy) · `deploy/scripts/deploy.sh`** — the `OWNER_TELEGRAM_ID` guard added by the previous audit contained an apostrophe inside a `${VAR:?message}` word; `bash -n` failed with "unexpected EOF while looking for matching `'`" — the script could not run at all. Introduced by the previous pass, caught only now because that pass never ran `bash -n` on the edited file. · Fix: apostrophe removed. · Test: `bash -n deploy/scripts/deploy.sh` (passes); guard behaviour confirmed.

**C-3 · LOW · `backend/app/domains/catalog/router.py`** — `next_cursor` was emitted for every non-empty page, so the last page always offered "Ko'proq ko'rsatish" that fetched an empty page. · Fix: no cursor when the page is shorter than `limit`. · Test: `test_p5_last_page_has_no_next_cursor`.

**C-4 · LOW · `backend/bot/handlers/start.py`** — one raw `SELECT phone FROM users` contradicted `AGENTS/bot.md`'s "no direct SQL" DoD. · Fix: reads via `identity.repository.get_by_id`. · Test: existing `test_start_handler` (87 unit pass).

**Design limitation found (not fixed): `sort=price_asc|price_desc` orders by the base minimum price while cards display the discounted price**, so a discounted product can appear out of strict display order. The keyset cursor must sort on a value computable in SQL, and §7.2's discount resolution is deliberately kept out of SQL (CLAUDE.md). A correct fix needs a maintained `current_min_price` column (written on discount/variant changes) — an ADR-level change, recorded in `04_API_SPEC.md` as a known limitation. The matrix harness prints two expected FAIL lines for it.

---

## D. BUSINESS DECISIONS REQUIRED

**OPEN-8 — Must order confirmation require an APPROVED payment?**
Current behaviour (verified by the transition matrix): an admin can confirm an `UNDER_REVIEW` order whose payment is still `PENDING` (receipt uploaded, not yet approved); the order becomes `CONFIRMED` with `paid_amount = 0`; the payment can still be approved afterwards (200). TZ §8.1 gives `UNDER_REVIEW → CONFIRMED | REJECTED`, §8.2 specifies the confirm transaction, §8.3 specifies payment review — but never their relationship. ADRs are silent. Options: (a) require `payments.status = 'APPROVED'` in `confirm_order` (422 otherwise); (b) auto-confirm on approve inside the same transaction; (c) keep two independent actions. Technical recommendation: (a) — smallest change, makes `CONFIRMED` imply money was accepted, which the future AI "sales summary" tool will need to trust. Not changed.

**OPEN-9 — Can a user cancel an UNDER_REVIEW order after its payment was APPROVED?**
Current behaviour (verified): yes — 200, reservation released, `paid_amount` remains on a `CANCELLED` order and is counted as revenue by `/owner/finance` and `/owner/dashboard`. P0 has no refund state (OPEN-4). Options: (a) forbid user cancel once `paid_amount > 0` (admin-only from then on); (b) allow and exclude `CANCELLED` orders from revenue; (c) pull `REFUND_PENDING` forward. Recommendation: (a). Not changed.

**OPEN-10 (new) — Cost price / negotiated sale price are not representable** (see §G). Deciding whether the P0 data model gains `cost_price` on variants and an admin-set `actual_unit_price` on order lines is a business/product decision that the AI phase depends on. Not implemented.

**OPEN-11 (new) — Price sort semantics**: sort by base price (current) or by discounted price (requires a maintained column)? Technical, but affects what the customer sees; recorded as a limitation until decided.

---

## E. DOCUMENTATION ISSUES

Corrected in this pass: ADR-014 (receipts layout amendment), `deploy/scripts/smoke_test.py` docstring + `09_DEPLOYMENT.md` (it is read-only), `AGENTS/devops.md` (oneshot timers, not `Restart=on-failure`), `Phase-04-Bot.md` (raw SQL removed), `04_API_SPEC.md` (multi-word search, `next_cursor` semantics, price-sort limitation).

Checked and found consistent: `01_REQUIREMENTS_MAP.md` has no duplicate IDs (the two repeated `REQ-PRC-001`/`REQ-TST-001` mentions are explicit cross-reference rows of merged requirements, 122 unique IDs); feature-inventory counts (13 P0 USER screens, 7 P0 ADMIN) are internally consistent; OWNER analytics/finance ownership is `backend-core` (AGENTS/backend-core.md) and the code matches; bot ↔ backend-engagement dependency is resolved by ADR-016 (outbox); DB/grant ownership: `database` owns migrations, `provision_roles.sql` is the single grant source and `0011` narrows `audit_logs` — no conflicting statements found.

Remaining, deliberately left: the `13 P0 USER screens` list includes "Notifications" while its endpoint is P1 (OPEN-7 — the inventory tag is the artifact to correct once OPEN-7 is decided); `docs/06_MINIAPP_SPEC.md` still lists screens the app does not have (Notifications) — tied to the same decision.

---

## F. SECURITY / RBAC STATUS

Verified over real HTTP (matrix harness + smoke + `test_security_suite`):

- **USER**: 403 on all 19 staff mutation/list endpoints tested (`/admin/orders*`, `/admin/inventory/adjust`, products/variants/brands/colors/compatibilities/images/payments review/receipt URL) and on all 10 owner endpoints; cannot self-promote via body fields; cannot read/cancel/pay another user's order (403); cannot patch another user's cart item (404 — existence not leaked); same Idempotency-Key replayed by a different user → 422 (no cross-user replay); tampered `user.id` / added fields → 401 (hash mismatch); stale/future `auth_date` → 401.
- **ADMIN**: 403 on all 10 owner endpoints (dashboard, finance, analytics, admins list/create/deactivate/reactivate, audit, settings GET/PUT); allowed on orders/payments/inventory/catalog per §3; cannot set stock through variant CRUD; deactivation invalidates an existing token immediately and blocks new sessions.
- **OWNER**: all owner endpoints 200; cannot demote/deactivate the OWNER row (422/404); role never taken from request bodies.
- `GET /admin/products/{id}/compatibilities` is reachable by USER by design (`catalog.view`, per spec) — public data, noted, not a defect.
- Webhook: wrong/missing secret → 401 (constant-time); malformed body → 400.
- Secrets: no token pattern anywhere outside `backend/.env.local` (gitignored, confirmed by `git check-ignore`); the bot token there is self-described as disclosed → **SECRET ROTATION REQUIRED** (not rotated). Zero commits exist in the repository — nothing is committed, so nothing is leaked via git, but nothing is versioned either.

---

## G. FINANCIAL INTEGRITY STATUS

| Concept | Representation today | Status |
|---|---|---|
| Sale price | `order_items.unit_price` (base, snapshot) + `discount_amount` per line; `line_total = unit_price*qty − discount`; `orders.total_amount` | SUPPORTED (server-side, snapshot, re-validated at checkout) |
| Discounts | `discounts`/`discount_targets`, §7.2 resolver, snapshot per line | SUPPORTED |
| Revenue | `orders.paid_amount` (Σ approved payments), summed by `orders.created_at` in `/owner/finance`, `/owner/analytics`, `/owner/dashboard` | PARTIALLY SUPPORTED — counts money on CANCELLED orders (OPEN-9); windowed by order creation date, not payment approval date; no per-day cash-received view |
| Cost price / COGS / gross profit | **no `cost_price` column anywhere** (`product_variants`, `order_items`, TZ) | NOT SUPPORTED |
| Negotiated (actual) sale price ≠ catalog price | no override field; the only lever is a `discounts` row (not per-order, not per-sale) | NOT SUPPORTED → REQUIRES BUSINESS DECISION (OPEN-10) |
| Inventory movements | `inventory_movements` append-only (IN/OUT/RESERVE/RELEASE/ADJUST, before/after, actor, reference); `stock_reserved == Σ open reservations` verified | SUPPORTED |
| Stock never negative / oversell | DB CHECKs + guarded UPDATEs; verified under concurrency | SUPPORTED |
| Example "BMW M5 cost 700 / sale 1200" | revenue 1200 and stock −1 representable; COGS 700 and profit 500 are not | PARTIALLY SUPPORTED |
| Example "catalog 1200 / actual 1000" | not representable without a per-order price override | NOT SUPPORTED |

The revenue figure is trustworthy as "money approved on orders", not as accounting revenue, until OPEN-9 is decided.

---

## H. TEST RESULTS

Environment: disposable `comfort_audit` (Postgres 16 local), `TEST_DATABASE_URL` = `comfort_app` over TCP, `SUPERUSER_DATABASE_URL` = local superuser over socket, fake `BOT_TOKEN`.

| Command | Result | Tests | Failures | Skipped | Known environment failures |
|---|---|---|---|---|---|
| `backend: pytest tests/unit -q` | PASS | 87 | 0 | 0 | — |
| `backend: pytest tests/integration -q` | PASS | 214 (29 in `test_audit_regressions.py`, 6 new this pass) | 0 | 0 | — |
| `backend: pytest tests/db -q --deselect tests/db/test_migration_role_e2e.py` | PASS | 34 | 0 | 3 (psql-dependent quoting cases skip without their env) | — |
| `backend: pytest tests/db/test_migration_role_e2e.py` (baseline run, previous pass) | FAIL | 2 | 2 | 0 | **environmental**: `pg_hba.conf` peer auth on the unix socket the superuser DSN uses; the test derives `comfort_migrate`'s DSN from it. Not re-run this pass because the suite **resets cluster-wide role passwords** (documented in its docstring); the same lifecycle was verified manually (below) |
| `backend: pytest tests/integration tests/db` with `TEST_DATABASE_URL` unset | SKIP | 247 skipped | 0 | 247 | — (M12 verified) |
| `alembic upgrade head → downgrade base → upgrade head → upgrade head` as `comfort_migrate` (SET ROLE) | PASS | — | — | — | 29 relations owned by `comfort_migrate` |
| `alembic current` with `postgresql+psycopg://comfort_migrate:<%-encoded pw>@127.0.0.1/comfort_audit` | PASS | — | — | — | `%` fix verified with a real encoded password over TCP |
| `miniapp: npx tsc --noEmit` | PASS | — | 0 | — | — |
| `miniapp: npx vitest run` | PASS | 127 (23 files) | 0 | 0 | — |
| `miniapp: npm run build` | PASS | — | — | — | 61 kB JS |
| `miniapp: lint` | NOT AVAILABLE | — | — | — | no lint script/config exists in `package.json` |
| `backend/scripts/audit_smoke.py` (HTTP, 98 checks) | PASS | 98 | 0 | — | — |
| `backend/scripts/audit_verify_matrix.py` (HTTP, 105 checks) | PASS with 2 documented FAILs | 103 | 2 (price-sort display limitation, §C) | — | — |
| `uvicorn --workers 2` live poller check | PASS | — | — | — | one send attempt per cycle across two workers |
| `bash -n` on all 6 deploy/dev scripts | PASS (after C-2 fix) | 6 | 0 | — | — |
| `deploy/scripts/backup.sh` with `.env.example` variables | PASS | — | — | — | dump (29 tables) + files archive produced; without `DATABASE_NAME` exits 1 with the documented message |
| `deploy/scripts/restore.sh` drill into `comfort_restore_drill` | PASS | — | — | — | row counts printed, DB dropped afterwards |
| Bot tests | PASS (part of unit: poller 8, start handler 11, webhook 4) | — | 0 | — | real Telegram NOT VERIFIED |

---

## I. NOT VERIFIED

- **Nginx runtime behaviour** (rate-limit zones, `^~` precedence, `secure_link` 403/410, SPA fallback, TLS, `http2` form): no `nginx` binary, docker or root here. The fix rests on nginx's documented matching order (regex locations beat prefix locations unless the prefix is `^~`) and on the signed-URL formula, which is verified mathematically (`tests/unit/test_signing.py`). Must be `nginx -t`'d and smoke-tested on the server.
- **systemd units, `bootstrap.sh`, `deploy.sh` end to end, `/var/comfort` permissions as seen by `www-data`**: no VPS/systemd/root. Only syntax and guard behaviour verified.
- **Real Telegram**: webhook delivery, Menu Button, `/start`, notification sends — fake token by design; `setWebhook` never called.
- **`test_migration_role_e2e.py`**: environment-blocked (peer auth) and cluster-mutating; not re-run.
- **On-device WebView**: rendering, safe areas, `window.prompt`/`confirm` on iOS; jsdom only.
- **Exactly-once Telegram delivery under 2 workers**: verified at the claim level (SKIP LOCKED, one attempt per cycle), not at the delivery level.

Environment note: the previous pass's E2E run left `comfort_migrate`/`comfort_backup` on this local cluster with the suite's test passwords (`comfort_app` restored automatically). This pass **used** that state (backup drill as `comfort_backup`, `alembic` as `comfort_migrate` over TCP) and did not change any credential. The original values are unknown to me and were not restored; the dev DB `comfort_verify` (12 products, head revision) still authenticates as `comfort_app`.

---

## J. REMAINING RISKS

1. OPEN-8/OPEN-9: `CONFIRMED` does not imply "paid", and cancelled orders keep their money in revenue — the finance numbers are not accounting-grade until decided.
2. No cost price / no negotiated price (OPEN-10) — profit is not computable at all today.
3. Nothing is committed to git; a disk failure loses the codebase. The dev bot token is disclosed and must be rotated.
4. Deploy layer is config-reviewed only; first real deploy must run `nginx -t`, check `www-data` can read `/var/comfort/{web,uploads}`, register the webhook, and run the backup timer once.
5. `idempotency_keys` grows unbounded (no cleanup worker, and `comfort_app` cannot DELETE — needs an ADR-7 decision on the cleanup role).
6. Price sort ignores discounts in display order (§C limitation).
7. A wrong/rotated `BOT_TOKEN` in production makes every notification a "transient" failure retried every 5 s with a traceback per row — noisy, not data-corrupting; watch the `comfort-api` journal after any token change.
8. Downgrade of migration 0016 is data-dependent (DB-1) — do not rely on `alembic downgrade` in production without checking cart state.

---

## K. AI READINESS

1. **Is the backend safe enough to expose domain operations as AI tools?** Yes for *reads* and for the *existing* transactional writes, with two conditions: every tool must call the Service layer with an authenticated `CurrentUser` (never the repositories), and the OPEN-8/OPEN-9 decisions must be made first if the AI will report finance figures. All money math, stock math, state transitions, idempotency and audit writes are server-side and transactional today; the AI layer must add nothing to them.
2. **Candidate tools (existing services, unchanged):**
   - `search_catalog(q)` → `catalog.service.search_products`; `get_product(id)` → `catalog.service.get_product_detail`; `list_products(filters)` → `catalog.service.list_products`
   - `get_inventory(variant_id | product_id)` → `catalog.repository.get_variant` / `get_variants_for_product` (stock_on_hand, stock_reserved, available)
   - `adjust_inventory(variant_id, delta, reason)` → `inventory.repository.adjust_stock` inside `idempotent_scope` + `record_audit` (exactly what `POST /admin/inventory/adjust` does)
   - `get_order(id)`, `list_orders(status, limit)` → `orders.repository.get_order` / `list_all_orders`; `confirm_order`, `cancel_order` → `orders.service`
   - `review_payment(id, approve, reason)` → `payments.service.review_payment`
   - `get_sales_summary(from, to)`, `get_dashboard()` → `owner.service.get_finance` / `get_analytics` / `get_dashboard`
   - `record_sale(...)` **does not exist** — there is no in-store/POS sale path; only the Mini App checkout creates orders. Adding it is a new business feature (and needs OPEN-10).
   - `get_profit_summary()` **cannot exist** until cost price is modelled.
3. **Data-model changes needed before AI (all business decisions, none made here):** `product_variants.cost_price` (BIGINT, ADR-3) and `order_items.cost_price_snapshot`; a per-line actual/negotiated `unit_price_override` with audit; a `sales`/POS path if the AI must "record a sale" outside the Mini App; an idempotency-key cleanup role; optionally a maintained `current_min_price` for price sorting.
4. **Invariants AI must never bypass:** stock changes only through `adjust_stock` (reason, audit) or the order confirm/cancel/expiry paths; `stock_reserved == Σ open reservations`; no negative stock; §8.1 transition table only; APPROVED never reverts; one PENDING payment per order; prices recomputed server-side (§7.3) — the AI never supplies a price; every write inside the same transaction as its audit row; `comfort_app` role (no DELETE/DDL); OWNER-only finance/analytics/admins — the AI acts *as* the calling user, never with a service account that outranks them.
5. **Confirmation rules for AI actions:** reads never need confirmation; any write must echo the exact Service call and arguments and wait for an explicit "yes" from a user whose role has the permission; the AI must carry an `Idempotency-Key` per confirmed intent (so a repeated "yes" replays instead of re-executing); writes are refused when the tool would need a permission the user lacks.
6. **Always require explicit confirmation:** `adjust_inventory` (any delta), `confirm_order`, `cancel_order`, `review_payment` (approve/reject), admin creation/deactivation, settings changes, any future `record_sale`/price override, anything touching money or stock. Never auto-execute on voice input alone.

---

## L. FINAL VERDICT

**READY WITH DOCUMENTED RISKS**

The implementation is stable, internally consistent and tested for everything the AI layer would call (reads and the existing transactional writes). It is *not* ready to answer profit or negotiated-price questions, and its revenue figure is only accounting-grade once OPEN-8 and OPEN-9 are decided — those, plus the un-versioned repository and the un-rotated dev token, are the documented risks.
