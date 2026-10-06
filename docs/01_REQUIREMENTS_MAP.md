# 01 — Requirements Map

**Purpose:** Atomic, traceable list of every requirement in the Master TZ, with a stable ID and a pointer back to the source section. This is the map every other Phase 0 document (feature inventory, domain architecture, agent architecture) is derived from.
**Owner:** architect (maintained), docs (sync)
**Last updated:** 2026-08-17
**Dependencies:** [00_MASTER_TZ.md](00_MASTER_TZ.md)

> Source of truth is always `00_MASTER_TZ.md`. If a requirement here ever disagrees with the Master TZ, the Master TZ wins and this file is wrong — file a docs fix.

ID scheme: `REQ-<DOMAIN>-<NNN>`. Domain codes: `IDT` Identity, `CAT` Catalog, `VEH` Vehicle, `PRC` Pricing, `INV` Inventory, `COM` Commerce, `PAY` Payments, `ENG` Engagement, `CMN` Communication, `MKT` Marketplace, `SRC` Search, `SEC` Security, `FS` File Storage, `BE` Backend Architecture, `FE` Frontend, `BOT` Bot, `WRK` Workers, `OPS` Server/Deployment, `PERF` Performance, `TST` Testing, `BIZ` Cross-cutting business rule.

## Architecture decisions (§0–§1)
| ID | Requirement | Source |
|---|---|---|
| REQ-BE-001 | Single backend (FastAPI). Mini App and Bot never touch DB directly — both call the same Service layer. | ADR-1, §13.1 |
| REQ-BE-002 | Backend and PostgreSQL co-located on one VPS, connected via Unix socket (no TCP). | ADR-1, §13.3 |
| REQ-SEC-001 | Auth is Telegram `initData` only. SMS/OTP is explicitly forbidden — do not reintroduce. | ADR-2 |
| REQ-SEC-002 | `initData` verified via HMAC-SHA256 (`secret_key = HMAC_SHA256("WebAppData", bot_token)`); `auth_date` must be < 24h old. | ADR-2 |
| REQ-SEC-003 | `user_id` from the frontend is never trusted as identity — only the verified `telegram_id` from `initData`. | ADR-2 |
| REQ-PRC-001 | All money fields are `BIGINT` so'm, `CHECK (price >= 0)`. `FLOAT`/`REAL`/`DOUBLE PRECISION` for money is forbidden anywhere in the stack. (Canonical ID — merged with the former `REQ-PRC-002`, which restated this same rule from §5.1; both TZ passages are the same requirement, not two.) | ADR-3, §5.1 |
| REQ-CAT-001 | Every product has ≥1 variant. Price, stock, initial-payment and color live only on the variant, never the product. | ADR-4 |
| REQ-COM-001 | Orders and order_items store a full snapshot (names, price, discount, required initial payment) at order-creation time. Later product/price edits never retroactively change existing orders. | ADR-5 |
| REQ-INV-001 | Variant stock has three fields: `stock_on_hand`, `stock_reserved`, `available = on_hand - reserved`. Never negative. | ADR-6 |
| REQ-INV-002 | Order creation reserves stock with `expires_at = now() + 24h`. Payment approval converts reservation to on-hand deduction. Cancel/TTL-expiry releases the reservation. | ADR-6 |
| REQ-SEC-004 | All mutating/side-effecting endpoints (order create, payment, receipt upload, stock adjust, confirm/cancel, broadcast) require an `Idempotency-Key` (UUID v4); duplicate keys return the stored response without re-executing. Keys expire/are purged after 24h. | ADR-7 |
| REQ-SRC-001 | Search must normalize Cyrillic↔Latin and Uzbek apostrophe variants (`oʻ`/`o'`/`o\``/`ў` → `o`, etc.) identically at write time and query time. | ADR-8 |
| REQ-SRC-002 | Trigram index (`pg_trgm`) on `products.search_text`. | ADR-8 |
| REQ-SRC-003 | `search_aliases` table maps colloquial spellings to canonical terms (e.g. `neksiya`→`nexia`). Match order: alias → exact → trigram similarity ≥0.3. | ADR-8 |
| REQ-FS-001 | Receipt DB rows are never deleted — only the file is purged after retention. `visibility_status`, `hidden_at`/`hidden_by`, `retention_until` (upload+30d), `file_purged_at`, `reviewed_at`, `review_result` are all tracked to answer "was this hidden before or after review?". | ADR-9 |
| REQ-MKT-001 | Sell-request lifecycle: `PENDING → UNDER_REVIEW → APPROVED → CONVERTED`, with `REJECTED` (reason mandatory) and `SOLD` side-branches. `CONVERTED` creates a draft product with `source='CONSIGNMENT'` and copies images. | ADR-10 |
| REQ-IDT-001 | Exactly one OWNER, seeded via migration from `OWNER_TELEGRAM_ID` env var. No UI path can create an OWNER. Enforced by a partial unique index on `role='OWNER'`. | ADR-11 |
| REQ-BOT-001 | On Telegram `403 bot was blocked`: set `users.bot_blocked_at`, exclude the user from broadcasts, still write to `notifications` (in-app). Clears on next `/start`. | ADR-12 |
| REQ-FS-002 | All file access is via Nginx `secure_link` signed URLs (`s`=signature, `e`=expiry). Backend signs (`md5(expires + path + SECRET)`), Nginx verifies. No file is ever served unsigned. `$remote_addr` must NOT be part of the signature (mobile IP roams). | ADR-13 |
| REQ-FS-003 | Upload directory layout is fixed: `products/{id}/`, `products/{id}/thumbs/`, `receipts/{yyyy}/{mm}/`, `sell-requests/{id}/`, `chat/{conversation_id}/`. Filenames are always server-generated UUIDv4, never user-supplied. Directory is not an Nginx document root — only reachable via `/files/` with a signature. | ADR-14 |

