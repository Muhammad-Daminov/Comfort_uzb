# 04 — API Spec (Phase 03–07)

**Purpose:** Endpoint-by-endpoint contract for the backend surface built through Phase 07. Split from Master TZ §13.4/§13.5. Matches `backend/app/domains/*/router.py` exactly — update this file in the same change whenever a route changes.
**Owner:** backend-core (auth/catalog/vehicles/admin-catalog/owner), backend-commerce (cart/orders/payments/admin)
**Last updated:** 2026-09-29 (v2 rebuild: cancellation/refund, cost price, AI admin assistant — see `13_V2_REBUILD_AUDIT.md`, `adr/ADR-017-post-confirmation-cancellation-refund.md`)
**Dependencies:** [00_MASTER_TZ.md](00_MASTER_TZ.md) §13.4, §13.5, §7.3, §8, ADR-2, ADR-5, ADR-6, ADR-7, ADR-9, ADR-11, ADR-13, ADR-15

## Conventions
- Auth: `Authorization: Bearer <session token>` from `POST /auth/session`, except that endpoint itself. Missing/invalid/expired token → `401`.
- Permission failures (§3 matrix) → `403`.
- **Every** error response (401/403/404/409/422/500) carries the §13.5 envelope `{"error": {"code", "message", "details"}}` at the top level, produced centrally by `app/observability.py::error_body`. FastAPI's `detail` key is kept alongside with the same information for compatibility. Generic codes: `UNAUTHORIZED`, `FORBIDDEN`, `NOT_FOUND`, `CONFLICT`, `VALIDATION_ERROR`, `INTERNAL_ERROR`; endpoint-specific codes (`PRICE_MISMATCH`, `INSUFFICIENT_STOCK`, ...) are listed per endpoint. (Audit 2026-09-19: until then only `{"detail": ...}` was sent and the Mini App never saw an error code.)
- Mutating endpoints listed in ADR-7 require `Idempotency-Key: <uuid v4>`; a repeated key with the same request body replays the stored response, a repeated key with a different body → `422 IDEMPOTENCY_KEY_REUSED`.
- Money fields are integer so'm (ADR-3). Timestamps are UTC ISO-8601.

## Identity (backend-core)

### `POST /auth/session`
- Body: `{"initData": "<Telegram initData string>"}`
- Verifies HMAC per ADR-2. First-ever login creates a `USER`-role row.
- 200: `{"token": "...", "user_id": 1, "role": "USER"}`
- 401: invalid/expired/tampered initData. 403: account deactivated.

### `GET /auth/me`
- Added in Phase 05 (Mini App Profile/Settings screens needed the caller's own phone/name, which `POST /auth/session`'s minimal response deliberately omits).
- 200: `{"id", "telegram_id", "first_name", "last_name", "username", "role", "phone", "status"}`. 401: no/invalid session token.

## Catalog (backend-core)

