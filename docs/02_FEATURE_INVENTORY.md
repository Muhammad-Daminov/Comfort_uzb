# 02 — Feature Inventory

**Purpose:** Every feature in the product, grouped by domain, tagged with priority phase and the requirements it's built from. This is the unit of work handed to agents.
**Owner:** architect (maintained), docs (sync)
**Last updated:** 2026-08-17
**Dependencies:** [01_REQUIREMENTS_MAP.md](01_REQUIREMENTS_MAP.md)

Priority tags follow §2 of the Master TZ: **P0** MVP (~9wk), **P1** +3wk, **P2** +2wk, **P3** later. Domain codes match [01_REQUIREMENTS_MAP.md](01_REQUIREMENTS_MAP.md).

## IDENTITY
| Feature | Priority | Key requirements |
|---|---|---|
| Telegram initData auth (session issuance) | P0 | REQ-SEC-001..003 |
| Role model (OWNER/ADMIN/USER) + permission matrix enforcement | P0 | REQ-IDT-002..004, REQ-SEC-005 |
| OWNER bootstrap via migration (env var seed) | P0 | REQ-IDT-001 |
| Admin management (create/deactivate admins) | P2 | §3, owner-only |
| Phone capture via bot `request_contact` | P0 | REQ-IDT-005 |

## CATALOG / VEHICLE / SEARCH
| Feature | Priority | Key requirements |
|---|---|---|
| Product CRUD (draft/active/archived) | P0 | REQ-CAT-002 |
| Variant CRUD (SKU, color, price, initial payment, stock) | P0 | REQ-CAT-001, REQ-CAT-003 |
| Product image upload + primary image | P0 | REQ-CAT-004, REQ-FS-005/006 |
| Vehicle compatibility (brand→model→generation→product) | P0 | REQ-VEH-001 |
| Catalog listing (filter, sort, pagination) | P0 | REQ-CAT-002/003, REQ-PERF-002 |
| Cyrillic/Latin-normalized search + trigram + alias table | P0 | REQ-SRC-001..004 |

## PRICING
| Feature | Priority | Key requirements |
|---|---|---|
| Discount model (percent/fixed, targeted by variant/product/brand/car-model/all) | P0 | REQ-PRC-003/004 |
| Server-side checkout price re-validation + 409 on mismatch | P0 | REQ-COM-002 |

## INVENTORY
| Feature | Priority | Key requirements |
|---|---|---|
| Stock on-hand/reserved/available tracking | P0 | REQ-INV-001 |
| Reservation on order create, 24h TTL | P0 | REQ-INV-002, REQ-BIZ-016 |
| Append-only inventory_movements ledger | P0 | REQ-INV-003/004 |
| Manual stock adjustment (reason required) | P0 | REQ-INV-004 |

## COMMERCE
| Feature | Priority | Key requirements |
|---|---|---|
| Cart (add/update/remove items) | P0 | §13.4 |
| Order creation with snapshot | P0 | REQ-COM-001 |
| Order state machine + transition guard | P0 | REQ-COM-003 |
| Concurrent-confirm race protection (`FOR UPDATE`) | P0 | REQ-COM-004 |
| Order cancellation (user/admin, reason required) | P0 | REQ-COM-005 |
| Order history (user-facing list) | P1 | §2 |
| Refund lifecycle (REFUND_PENDING→REFUNDED) | P3 | REQ-COM-003 |
| Delivery | P3 | §2 |

## PAYMENTS
| Feature | Priority | Key requirements |
|---|---|---|
| Manual card-transfer payment submission | P0 | REQ-PAY-001 |
| Receipt photo upload | P0 | REQ-FS-002/004/005/006 |
| Admin payment review (approve/reject) | P0 | REQ-PAY-001/002 |
| Receipt visibility/hide tracking (before/after review) | P0 | REQ-FS-001 |
| Online payment gateway | P3 | §2 |