## Scope & priority (§2)
| ID | Requirement | Source |
|---|---|---|
| REQ-BIZ-001 | P0 (MVP, ~9wk): auth, roles, catalog, cart, order+reservation, payment (card→receipt→review), stock, admin panel, bot notifications, audit log. | §2 |
| REQ-BIZ-002 | P1 (+3wk): favorites, stock notifications, sell-request, user↔admin chat, broadcast, order history, dark/light mode. | §2 |
| REQ-BIZ-003 | P2 (+2wk): owner financial report, top products, admin activity report, admin management, audit panel. | §2 |
| REQ-BIZ-004 | P3 (later): refund lifecycle, analytics events, online payment, delivery, loyalty. | §2 |
| REQ-BIZ-005 | Rule: never fold a P1+ feature into the P0 build. | §2 |

## Roles & permissions (§3)
| ID | Requirement | Source |
|---|---|---|
| REQ-IDT-002 | Three roles: OWNER (exactly 1), ADMIN (many), USER (many). | §3 |
| REQ-IDT-003 | Permission matrix is authoritative (catalog.view, products.*, inventory.manage, orders.view.all/own, orders.confirm/cancel, payments.review, receipts.view, sell_requests.review, chat.reply, broadcast.send, finance.view, analytics.view, admins.manage, audit.view, settings.manage). ADMIN never gets finance.view, analytics.view, admins.manage, audit.view, settings.manage. | §3 |
| REQ-SEC-005 | Every permission is checked server-side on every API call. Hiding a button in the frontend is not access control. | §3 |
| REQ-IDT-004 | Roles/permissions are data (`roles`, `permissions`, `role_permissions` tables), not hardcoded — must support adding roles like `SENIOR_ADMIN`/`OPERATOR` later without code changes to the permission check path. | §3 |

## Domain model (§4)
| ID | Requirement | Source |
|---|---|---|
| REQ-BE-003 | ~30 tables across 12 domains: IDENTITY, CATALOG, VEHICLE, PRICING, INVENTORY, COMMERCE, PAYMENTS, ENGAGEMENT, COMMUNICATION, MARKETPLACE, SEARCH, SECURITY. MVP ships ~20 (COMMUNICATION, MARKETPLACE deferred to P1). | §4 |