### `GET /catalog/products`
- Query: `car_brand_id?, car_model_id?, brand_id?, color_id?, price_min?, price_max?, in_stock_only?, sort? (newest|price_asc|price_desc|popular, default newest), cursor?, limit? (default 20, max 100)`.
- `next_cursor` is `null` when the page is shorter than `limit` (last page); a full page may still be followed by an empty one. Malformed cursor → 422. `price_asc`/`price_desc` sort on the **base** (pre-discount) minimum price — the displayed `min_price` is discounted, so a discounted card can appear out of strict display order (known limitation, see `12_POST_AUDIT_STABILIZATION_REPORT.md`).
- Cursor pagination only — no `OFFSET` (REQ-PERF-002). Product-level listing: one row per product, aggregating its ACTIVE, non-deleted variants (`min_price`, `total_available`).
- 200: `{"items": [...], "next_cursor": "<opaque>|null"}`.
- **Card fields** (added for the Mini App's catalogue grid, `docs/DESIGN.md`):
  - `brand_name` — product brand, or `null` if the brand row is archived. The join is `LEFT` on purpose: archiving a brand must never make its products disappear from the catalogue.
  - `min_price` — the **discounted** minimum, computed by the same `resolve_price` (§7.2) the detail endpoint and checkout use. Previously this was the pre-discount minimum, so a discounted product showed one price in the grid and a lower one on its page. §7.2 is never re-expressed in SQL; the listing service fetches variants, compatible car models, and discount candidates in **three bulk queries per page** (never per product) and resolves in Python.
  - `old_price` — the pre-discount price of whichever variant is cheapest after discount, or `null` when nothing applies. Note the cheapest variant after a discount is not necessarily the cheapest before one, so both come from the same resolved variant.
  - `fitment_summary` — up to two compatibilities, newest generation first, formatted `"Nexia 3 2016–2024"` / `"Nexia 3 2016+"` (no end year) / `"Nexia 3"` (no years at all — a missing year must not delete the entry). When the request filters by `car_model_id`, that model is pinned first so a buyer searching for their car sees it on the card.
  - `fitment_total` — total active compatibilities, so the card can show "yana N ta" instead of silently hiding the one the buyer wanted.
- **Performance**: the per-product subqueries (image, fitment) run on the OUTER query, after `ORDER BY`/`LIMIT` — inside the aggregate they executed once per *matching* product (measured: 72 ms of an 80 ms query at 2 000 products). Measured p95 at 2 000 products / 8 000 compatibility rows: **6.7–7.3 ms**.
- Each item also carries `primary_image_url` — the product's primary image (`is_primary` first, then `sort_order`/`id` for a stable pick), signed with the same `signed_url_for_folder(..., "products")` helper the detail endpoint uses (ADR-13: no file is ever served unsigned), or `null` when the product has no image. The raw `storage_path` is never returned by this endpoint. Added because the Mini App's catalog/home grids render product cards, and a storefront listing with no thumbnails is not usable; the original spec only signed images on the detail endpoint. Test: `tests/integration/test_catalog_images.py`.

### `GET /catalog/products/{id}`
- 200: `{"product": {...}, "variants": [{..., "current_price", "discount_amount"}], "images": [{..., "signed_url"}]}` — `current_price` computed via `resolve_price` (§7.2), same function checkout re-validation uses. `images[].signed_url` added in Phase 05 (ADR-13: no file served unsigned) — the Mini App re-fetches the product on a 403/410 from the signed URL rather than caching it past its TTL.
- 404: product not found or soft-deleted.

### `GET /catalog/search?q=`
- ADR-8: query normalized (Cyrillic→Latin, apostrophe variants), split into words; each word is mapped through `search_aliases` (looked up both normalized and as typed) and must match `products.search_text` by pg_trgm **word** similarity (`<%`) — all words required, order-free ("nexia gilam" ≡ "gilam nexia"); ranked by average word similarity. Whole-string `%` similarity scored a one-word query at ~0.2 against the long search_text and returned nothing, and a phrase-level `<%` only matched adjacent words (audit 2026-09-19, stabilization pass).
- 200: `{"items": [...]}` — the same card shape as `GET /catalog/products` items (`min_price` discounted, `old_price`, `total_available`, `brand_name`, `fitment_summary`, `primary_image_url`), ranked by similarity, max 20. (Previously bare `id/name/brand_id` rows, which the Mini App rendered as "NaN so'm".)

### `GET /catalog/filters`
- 200: `{"brands": [...], "colors": [...], "car_brands": [...]}`

## Vehicles (backend-core)

### `GET /vehicles/brands`
### `GET /vehicles/models?car_brand_id=`
### `GET /vehicles/generations?car_model_id=`
- 200: `{"items": [...]}` each.

## Cart (backend-commerce)

One cart per user, auto-created on first access. `cart_id` is always derived server-side from the authenticated session, never from client input — cross-user cart access is structurally impossible, not just permission-checked.

### `GET /cart` — 200: `{"items": [{cart item + joined variant/product fields, "price" (base), "current_price", "discount_amount", "primary_image_url"}]}` — excludes soft-deleted items. `current_price` is the §7.2-resolved unit price, the value the Mini App sends back as `client_unit_price` (audit 2026-09-19: the cart only exposed the base price, so every discounted item 409'd at checkout).
### `POST /cart/items` — body `{"variant_id", "quantity"}` (upsert on `(cart_id, variant_id)` among non-deleted rows — re-adding a variant after removing it is a fresh row, not a conflict with the old soft-deleted one). 422 if quantity ≤ 0.
### `PATCH /cart/items/{id}` — body `{"quantity"}`. 404 if not the caller's item or already removed.
### `DELETE /cart/items/{id}` — soft-delete (`cart_items.deleted_at`, migration `0016_cart_items_soft_delete`, Phase 08 — a real `DELETE` here fails against `comfort_app`'s zero-DELETE privilege, §12.2; this was a live bug, found and fixed). Idempotent: 404 on a second removal of the same item, not an error. 404 if not the caller's item (never leaks whether it exists for someone else).

## Orders (backend-commerce)

### `POST /orders` [Idempotency-Key]
- Body: `{"lines": [{"variant_id", "quantity", "client_unit_price"?}]}`.
- §7.3 re-validation per line: variant + product `ACTIVE`, `available >= qty`, current price recomputed via `resolve_price`. If `client_unit_price` was sent and doesn't match → **409** `PRICE_MISMATCH` with the corrected price, nothing written. Otherwise: order + `order_items` snapshot (ADR-5) written, `stock_reservations` created with `expires_at = now()+24h`, `stock_reserved` incremented via a guarded atomic UPDATE (never read-then-write), `inventory_movements` RESERVE row, audit row — all one transaction.
- 201: order object. 409: `PRICE_MISMATCH` or `INSUFFICIENT_STOCK` (lost the race for remaining stock). 422: inactive variant / bad request shape.
- The ordered variants are removed (soft-deleted) from the caller's cart in the same transaction.
- Idempotency: check → run → store is one transaction under a `pg_advisory_xact_lock` on the key, so concurrent same-key requests execute the Service call once and the rest replay (`app/security/idempotency.py::idempotent_scope`; same for every `[Idempotency-Key]` endpoint below).

### `GET /orders` — own orders, newest first.
### `GET /orders/{id}` — 403 if not own and caller lacks `orders.view.all`. 404 if missing.

### `POST /orders/{id}/cancel`
- Body: `{"reason"}` (≥10 chars, §8.4 — DB CHECK is the backstop).
- Releases every active reservation via the mandatory guarded pattern (`AGENTS/backend-commerce.md`): decrement `stock_reserved` only if the release UPDATE actually affected a row.
- 200: updated order. 403: not the order's owner. 404: order not found. 422: bad reason / invalid transition (§8.1 table).

## Admin — Orders (backend-commerce, `orders.confirm`/`orders.cancel`/`orders.view.all`)

### `GET /admin/orders?status=&limit=` — requires `orders.view.all`. `limit` default 20, max 200.
### `POST /admin/orders/{id}/confirm` [Idempotency-Key] — requires `orders.confirm`.
- Exact §8.2 pattern: `SELECT ... FOR UPDATE`, guard `status = 'UNDER_REVIEW'`, guarded `UPDATE orders SET status='CONFIRMED'`, guarded stock decrement (`stock_on_hand -= qty, stock_reserved -= qty`, 409 `INSUFFICIENT_STOCK` if the reserved units are no longer held), the order's `stock_reservations` rows **consumed** (`released_at` stamped — ADR-006 amendment), `inventory_movements` OUT row, audit row — one transaction.
- 200: confirmed order. **409** `ALREADY_CONFIRMED`: the guarded UPDATE affected 0 rows — a second concurrent admin lost the race, per §8.2/§12.6's "ikkinchi admin xato oladi" requirement. 422: order wasn't `UNDER_REVIEW`. 404: not found.

### `POST /admin/orders/{id}/cancel` [Idempotency-Key] + `{"reason"}` — requires `orders.cancel`. Same guarded-release path as the user endpoint, admin actor.

## Admin — Inventory (backend-commerce, `inventory.manage`)

### `POST /admin/inventory/adjust` [Idempotency-Key]
- Body: `{"variant_id", "quantity_change", "reason"}` — reason mandatory (§9). Guarded UPDATE on `stock_on_hand`, `inventory_movements` ADJUST row, audit row.
- 201: movement record. 422: missing reason or the adjustment would violate `stock_reserved <= stock_on_hand`.

## Payments (backend-commerce)

### `POST /payments` [Idempotency-Key]
- Body: `{"order_id"}`. Caller must own the order. Moves `CREATED → AWAITING_PAYMENT` if needed, creates a `PENDING` payment for `orders.remaining_amount`. If a `PENDING` payment already exists for the order it is returned instead (one open payment per order — approving two used to double `paid_amount`).
- 201: payment object. 403: not the order's owner. 422: order not in a payable state.

### `POST /payments/{id}/receipt` (multipart)
- The body is read with a hard 5MB cap while streaming (`read_upload_limited`) — larger bodies are rejected with 422 before being buffered.
- §11.2/§11.3 pipeline: MIME allowlist + magic-byte sniff, ≤5MB in, WebP re-encode ≤1MB out, EXIF stripped, max long side 1600px, `uuid4` filename under `receipts/`. Retention `now()+30d` (ADR-9). Moves order `AWAITING_PAYMENT → PAYMENT_SUBMITTED → UNDER_REVIEW`.
- 200: `{"id", "payment_id"}`. 422: failed validation/processing, or payment not `PENDING`. 403: not the payment's owner. 404: payment not found.

## Admin — Payments (backend-commerce, `payments.review`)

### `POST /admin/payments/{id}/review`
- Body: `{"approve": bool, "rejection_reason"?}` — reason required when rejecting.
- Guarded one-way transition: `UPDATE ... WHERE status='PENDING'` (REQ-BIZ-008 — an `APPROVED` payment never reverts). The order row is locked `FOR UPDATE` first. On approve: `orders.paid_amount`/`remaining_amount` updated from the snapshot total (ADR-5), not a live catalog recompute. On reject: the order moves `UNDER_REVIEW → REJECTED` (§8.1; audit 2026-09-19 — nothing performed this transition before, see OPEN-8) with an `order.reject` audit row.
- 200: updated payment. 422: payment already reviewed, missing rejection reason, or `ORDER_NOT_REVIEWABLE` (the order is `CANCELLED`/`EXPIRED` — money is never recorded against a dead order).

### `GET /admin/payments/{id}/receipt`
- Returns a Nginx `secure_link` signed URL (ADR-13), 15-minute TTL — never streams the file itself.
- 200: `{"url": "/files/receipts/....webp?s=...&e=..."}`. 404: no receipt on this payment.

### `GET /admin/payments?status=&limit=` (`limit` default 20, max 200)
- Added in Phase 06 — the P0 Admin Payments screen had no list to work from; Phase 03 only ever built single-payment lookups by id.
- Requires `payments.review`. 200: `{"items": [...]}`, newest-submitted first.

## Admin — Catalog Management (backend-core, Phase 06)

All mutations here require `products.create` (create), `products.update` (update/images/compatibility), or `products.archive` (status changes) — the exact three keys §3's matrix already grants ADMIN, no new permission introduced. Every mutation writes an audit row on the same connection/transaction as the change.

### `POST /admin/products` — body `{"name", "description"?, "brand_id"}`. Creates a `DRAFT` product, populates `search_text` (ADR-8).
### `PATCH /admin/products/{id}` — body `{"name"?, "description"?, "brand_id"?}`. Bumps `updated_at`, recomputes `search_text`. 404 if not found/soft-deleted.
### `POST /admin/products/{id}/status` — body `{"status": "DRAFT"|"ACTIVE"|"ARCHIVED"}`. 422 on an invalid literal, 404 if not found.

### `POST /admin/variants` — body `{"product_id", "sku", "color_id"?, "price", "required_initial_payment"?}`. `stock_on_hand`/`stock_reserved` are never settable here — they default to 0 and only ever change via `POST /admin/inventory/adjust` or order-confirm. 422 on a CHECK/UNIQUE violation (duplicate SKU, `required_initial_payment > price`).
### `PATCH /admin/variants/{id}` — same field set minus `product_id`, same stock exclusion. 404/422 as above.
### `POST /admin/variants/{id}/status` — body `{"status": "ACTIVE"|"ARCHIVED"}`.

### `POST /admin/brands` / `PATCH /admin/brands/{id}` / `POST /admin/brands/{id}/archive` — body `{"name"}` for create/update. Archive soft-deletes (`deleted_at`).
### `POST /admin/colors` / `PATCH /admin/colors/{id}` / `POST /admin/colors/{id}/archive` — body `{"name"?, "hex_code"?}`.

### `GET /admin/products/{id}/compatibilities` — requires `catalog.view`. 200: `{"items": [...]}`.
### `POST /admin/products/{id}/compatibilities` — body `{"generation_id", "year_from"?, "year_to"?, "note"?}`. Rejects a soft-deleted `car_generations` row with 422 — the FK alone only proves existence, not that the row is still active (Phase 02's polymorphic-reference lesson, applied here to a real FK).
### `DELETE /admin/products/{id}/compatibilities/{compatibility_id}` — soft-delete (migration `0014_compatibility_soft_delete` — see "Database changes" below for why this couldn't be a real `DELETE`). 404 if not found.

### `POST /admin/products/{id}/images` (multipart) — §11.2/§11.3 pipeline (shared with receipts, `app/security/uploads.py`), stored at `products/{product_id}/{uuid}.webp` per ADR-14. First image on a product is automatically primary. 422 if the product already has 5 images (§6.3 cap, application-enforced).
### `DELETE /admin/products/{id}/images/{image_id}` — soft-delete; the file is left on disk (no purge worker for product images yet, same "metadata-first" pattern as ADR-9's receipts).
### `POST /admin/products/{id}/images/{image_id}/primary` — unsets the previous primary, sets the new one, one transaction; the existing partial unique index (migration `0003_catalog`) is what actually guarantees exactly one survives even under concurrent calls.

## Cancellation requests (backend-commerce, ADR-017 — v2 rebuild)

A `CONFIRMED` order (or any order with `paid_amount > 0`) cannot be cancelled through
`POST /orders/{id}/cancel` — that endpoint now returns `409 APPROVED_PAYMENT_EXISTS` for it. This
is the replacement path.

### `POST /orders/{id}/cancellation-request` — requires `cancellation_requests.create` (USER, own order only).
- Body: `{"reason"}` — ≥10 chars, same discipline as the direct cancel endpoint.
- 201: the request (`status: "PENDING"`). 409: another `PENDING` request already exists for this order (`REQUEST_ALREADY_OPEN`). 422: order not `CONFIRMED`/`UNDER_REVIEW` with `paid_amount > 0`, or reason too short. 403: not the order's owner.

### `GET /admin/cancellation-requests` — requires `cancellation_requests.review`. 200: all `PENDING` requests, oldest first.

### `POST /admin/cancellation-requests/{id}/approve` / `.../deny` — requires `cancellation_requests.review`.
- Body: `{"decision_note"?}`.
- Approve: guarded transition `CONFIRMED -> CANCELLED` (reachable *only* through this path, never `POST /orders/{id}/cancel`), stock restored via a fresh `IN` inventory movement (not a reservation release — none exists on a CONFIRMED order). Deny: order stays `CONFIRMED`.
- 200: the decided request. 409: request already decided (`REQUEST_NOT_PENDING`) or the order's status changed concurrently (`ORDER_NOT_ELIGIBLE`). 404: request not found.

## Refunds (backend-commerce, ADR-017 — v2 rebuild)

Refund is fully independent of `orders.status`/`cancellation_requests.status` — approving a
cancellation never auto-creates or auto-completes a refund. `CARD` refunds are admin-attested
manual records, same as `CASH` — no Hamyon refund API is documented (`13_V2_REBUILD_AUDIT.md` §2),
so nothing here auto-completes against a payment provider.

### `POST /admin/refunds` — requires `refunds.manage`.
- Body: `{"order_id", "payment_id"?, "amount", "method": "CASH"|"CARD", "reason"}` — reason ≥10 chars.
- The amount-conservation invariant is enforced at both creation *and* completion time: the sum of `COMPLETED` refunds for an order can never exceed `orders.paid_amount` (re-checked under an order-row lock on completion, so two admins racing to complete two PENDING refunds can't both succeed).
- 201: the refund (`status: "PENDING"`). 409: would exceed `paid_amount` (`INVALID_REFUND_AMOUNT`). 404: order not found.

### `GET /admin/orders/{id}/refunds` — requires `refunds.manage`. 200: `{"items": [...]}`, newest first.

### `POST /admin/refunds/{id}/complete` — requires `refunds.manage`. Body: `{"provider_reference"?}`.
- 200: the refund (`status: "COMPLETED"`). 409: already decided (`REFUND_NOT_PENDING`), or completing it would now exceed `paid_amount` (`INVALID_REFUND_AMOUNT` — refund stays `PENDING`, not silently completed). 404: not found.

### `POST /admin/refunds/{id}/fail` — requires `refunds.manage`. Body: `{"reason"?}`. 200/409/404 as above.

## Cost price (backend-core, gated by `finance.view` — v2 rebuild)

Cost price is financial data: ADMIN holds `products.update` but **not** `finance.view`, so these
two endpoints (not the general variant-update endpoint) are the only way to read/write it. Never
exposed through `GET /catalog/products`, `GET /catalog/products/{id}`, or any USER-facing response.

### `GET /admin/variants/{id}/cost-price` — requires `finance.view`. 200: `{"id", "cost_price"}` (`cost_price` is `null` if never recorded). 404: not found.
### `PATCH /admin/variants/{id}/cost-price` — requires `finance.view`. Body: `{"cost_price"}` (≥0). 200: `{"id", "cost_price"}`. 404: not found.

`order_items.cost_price_snapshot` (not a separate endpoint) is copied from the variant's cost
price at order-creation time (ADR-005 snapshot discipline) — `owner/finance` reads this snapshot
for COGS/gross-profit, never the live `product_variants.cost_price`, so a later cost edit never
changes historical numbers. `GET /owner/finance` additionally returns `gross_sales_confirmed`,
`cogs_known`, `gross_profit_known`, `items_missing_cost_price`, `cogs_complete` (false if any
`CONFIRMED`-order line in the period has no cost snapshot — profit is never claimed from
incomplete cost data), `refunded`, `net_revenue`.

## AI admin assistant (ADMIN/OWNER only — `ai.assistant.use`, v2 rebuild)

Mandatory architecture (never bypassed): `structured command -> backend schema validation ->
permission check -> preview draft -> admin confirmation -> domain service -> database`. The AI
never executes a mutation directly — every mutation command (`CREATE_PRODUCT`, `INCREASE_STOCK`,
`DECREASE_STOCK`, `UPDATE_PRICE`, `ARCHIVE_PRODUCT`) creates a `PENDING` draft first; read
commands (`GET_PRODUCT`, `GET_STOCK`, `GET_ORDER`, `GET_SALES_STATISTICS`, `GET_REVENUE`,
`GET_PROFIT`, `GET_COST_PRICE`) execute immediately after the same permission check (each command
requires the *identical* permission key its manual admin endpoint requires — `GET_REVENUE`/
`GET_PROFIT`/`GET_COST_PRICE` require `finance.view`, so a plain ADMIN cannot reach them via AI
either). Full schema: `backend/app/ai/commands.py`.

### `POST /admin/ai/message` — requires `ai.assistant.use`. Body: `{"text"}`.
- 200 (read command): `{"understood": true, "command_type", "executed": true, "read_only": true, "result"}`.
- 200 (mutation, not yet confirmed): `{"understood": true, "command_type", "executed": false, "draft_id", "confirmation_token", "expires_at", "preview"}`.
- 200 (not understood): `{"understood": false, "message", "raw_text"}` — never guessed, never silently dropped.
- 409: the text named an ambiguous product (`AMBIGUOUS_REFERENCE`, includes `matches`). 422: unresolvable product/brand reference (`NOT_FOUND`), or the AI's payload failed strict schema validation (`INVALID_REQUEST` — e.g. `CREATE_PRODUCT` without a `brand_id`, which is never guessed). 403: role lacks the specific command's permission.

### `POST /admin/ai/voice` — requires `ai.assistant.use`. Body: raw audio bytes (multipart/binary), `Content-Type` header carries the mime type.
- Transcribes via the configured `STT_PROVIDER`, then runs the exact same pipeline as `/admin/ai/message` (no duplicated logic). 503: no STT provider configured or the provider call failed (`STT_NOT_CONFIGURED`) — never crashes, never fabricates a transcript.

### `POST /admin/ai/drafts/{id}/confirm` — requires `ai.assistant.use`. Body: `{"confirmation_token"}`.
- Bound to the authenticated admin (must be the draft's creator), the exact frozen payload (re-validated, never accepts new values), expiration (15 minutes), and re-checks the command's permission (a role change between draft and confirm is caught). One-time: a second confirm attempt on the same draft gets `409 DRAFT_NOT_PENDING`, never re-executes.
- 200: `{"draft_id", "command_type", "result"}`. 403: wrong admin (`FORBIDDEN`) or token mismatch. 409: expired (`DRAFT_EXPIRED`) or already confirmed/cancelled (`DRAFT_NOT_PENDING`). 404: draft not found.

### `POST /admin/ai/drafts/{id}/cancel` — requires `ai.assistant.use`. 200: the cancelled draft. 403/409/404 as above.

**Telegram bot surface** (`bot/handlers/ai.py`, ADMIN/OWNER only — a non-admin sender's message
silently falls through to the ordinary USER bot flow, never a "forbidden" reply that would confirm
an account's role to an unauthorized prober): text messages, voice messages (downloaded once,
transcribed, fed into the same pipeline), and photos. A photo with a caption is `IMAGE` context
immediately; a bare photo opens a 2-minute `ai_pending_media` correlation window (bound to admin
Telegram ID + chat ID, atomically claimed — see `app/ai/pending_media.py`) so a following
voice/text message completes a `CREATE_PRODUCT` command with the photo attached (the file is
downloaded and stored exactly once, at confirm time, never at draft time). Mutation drafts render
as `[Tasdiqlash]`/`[Tahrirlash]`/`[Bekor qilish]` inline buttons; `Tahrirlash` cancels the draft
and prompts a resend rather than doing in-place field editing.

## Owner (backend-core — `app/domains/owner/`, Phase 07)

Every route is gated by the exact §3 permission key it corresponds to — all five (`finance.view`, `analytics.view`, `admins.manage`, `audit.view`, `settings.manage`) were already seeded in migration `0001_identity`, held only by OWNER (ADMIN explicitly excluded in that same seed data). "Revenue" everywhere below reads `orders.paid_amount` (ADR-5's already-authoritative running total of approved payments, kept in sync since Phase 03), not a re-derivation from `payments`.

### `GET /owner/dashboard` — requires `finance.view`.
- 200: order counts by status, `total_revenue`, product/active-product counts, `low_stock_variants` (variants at or below `low_stock_threshold`, an operational display default of 5 — not a TZ business rule), 10 most recent orders/payments.

### `GET /owner/finance?from=&to=` — requires `finance.view`. ISO-8601 dates, range capped at 366 days.
- 200: `revenue`, `order_count`, `payment_status_breakdown`, and up to 100 `payments` in the period, each including `hidden_before_review` (ADR-9's `hidden_at < reviewed_at` comparison — always `false` today since no receipt-hide endpoint has shipped yet, ready the moment one does). 422: invalid/inverted/oversized date range.

### `GET /owner/analytics?from=&to=` — requires `analytics.view`. Same date-range rules as finance.
- 200: `orders_over_time` (daily, SQL `date_trunc` aggregation), `order_status_distribution`, `payment_status_distribution`, `best_selling_products` (top 10 by quantity, `CONFIRMED` orders only, SQL-aggregated over `order_items`, never loaded row-by-row into Python).

### `GET /owner/admins` — requires `admins.manage`. 200: all `role='ADMIN'` users.
### `POST /owner/admins` — body `{"telegram_id", "first_name"?, "last_name"?, "username"?}` — **no `role` field exists on this model**, so a request body can never specify or escalate a role; it's hardcoded `'ADMIN'` server-side. Reuses the same upsert-on-`telegram_id` shape as `identity.repository.find_or_create_user` — one place a user row's identity is ever keyed, so pre-registering someone here and having them later open the bot/Mini App recognizes the same row. 422 if the `telegram_id` already belongs to the OWNER (never reassignable through this endpoint).
### `POST /owner/admins/{id}/deactivate` / `POST /owner/admins/{id}/reactivate` — requires `admins.manage`. Guarded to `role='ADMIN'` rows only — can never touch the OWNER row or a plain USER row, by construction. 404 otherwise.

### `GET /owner/audit-logs?entity_type=&action=&actor_id=&cursor=&limit=` — requires `audit.view`. Keyset-paginated (`(created_at, id)`, same cursor shape as `catalog/repository.py`), newest first. `old_data`/`new_data`/`metadata` pass through a denylist redaction (`password`/`token`/`secret`/`credential` key names, case-insensitive, recursive) before being returned — defense-in-depth; no current write path stores such fields, but this is the first endpoint that echoes raw audit JSONB back to a client.

### `GET /owner/settings` / `PUT /owner/settings` — requires `settings.manage`. Body: `{"settings": {key: value, ...}}`, partial upsert (each key independent, never a whole-blob replace). **Starts with zero pre-seeded keys** — the TZ never specifies what a setting is anywhere in the document (confirmed exhaustively during Phase 07 planning); this is a generic, empty-by-default persistence mechanism, not invented business content. 422: empty or >100-char key.

## Worker (backend-commerce business logic, devops-owned scheduling — Phase-09)

`comfort-reservation-expiry` (`app/workers/reservation_expiry.py::run_once`): every 5 minutes, releases `stock_reservations` past `expires_at` (guarded pattern, safe to re-run) and moves the order to `EXPIRED` if it's still in a pre-terminal status. Not an HTTP endpoint.

## Deferred to later phases
`/favorites`, `/stock-notifications`, `/sell-requests`, `/conversations/*`, `/notifications`, `/admin/sell-requests/*`, `/admin/conversations/*`, `/admin/broadcasts` (ENGAGEMENT/COMMUNICATION/MARKETPLACE, P1, `backend-engagement`, Phase-10), `/health` (devops, Phase-09). Refund/cancellation-request endpoints were deferred as P3/OPEN-4 as of the 2026-09-19 audit — **implemented** in the 2026-09-29 v2 rebuild, see the "Cancellation requests"/"Refunds" sections above; Hamyon payment-provider endpoints remain undocumented/unimplemented (no authoritative API docs exist, `13_V2_REBUILD_AUDIT.md` §2) and are not listed here since nothing real was built against a guessed schema.