## ENGAGEMENT
| Feature | Priority | Key requirements |
|---|---|---|
| Favorites | P1 | REQ-ENG-001, REQ-BIZ-017 |
| Stock-availability notification subscription | P1 | REQ-ENG-002 |
| Loyalty program | P3 | §2 |

## COMMUNICATION
| Feature | Priority | Key requirements |
|---|---|---|
| User↔Admin chat (conversations + messages) | P1 | REQ-CMN-001 |
| Notifications (Telegram + in-app dual channel) | P0 | REQ-CMN-002, REQ-BOT-001 |
| Broadcast (rate-limited, resumable) | P1 | REQ-CMN-003 |

## MARKETPLACE
| Feature | Priority | Key requirements |
|---|---|---|
| Sell-request submission + images | P1 | REQ-MKT-001/002 |
| Sell-request review workflow (approve/reject/convert) | P1 | REQ-MKT-001 |
| Sell-request → draft product conversion | P1 | REQ-MKT-001 |

## SECURITY
| Feature | Priority | Key requirements |
|---|---|---|
| Signed URL issuance + Nginx `secure_link` verification | P0 | REQ-FS-002 |
| Rate limiting (app-level + Nginx) | P0 | REQ-SEC-009 |
| Audit log (immutable, trigger-enforced) | P0 | REQ-SEC-008 |
| Least-privilege DB role **policy** (app/migrate/backup — `security` defines the policy and reviews compliance; `database` owns and executes the `CREATE ROLE`/`GRANT`/`REVOKE` DDL) | P0 | REQ-SEC-007 |
| Idempotency-key infrastructure | P0 | REQ-SEC-004 |
| 14-case security test suite | P0 | REQ-TST-001 |
| Audit panel (owner-facing UI) | P2 | §2 |

## OWNER-ONLY ANALYTICS
**Owner agent: `backend-core`** (read-only reporting endpoints, no new tables — aggregates COMMERCE/PAYMENTS/SECURITY data; see [04_DOMAIN_ARCHITECTURE.md](04_DOMAIN_ARCHITECTURE.md) and [05_AGENT_ARCHITECTURE.md](05_AGENT_ARCHITECTURE.md)). Screens are `frontend`'s.

| Feature | Priority | Key requirements |
|---|---|---|
| Financial report (`/owner/finance`) | P2 | §3 finance.view |
| Top products / analytics dashboard | P2 | §3 analytics.view |
| Admin activity report | P2 | §12.3 audit-derived |
| Analytics events pipeline | P3 | §2 |