## Data type standards (§5)
| ID | Requirement | Source |
|---|---|---|
| *(money type)* | See `REQ-PRC-001` above (Architecture decisions §0–§1) — §5.1 restates the same ADR-3 rule, merged rather than duplicated as its own ID. | §5.1 → ADR-3 |
| REQ-BE-004 | Time: `timestamptz DEFAULT now()`, stored UTC; server OS timezone set to UTC; display/reports in Asia/Tashkent (UTC+5, no DST). | §5.2 |
| REQ-IDT-005 | Phone: `CHECK (phone ~ '^\+998[0-9]{9}$')`, normalized (strip spaces/`-`/`(`/`)`) before write, unique among non-deleted users. | §5.3 |
| REQ-BE-005 | Soft-delete + uniqueness: partial unique indexes (`WHERE deleted_at IS NULL`) everywhere soft delete applies — a deleted SKU must not block reuse. | §5.4 |
| REQ-IDT-006 | `users.telegram_id` is `BIGINT` (exceeds 32-bit). Internal PKs are `BIGSERIAL`. Externally visible order number is a short random code (`CU-7F3K92`), never sequential. | §5.5 |
| REQ-BE-006 | Status fields are `text + CHECK (status IN (...))`; the allowed list must match between DB and code. | §5.6 |

## Catalog (§6)
| ID | Requirement | Source |
|---|---|---|
| REQ-CAT-002 | Product: name, description, brand, status (DRAFT/ACTIVE/ARCHIVED), source (OWN/CONSIGNMENT), `search_text`, timestamps. | §6.1 |
| REQ-CAT-003 | Variant: SKU (unique among non-deleted), color, price, initial payment, `stock_on_hand`, `stock_reserved`, status. | §6.2 |
| REQ-CAT-004 | Product images: 1–5 per product, file on disk + DB metadata (`storage_path`, `sort_order`, `is_primary`, `width`, `height`, `bytes`). Exactly one `is_primary` per product (partial unique index). | §6.3 |
| REQ-VEH-001 | Compatibility chain: `car_brands → car_models → car_generations → product_compatibilities`, with optional `year_from`/`year_to` (`year_to >= year_from` when both set) and free-text `note`. | §6.4 |
| REQ-SRC-004 | Search covers product name, brand, vehicle brand/model/generation, SKU (via ADR-8 normalization). Filters: vehicle brand/model, product brand, price range, availability, discount, color. Sort: price ↑↓, newest, popularity. | §6.5 |
| REQ-CAT-005 | `brands` and `colors` are normalized lookup tables with stable surrogate IDs (`BIGSERIAL` PKs), not free-text columns on `products`/`product_variants`. Not stated explicitly in §6.1/§6.2 (which describe brand/color as inline product/variant attributes) but required by §4's domain model (which lists `brands`/`colors` as their own tables) and by §7.1's `discount_targets(target_type='BRAND', target_id)`, which can only reference a stable ID if `brands` is a real table with a primary key. Added per Phase 0 review — previously only implied, not stated as a requirement. | §4, §6.1, §6.2, §7.1 (inferred) |

## Pricing & discounts (§7)
| ID | Requirement | Source |
|---|---|---|
| REQ-PRC-003 | `discounts` (kind PERCENT/FIXED, value, starts_at/ends_at, is_active, priority) + `discount_targets` (target_type: VARIANT/PRODUCT/BRAND/CAR_MODEL/ALL, target_id). | §7.1 |
| REQ-PRC-004 | Discount specificity order: VARIANT > PRODUCT > BRAND > CAR_MODEL > ALL. Same-level ties broken by `priority` (higher wins); remaining ties resolved in the customer's favor (cheaper). No stacking — exactly one discount applies. Result is never negative. | §7.2 |
| REQ-COM-002 | Checkout always re-validates on the server: variant ACTIVE, `available >= qty`, price recomputed, discount reapplied, initial-payment requirement fetched, snapshot written. Client-submitted price is never trusted. Mismatch → `409 Conflict` with the new price, requiring user confirmation. | §7.3 |

