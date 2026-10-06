# 04 — Domain Architecture

**Purpose:** Defines the 12 business domains from Master TZ §4, plus the 4 cross-cutting technical domains not enumerated there (File Storage, Backend Architecture/Workers, Frontend, Infrastructure), and states which tables/concepts each owns.
**Owner:** architect
**Last updated:** 2026-08-17
**Dependencies:** [00_MASTER_TZ.md](00_MASTER_TZ.md) §4, [03_FEATURE_DEPENDENCY_MAP.md](03_FEATURE_DEPENDENCY_MAP.md)

## Business domains (from TZ §4)

| Domain | Tables (§4/§6-10) | Responsibility |
|---|---|---|
| **IDENTITY** | `users`, `roles`, `permissions`, `role_permissions` | Who the actor is, what they're allowed to do |
| **CATALOG** | `products`, `product_variants`, `product_images`, `brands`, `colors` | What's for sale. `brands` and `colors` are normalized lookup tables with stable surrogate IDs, not free-text fields — required so `discount_targets.target_type='BRAND'` (§7.1) can reference a stable `target_id` (see `REQ-CAT-005` in `01_REQUIREMENTS_MAP.md`) |
| **VEHICLE** | `car_brands`, `car_models`, `car_generations`, `product_compatibilities` | Which product fits which car |
| **PRICING** | `discounts`, `discount_targets` | What it costs right now |
| **INVENTORY** | `inventory_movements` (+ stock fields on `product_variants`) | Physical stock truth, append-only ledger |
| **COMMERCE** | `carts`, `cart_items`, `orders`, `order_items`, `stock_reservations` | Cart → order lifecycle, snapshotting |
| **PAYMENTS** | `payments`, `payment_receipts`, `refunds` (P3) | Money received, receipt review |
| **ENGAGEMENT** | `favorites`, `stock_notifications` | User retention hooks (P1) |
| **COMMUNICATION** | `conversations`, `messages`, `notifications`, `broadcasts`, `broadcast_targets` | User↔store messaging (P1) |
| **MARKETPLACE** | `sell_requests`, `sell_request_images` | Buy-back / consignment intake (P1) |
| **SEARCH** | `search_aliases` (+ `search_text` column on `products`) | Cyrillic/Latin-normalized lookup |
| **SECURITY** | `audit_logs`, `idempotency_keys` | Non-repudiation, replay protection |

## Cross-cutting technical domains (not in §4's table list, but load-bearing)

| Domain | Scope | Responsibility |
|---|---|---|
| **FILE STORAGE** | Upload directory layout (ADR-14), signed URL issuance (ADR-13), Pillow processing (§11.3) | No file exists outside `/var/comfort/uploads/`, no file is ever served unsigned |
| **BACKEND ARCHITECTURE** | Router/Service/Repository layering (§13.1), API surface (§13.4), workers (§15) | Enforces that Bot and Mini App share one Service layer; owns worker scheduling infra |
| **FRONTEND** | Mini App screens (§14), Telegram WebApp integration | Renders the domains above; owns no business logic |
| **INFRASTRUCTURE** | Server (§16), deployment (§17), monitoring | The substrate everything runs on. Postgres role/grant DDL (`CREATE ROLE`/`GRANT`/`REVOKE`, §12.2) is owned by `database`, not this domain — this domain owns only runtime config (`postgresql.conf`, `pg_hba.conf`) and the server itself |
| **OWNER ANALYTICS / REPORTING** | No new tables — read-only aggregation over COMMERCE, PAYMENTS, and SECURITY (audit) data (§3 `finance.view`/`analytics.view`, §13.4 `/owner/finance`, `/owner/analytics`) | Owned by `backend-core` (read/aggregation endpoints); `frontend` builds the OWNER screens on top. Previously undocumented — corrected per Phase 0 review finding "OWNER ANALYTICS OWNERSHIP" |

## Domain ownership boundaries — the rule

Per the TZ's own architecture principle (ADR-1, §23): **the server is the single source of truth.** Applied to domains, that means each domain listed above is the *single source of truth* for its tables and the invariants on them. A table appears in exactly one domain's row above. Any other domain that needs that data reads through the owning domain's Service layer — it never queries the table directly and never writes to it.

Concretely: Catalog never writes `stock_on_hand`/`stock_reserved` (Inventory's job, exercised through Commerce's order-confirm transaction). Communication never writes `orders.status` (Commerce's job) — it only reads order state to compose a notification. Bot never contains business logic (§13.1) — it calls the same Service functions the Mini App calls.

## Domain → phase mapping

| Domain | MVP (P0) tables shipped | P1 additions | P2/P3 additions |
|---|---|---|---|
| IDENTITY | all | — | admin management UI |
| CATALOG/VEHICLE/SEARCH | all | — | — |
| PRICING | all | — | — |
| INVENTORY | all | — | — |
| COMMERCE | `carts`,`cart_items`,`orders`,`order_items`,`stock_reservations` | order history UI | refunds (P3), delivery (P3) |
| PAYMENTS | `payments`,`payment_receipts` | — | `refunds` (P3), online payment (P3) |
| ENGAGEMENT | — | `favorites`,`stock_notifications` | loyalty (P3) |
| COMMUNICATION | `notifications` only (bot+in-app) | `conversations`,`messages`,`broadcasts`,`broadcast_targets` | — |
| MARKETPLACE | — | `sell_requests`,`sell_request_images` | — |
| SECURITY | all | — | audit panel UI (P2) |
| OWNER ANALYTICS/REPORTING (no owned tables, `backend-core`) | — | — | finance report, top products, admin activity report (P2); analytics events pipeline (P3) |

This confirms REQ-BE-003: ~20 of the ~30 tables ship in MVP; COMMUNICATION (minus notifications) and MARKETPLACE are P1.