## FRONTEND (Mini App)
TZ §14.1 lists 17 USER screens (recount: Home, Katalog, Qidiruv, Filter, Product detali, Yoqtirilganlar, Savat, Checkout, To'lov, Chek yuklash, Buyurtmalar tarixi, Buyurtma detali, Sidena sotish, Chat, Profil, Bildirishnomalar, Sozlamalar — corrects the earlier miscount of 16) and 10 ADMIN screens. Split below by the priority of the underlying feature each screen exposes (§2), replacing the earlier "P0 core + P1 extras" hybrid tag.

| Feature | Priority | Key requirements |
|---|---|---|
| USER screens — P0 (13: Home, Catalog, Search, Filter, Product detail, Cart, Checkout, Payment, Receipt upload, Order detail, Profile, Notifications, Settings) | P0 | REQ-FE-001/002/003 |
| USER screens — P1 additions (4: Favorites, Order history list, Sell, Chat) | P1 | REQ-FE-001, REQ-BIZ-002 |
| ADMIN screens — P0 (7: Dashboard, Orders, Order detail, Payments, Products, Product editor, Stock) | P0 | REQ-FE-001 |
| ADMIN screens — P1 additions (3: Sell-requests, Chats, Broadcast) | P1 | REQ-FE-001, REQ-BIZ-002 |
| OWNER screens (5: Finance, Analytics, Admins, Audit, Settings) | P2 | REQ-FE-001 |
| Dark/light theme sync with Telegram | P1 | §2 |
| Client-side image compression before upload | P0 | REQ-FE-003 |

## BOT
| Feature | Priority | Key requirements |
|---|---|---|
| `/start`, phone capture, menu button → Mini App | P0 | §13.2, REQ-IDT-005 |
| Notification delivery (order/payment/broadcast events) | P0 | REQ-CMN-002 |
| Blocked-user handling | P0 | REQ-BOT-001 |

## WORKERS
| Feature | Priority | Key requirements |
|---|---|---|
| `comfort-reservation-expiry` | P0 | REQ-WRK-001 |
| `comfort-receipt-purge` | P0 | REQ-WRK-002 |
| `comfort-idempotency-cleanup` | P0 | REQ-WRK-004 |
| `comfort-backup` | P0 | REQ-WRK-005 |
| `comfort-health` | P0 | REQ-WRK-006 |
| `comfort-broadcast` | P1 | REQ-WRK-003 (depends on Broadcast feature) |

## DEVOPS / INFRASTRUCTURE
| Feature | Priority | Key requirements |
|---|---|---|
| Postgres role/grant DDL (`CREATE ROLE`/`GRANT`/`REVOKE` for `comfort_app`/`comfort_migrate`/`comfort_backup`) — owned by `database`, not `devops` | P0 | REQ-SEC-007 |
| Server hardening (SSH, ufw, fail2ban, unattended-upgrades) | P0 | REQ-OPS-002 |
| Postgres install + runtime tuning (`postgresql.conf`, `pg_hba.conf` only — role/grant DDL is owned by `database`, see [05_AGENT_ARCHITECTURE.md](05_AGENT_ARCHITECTURE.md)) | P0 | REQ-OPS-006 |
| Nginx (HTTPS, static, `/files/` secure_link, reverse proxy) | P0 | REQ-FS-002, REQ-OPS-003/009 |
| systemd services + timers for API/bot/workers | P0 | REQ-WRK-007 |
| Three-tier backup (pg_dump, WAL/PITR, snapshot) | P0 | REQ-OPS-010 |
| Alembic migration pipeline | P0 | REQ-OPS-011 |
| Deploy pipeline (git pull → migrate → restart → health check) | P0 | REQ-OPS-012 |
| Monitoring (uptime ping, disk alert, error tracking) | P0 | REQ-OPS-013 |
| Go-live checklist execution | P0 | REQ-OPS-014 |

## QA (cross-cutting, not owned by any single domain)
| Feature | Priority | Key requirements |
|---|---|---|
| Unit test suite (pricing, discount, transitions, search, signed URL) | P0 | REQ-TST-002 |
| Integration test suite (order/payment/stock/transaction) | P0 | REQ-TST-003 |
| Security test suite (14 cases) | P0 | REQ-TST-001 |
| E2E flow test | P0 | REQ-TST-005 |
| Load test (50 browse / 10 checkout) | P0 | REQ-TST-006 |
| Restore drill (monthly) | P0 | REQ-TST-007 |

## Feature counts

Corrected by direct recount of every row above (Phase 0 review found the previous footer — 62/41/11/6/4 — didn't match the table; the table rows are authoritative and were not trimmed or merged to hit a target number).

- **Total distinct features:** 82
- **P0 (MVP):** 59
- **P1:** 12
- **P2:** 6
- **P3:** 5

Per-section row counts, for auditability: IDENTITY 5, CATALOG/VEHICLE/SEARCH 6, PRICING 2, INVENTORY 4, COMMERCE 8, PAYMENTS 5, ENGAGEMENT 3, COMMUNICATION 3, MARKETPLACE 3, SECURITY 7, OWNER-ONLY ANALYTICS 4, FRONTEND 7, BOT 3, WORKERS 6, DEVOPS/INFRASTRUCTURE 10, QA 6 — sum = 82.