## Orders & payments (§8)
| ID | Requirement | Source |
|---|---|---|
| REQ-COM-003 | Order lifecycle: `CREATED → AWAITING_PAYMENT → PAYMENT_SUBMITTED → UNDER_REVIEW → {CONFIRMED\|REJECTED}`, plus `CANCELLED` (user/admin) and `EXPIRED` (TTL/worker) branches, plus P3 `CONFIRMED → REFUND_PENDING → REFUNDED`. Only the explicit transition table is legal; anything else → `422`. | §8.1 |
| REQ-COM-004 | Concurrent confirm-order race: `SELECT ... FOR UPDATE` on the order row, transition guarded by current status, stock decrement + audit insert in the same transaction. Second admin gets an explicit "already confirmed by another admin" error, not a silent overwrite. | §8.2 |
| REQ-PAY-001 | MVP payment method is manual card transfer + receipt photo + admin review. `payments` table: order_id, amount, method (CARD_TRANSFER), status (PENDING/APPROVED/REJECTED), submitted_at, reviewed_at, reviewed_by, rejection_reason. | §8.3 |
| REQ-PAY-002 | An `APPROVED` payment can never transition back to `PENDING`. | §8.3, §20 |
| REQ-COM-005 | Order cancellation by admin requires `cancellation_reason`, minimum 10 characters. | §8.4 |

## Inventory (§9)
| ID | Requirement | Source |
|---|---|---|
| REQ-INV-003 | `inventory_movements` is append-only: variant_id, movement_type (IN/OUT/RESERVE/RELEASE/ADJUST), quantity_change, quantity_before/after, reason, reference_type/id, actor_id, created_at. | §9 |
| REQ-INV-004 | Stock only changes through the backend, never negative (CHECK), all concurrent mutation via `FOR UPDATE`, manual `ADJUST` requires a reason and is audited. | §9 |

## Remaining modules (§10)
| ID | Requirement | Source |
|---|---|---|
| REQ-ENG-001 | Favorites: `UNIQUE (user_id, variant_id)`. | §10 |
| REQ-ENG-002 | Stock notifications: `UNIQUE (user_id, variant_id)`, fires when stock becomes > 0, then records `notified_at`. | §10 |
| REQ-MKT-002 | Sell-request rejection requires a reason (see ADR-10). | §10 |
| REQ-CMN-001 | Chat: `conversations` (user, assigned admin, status) + `messages` (sender, text, attachment, read state). Reassigning the admin preserves history. | §10 |
| REQ-CMN-002 | Notifications go over two channels: Telegram message + `notifications` row (visible in Mini App). If the bot is blocked, only the in-app channel fires (ADR-12). | §10 |
| REQ-CMN-003 | Broadcast: max 25 msg/sec (Telegram allows ~30, headroom kept); `429` → wait `retry_after` then exponential backoff (2s/4s/8s/max 60s); `403` → ADR-12 path, no retry; `broadcast_targets` tracks SENT/FAILED/BLOCKED per user; resuming a broadcast retries only FAILED (idempotent). | §10 |

## File storage (§11)
| ID | Requirement | Source |
|---|---|---|
| REQ-FS-004 | Signed URL TTL by folder: products 24h, receipts 15min, sell-requests 1h, chat 1h. Retention: products until archived, receipts min 30d, sell-requests 90d after closed, chat 180d. | §11.1 |
| REQ-FS-005 | Upload validation: MIME in {jpeg,png,webp}, max 5MB incoming / 1MB post-compression, magic-byte check (not extension), server-generated filename, executables blocked, Nginx `client_max_body_size 6M`. | §11.2 |
| REQ-FS-006 | Image processing (Pillow): convert to WebP q85, max long edge 1600px, generate 400px thumbnail, strip EXIF (GPS leak risk), catalog uses thumbnail, detail view lazy-loads full image. | §11.3 |
| REQ-OPS-001 | Disk budget target ~19GB used / 100GB available for Comfort UZB alone; monitor and alert OWNER via bot at 80% disk usage. | §11.4 |

## Security (§12)
| ID | Requirement | Source |
|---|---|---|
| REQ-SEC-006 | App-level controls: initData HMAC verification, server-side authorization on every endpoint, Pydantic validation on all input, parametrized queries only, frontend never uses `innerHTML` (XSS), file safety per §11.2 + signed URLs, rate limiting, secrets in `.env` (chmod 600, not in git). | §12.1 |
| REQ-SEC-007 | No RLS (deliberately dropped — see ADR/§12.2 rationale: Postgres only reachable from localhost by the backend). Instead: least-privilege roles — `comfort_app` (SELECT/INSERT/UPDATE, no DELETE, no DDL), `comfort_migrate` (Alembic only), `comfort_backup` (SELECT only). App never connects as superuser/owner. `listen_addresses='localhost'`, `pg_hba.conf` local scram-sha-256 only. | §12.2 |
| REQ-SEC-008 | `audit_logs` is immutable: a trigger raises on any `UPDATE`/`DELETE`. Row shape: actor_id, actor_role, action, entity_type, entity_id, old_data (jsonb), new_data (jsonb), ip, created_at, metadata. Must cover: auth, admin add/remove, product create/update, price change, stock change, order confirm/cancel, payment approve/reject, receipt hide, sell-request decision, broadcast, permission change. | §12.3 |
| REQ-SEC-009 | Rate limits: 60 req/min/user general, 5/min orders, 5/min payments, 10/min uploads, 30/min search, 60/min admin confirm/cancel. Also enforced at Nginx (`limit_req_zone ... rate=10r/s`), `429` + `Retry-After` on breach. | §12.4 |
| REQ-OPS-002 | Server hardening: SSH key-only + no root login + non-standard port (e.g. 2222); `ufw` open only to SSH/80/443, Postgres 5432 never exposed; `fail2ban` on SSH+Nginx; `unattended-upgrades` on; app runs as non-root `comfort` user; HTTPS via Certbot + auto-renew (mandatory for Mini App); `server_tokens off`, TLS 1.2+, HSTS; `logrotate` 14 days. | §12.5 |
| REQ-TST-001 | 14 mandatory security test scenarios (parallel last-unit purchase, concurrent confirm, cross-user order access, ADMIN hitting finance.view, unsigned receipt URL, expired signature, another user's receipt signature, tampered client price, negative qty/price, duplicate Idempotency-Key, deactivated admin, broken/expired initData, `.php`/executable upload, direct external `psql` connection). Canonical ID for this requirement — merged with the former `REQ-TST-004`, which restated the same 14 cases from §19's "Security" test-type row; both TZ passages describe the same 14 scenarios, not two separate sets. | §12.6, §19 |

## Backend architecture (§13)
| ID | Requirement | Source |
|---|---|---|
| REQ-BE-007 | Layering: Router (FastAPI: HTTP/validation/auth) → Service (business logic, single source of truth) → Repository (DB access) → PostgreSQL. Bot and Mini App both call the same Service layer; no business logic lives in the bot. | §13.1 |
| REQ-BE-008 | Stack: Python 3.12, FastAPI+uvicorn, aiogram 3.x, asyncpg (SQLAlchemy Core optional), Alembic, Pydantic v2, Pillow, `python-jose`/`hmac`. | §13.2 |
| REQ-BE-009 | `asyncpg` pool over Unix socket, `min_size=2 max_size=10`, `command_timeout=30`; `postgresql.conf max_connections=100`; if multiple projects share the instance, ≤10 connections each, ≤100 total; PgBouncer only if >100 concurrent connections is actually reached. | §13.3 |
| REQ-BE-010 | Full endpoint surface is fixed in §13.4 (auth, catalog, vehicles, cart, orders, payments, files, favorites, stock-notifications, sell-requests, conversations, notifications, `/admin/*`, `/owner/*`, `/health`). | §13.4 |
| REQ-BE-011 | Error envelope: `{"error": {"code", "message", "details"}}`, user-facing message in Uzbek, technical detail only in server logs. | §13.5 |

## Frontend (§14)
| ID | Requirement | Source |
|---|---|---|
| REQ-FE-001 | Screen inventory fixed: USER (16 screens incl. Home, Catalog, Search, Filter, Product detail, Favorites, Cart, Checkout, Payment, Receipt upload, Order history/detail, Sell, Chat, Profile, Notifications, Settings), ADMIN (10 screens), OWNER (ADMIN + Finance, Analytics, Admins, Audit, Settings). | §14.1 |
| REQ-FE-002 | Mobile-first from 375px; adapt to Telegram `themeParams`/`colorScheme`; respect `safe-area-inset`; no `localStorage` (unreliable in Telegram WebView) — use CloudStorage API or server state; lazy-load images with skeletons; signed image URLs re-requested on expiry per their TTL. | §14.2 |
| REQ-FE-003 | Gallery upload: client-side compress before send (canvas, max 1600px, WebP, q0.85) so mobile uploads stay small. | §14.3 |
| REQ-OPS-003 | Static frontend served by Nginx from `/var/comfort/web/`, fronted by Cloudflare (free CDN/cache); no separate deploy target; hashed assets cached `max-age=31536000, immutable`. | §14.4 |

## Workers (§15)
| ID | Requirement | Source |
|---|---|---|
| REQ-WRK-001 | `comfort-reservation-expiry` (every 5min): release TTL-expired reservations, order → EXPIRED. | §15 |
| REQ-WRK-002 | `comfort-receipt-purge` (daily 04:00): delete files past `retention_until`, keep metadata (ADR-9). | §15 |
| REQ-WRK-003 | `comfort-broadcast` (continuous queue): send per §10 rate-limit rules. | §15 |
| REQ-WRK-004 | `comfort-idempotency-cleanup` (daily 04:30): purge keys older than 24h. | §15 |
| REQ-WRK-005 | `comfort-backup` (daily 03:00): pg_dump + off-server copy (§17.3). | §15 |
| REQ-WRK-006 | `comfort-health` (every 10min): disk/RAM/DB check, Telegram alert to OWNER at 80% disk. | §15 |
| REQ-WRK-007 | Each worker is its own systemd service+timer, `Restart=on-failure`; no worker may run two instances concurrently — enforce via flock or a Postgres advisory lock. | §15 |

## Server & deployment (§16–§17)
| ID | Requirement | Source |
|---|---|---|
| REQ-OPS-004 | Server: Contabo VPS, 4 vCPU/8GB RAM/100GB SSD-NVMe, Ubuntu 24.04 LTS, 1 snapshot. Region picked by measured latency (EU Hub vs India vs Singapore) at checkout — **not yet decided, see open decisions**. | §16.1 |
| REQ-OPS-005 | RAM budget: OS 0.5GB, Postgres 2.5GB, FastAPI 0.7GB, bot 0.3GB, workers 0.3GB, Nginx 0.1GB → ~4.4GB used, ~3.6GB headroom for other projects. | §16.2 |
| REQ-OPS-006 | Postgres tuning for 8GB RAM host is fixed in §16.3 (`shared_buffers=2GB`, `effective_cache_size=5GB`, `work_mem=16MB`, `maintenance_work_mem=512MB`, `max_connections=100`, `random_page_cost=1.1`, `effective_io_concurrency=200`, `wal_level=replica`, `archive_mode=on`, `listen_addresses=localhost`). | §16.3 |
| REQ-OPS-007 | Multi-project host isolation: one Postgres DB + role per project (no cross-DB visibility, `REVOKE CONNECT ... FROM PUBLIC` on others), Nginx routed by subdomain, one systemd service per project, connection budget ≤10 per project. | §16.4 |
| REQ-OPS-008 | Dev and prod never share a DB or bot token. | §17.1 |
| REQ-OPS-009 | Production stack topology fixed: Cloudflare → Contabo → Nginx → {FastAPI :8001, aiogram webhook, workers} → PostgreSQL 16 (localhost) → `/var/comfort/`. Domain + valid HTTPS cert is mandatory (Mini App rejects self-signed). | §17.2 |
| REQ-OPS-010 | Three-tier backup: (1) `pg_dump` gzip daily 03:00, (2) continuous WAL archiving for PITR (RPO 5min), (3) manual full-server snapshot before risky changes. Local retention 7 days, off-server (e.g. Cloudflare R2) 30 days. Restore must be tested monthly against a different target — an untested backup is not a backup. | §17.3 |
| REQ-OPS-011 | All schema changes go through Alembic, versioned. Manual `psql`/`ALTER TABLE` on the server is forbidden. | §17.4 |
| REQ-OPS-012 | Deploy flow: `git pull` → `pip install` → `alembic upgrade head` → restart `comfort-api`/`comfort-bot` → `/health` check. `pg_dump` (and snapshot for big changes) before deploy. | §17.5 |
| REQ-OPS-013 | Monitoring: systemd `Restart=on-failure`; external ping every 10min (e.g. healthchecks.io); disk 80%+ alert via `comfort-health`; error tracking via Sentry free tier **or** ERROR-log→Telegram — **not yet decided, see open decisions**; journald + logrotate 14 days. | §17.6 |
| REQ-OPS-014 | Go-live checklist is fixed in §17.7 (16 items) — must all be checked before production traffic. | §17.7 |

## Performance (§18)
| ID | Requirement | Source |
|---|---|---|
| REQ-PERF-001 | Targets: first paint <2.0s on 4G, catalog list p95 <150ms, search p95 <200ms, product detail p95 <120ms, order create p95 <300ms, signed file serve <50ms, thumbnail <30KB, first load payload <400KB. | §18 |
| REQ-PERF-002 | Pagination mandatory on products/orders/messages/notifications/users/audit/sell-requests; default `limit=20` max `100`; cursor/keyset-based, not `OFFSET`. | §18.1 |
| REQ-PERF-003 | Full index list is fixed in §18.2 — every listed index must exist before load testing. | §18.2 |

## Testing (§19)
| ID | Requirement | Source |
|---|---|---|
| REQ-TST-002 | Unit: price calc, discount priority, status transitions, search normalization, signed-URL signature. | §19 |
| REQ-TST-003 | Integration: order flow, payment flow, stock movement, transactions. | §19 |
| *(security testing)* | See `REQ-TST-001` above (§12) — §19's "Security" row restates the same 14 cases, merged rather than duplicated as its own ID. | §19 → §12.6 |
| REQ-TST-005 | E2E: user → cart → order → payment → admin → confirm → stock decremented. | §19 |
| REQ-TST-006 | Load: 50 parallel users browsing catalog + 10 parallel checkouts. | §19 |
| REQ-TST-007 | Restore drill: monthly, restore backup to a separate target. | §19 |
| REQ-TST-008 | Minimum bar: the 14 security cases + the E2E flow + the restore drill must be automated or documented as a runnable procedure. | §19 |

## Cross-cutting business rules (§20) — non-negotiable, apply across all domains
- REQ-BIZ-006 Stock never negative; `available = on_hand - reserved`, never negative.
- REQ-BIZ-007 A `CONFIRMED` order is never modified by a plain `UPDATE` (state-machine only).
- REQ-BIZ-008 An `APPROVED` payment never reverts to `PENDING`.
- REQ-BIZ-009 Receipt metadata is never deleted (file may be purged).
- REQ-BIZ-010 ADMIN never sees financial data.
- REQ-BIZ-011 A USER never sees another USER's order.
- REQ-BIZ-012 Exactly one OWNER, always.
- REQ-BIZ-013 Cancellation always requires a reason.
- REQ-BIZ-014 Price/stock/discount are computed only on the server.
- REQ-BIZ-015 Audit log is append-only.
- REQ-BIZ-016 A reservation never outlives 24h.
- REQ-BIZ-017 A user can favorite a given variant only once.
- REQ-BIZ-018 A product has exactly one primary image.
- REQ-BIZ-019 No file is ever served without a valid signature.
*(Source: §20, restated verbatim from §1–§19 as a final checklist — not new scope.)*

## Retention (§21)
| ID | Requirement | Source |
|---|---|---|
| REQ-BE-012 | Retention policy table is fixed: products archived not deleted; users/admins soft-deleted; orders/payments never deleted; audit logs never deleted (archived after 12mo); receipt metadata never deleted, file purged after 30d; messages 180d; idempotency keys 24h; WAL archive 7d; local backup 7d (off-server 30d). | §21 |

## Development phases & timeline (§22)
| ID | Requirement | Source |
|---|---|---|
| REQ-BE-013 | TZ's own 13-step phase/timeline breakdown, ~10 weeks MVP total: 0 server setup (3d) → 1 TZ+DB schema (✅) → 2 Alembic migrations+seed+roles (1wk) → 3 backend auth/catalog/cart (1.5wk) → 4 backend order/payment/stock (1.5wk) → 5 **workers+backup (0.5wk)** → 6 Mini App user screens (2wk) → 7 admin panel (1wk) → 8 bot notifications (0.5wk) → 9 security+test (1wk) → 10 production deploy (0.5wk) → 11 v1.1 (+3wk) → 12 v1.2 (+2wk). Added per Phase 0 review — this was previously omitted from the requirements map entirely, and `docs/tasks/Phase-01..10` was never explicitly reconciled against it. Notably, TZ's own phase 5 places worker business logic immediately after order/payment backend work, not at deploy time — this requirement is the source authority behind the Phase 0 review's worker-sequencing correction (see `docs/03_FEATURE_DEPENDENCY_MAP.md` "Relationship to Master TZ §22" and `docs/tasks/Phase-03-Backend.md`). | §22 |

*Where the implementation roadmap (`docs/tasks/Phase-01..10`) differs from this TZ timeline, and why:* the roadmap is organized by owning agent/deliverable rather than by TZ §22's week-by-week grouping, and does not carry a standalone "Workers" phase — each worker's business logic instead ships inside the phase of the domain that owns it (`comfort-reservation-expiry` with `backend-commerce` in Phase-03; `comfort-receipt-purge`/`comfort-idempotency-cleanup` with `security`'s Phase-03-prerequisite work; `comfort-broadcast` with `backend-engagement`'s P1 rollout in Phase-10; `comfort-backup`/`comfort-health` authored by `devops` in Phase-09). This is a closer match to TZ §22's actual intent (workers built alongside backend work, not deferred) than an earlier draft of this roadmap was — see `docs/06_OPEN_DECISIONS.md` OPEN-5. No other TZ §22 sequencing intent is knowingly overridden; the roadmap's per-agent phase boundaries are a documentation-organization choice, not a scope or requirement change.

## Definition of done (§24)
| ID | Requirement | Source |
|---|---|---|
| REQ-BIZ-020 | MVP is production-ready only when all 15 checklist items in §24 pass (initData verified, 3 roles enforced server-side, catalog+search+filter work, cart→order snapshot correct, reservation+TTL work, receipt upload+signed access only, admin confirm atomically decrements stock, parallel-confirm test passes, audit log write+immutability, bot notifications don't crash on blocked users, all 14 §12.6 tests pass, backup+restore drill passed, all workers running, external uptime monitoring alerts, mobile UX verified on a real phone). | §24 |

## Forward-looking documents named by the TZ itself (§25)
These are not yet written; they are downstream of this Phase 0 pass and are the actual implementation-phase deliverables:
1. Server Setup Runbook (§12.5 + §16 + §17, step by step)
2. Complete PostgreSQL Schema (full DDL, constraints, indexes, roles/grants)
3. Backend API Specification (per-endpoint request/response/error)
4. Bot Specification (handlers, FSM, message copy)
5. Mini App UI/UX Spec (screen by screen)
6. Deployment & Backup Runbook (deploy/rollback/restore procedure)
