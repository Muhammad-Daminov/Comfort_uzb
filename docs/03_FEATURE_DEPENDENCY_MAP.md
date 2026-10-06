# 03 — Feature Dependency Map

**Purpose:** What must exist before what, at the domain and feature level. Used to sequence the roadmap (`docs/tasks/`) and to catch an agent starting work whose prerequisites aren't owned yet.
**Owner:** architect
**Last updated:** 2026-08-17
**Dependencies:** [02_FEATURE_INVENTORY.md](02_FEATURE_INVENTORY.md)

## Domain-level dependency graph

```
SECURITY (auth, permissions, signed URL, idempotency, audit)
   │  everything below requires this to exist first
   ▼
IDENTITY (roles, OWNER bootstrap)
   │
   ├──▶ CATALOG / VEHICLE / SEARCH ──┐
   │                                  │
   ├──▶ PRICING ◀────────────────────┘  (pricing reads catalog/variant)
   │        │
   │        ▼
   └──▶ COMMERCE (cart, order) ◀── INVENTORY (reservation, stock)
              │
              ▼
          PAYMENTS (receipt upload needs FILE STORAGE + SECURITY)
              │
              ▼
      WORKERS (reservation-expiry, receipt-purge — need COMMERCE/PAYMENTS to exist)
              │
              ▼
   COMMUNICATION / ENGAGEMENT / MARKETPLACE (P1, layered on top of COMMERCE+CATALOG)
              │
              ▼
   OWNER ANALYTICS (P2 — reads COMMERCE/PAYMENTS/AUDIT, no new writes)
```

`FILE STORAGE` (uploads, signed URLs) and `SECURITY` (auth, permissions, audit, idempotency) are cross-cutting foundations — nearly every other domain depends on them and they depend on nothing else in-app. `DEVOPS/INFRASTRUCTURE` is the substrate everything runs on; it must be stood up (§16–17 server + Postgres + Nginx) before any backend feature can be deployed, though local dev can proceed against a dev DB before production infra exists.

## Hard prerequisites (feature level)

| Feature | Requires | Why |
|---|---|---|
| Any `/admin/*` or `/owner/*` endpoint | IDENTITY: role/permission enforcement | REQ-SEC-005 — permission checked server-side on every call |
| Order creation | CATALOG (variant pricing), INVENTORY (reservation), PRICING (discount calc), SECURITY (idempotency key) | REQ-COM-001/002, REQ-INV-002 |
| Payment submission | COMMERCE (order must exist, in AWAITING_PAYMENT), FILE STORAGE (receipt upload + signed URL) | REQ-PAY-001, REQ-FS-002 |
| Admin payment approval | PAYMENTS (payment PENDING), INVENTORY (on-hand decrement in same tx), SECURITY (audit insert in same tx) | REQ-COM-004, ADR-6 |
| `comfort-reservation-expiry` worker | COMMERCE (orders/reservations exist), INVENTORY (release logic) | REQ-WRK-001 |
| `comfort-receipt-purge` worker | PAYMENTS (payment_receipts table + retention_until) | REQ-WRK-002, ADR-9 |
| `comfort-broadcast` worker | COMMUNICATION (broadcasts/broadcast_targets tables, P1) | REQ-WRK-003 |
| Sell-request → product conversion | CATALOG (product creation), FILE STORAGE (image move sell-requests→products) | REQ-MKT-001 |
| Stock notification delivery | ENGAGEMENT (subscription table), INVENTORY (stock change event), COMMUNICATION (notification channel) | REQ-ENG-002 |
| Owner finance report | COMMERCE + PAYMENTS (historical data), AUDIT (cross-check) | §3 finance.view |
| Mini App checkout screens | Backend: cart, order, payment, signed URL endpoints all live | REQ-FE-001 |
| Bot notifications | COMMUNICATION (notification writer), IDENTITY (bot_blocked_at) | REQ-BOT-001 |
| Production deploy | DEVOPS: server hardened (§12.5), Postgres roles (§12.2), Nginx secure_link tested, Alembic migrations run, OWNER seeded | REQ-OPS-014 |
| Load/E2E/security test suite | All P0 features implemented end to end | REQ-TST-001/005/006 |

## Shared-state boundaries (single source of truth per concept)

These are the concepts multiple domains touch — ownership must stay with exactly one agent/domain to avoid silent conflicting changes (see [05_AGENT_ARCHITECTURE.md](05_AGENT_ARCHITECTURE.md)):

| Shared concept | Single owner | Consumers who must NOT redefine it |
|---|---|---|
| `orders.status` state machine | Commerce/Payments domain | Bot, Frontend, Workers — they trigger transitions via the Service layer, never write status directly |
| `product_variants.stock_*` | Commerce/Payments domain (via Inventory) | Catalog domain reads it, never writes it |
| Permission matrix (`role_permissions`) | Identity domain | Every other domain enforces it, none redefine it |
| Audit log schema/write path | Security domain | All domains write through the shared audit helper, never a bespoke INSERT. **Architectural rule (Phase 0 review correction):** when an audit write participates in an atomic business transaction (e.g. order-confirm, §8.2 — order status + stock + audit all committed or none), the shared audit helper MUST execute on the same database transaction/connection as the caller. It must never be implemented as fire-and-forget or as its own independent transaction in a context where atomicity is required — doing so would silently break the "all-or-nothing" guarantee §8.2 depends on. See `AGENTS/security.md` (helper owner) and `AGENTS/backend-commerce.md` (primary caller under this constraint). |
| Signed URL signing/verification | Security domain (+ Devops for Nginx config) | File-producing domains (Catalog images, Payments receipts, Marketplace, Communication attachments) call the shared signer, never hand-roll one |
| Idempotency-key table/middleware | Security domain | Commerce, Payments, Communication (broadcast) consume it on their mutating endpoints |
| DB schema (DDL, indexes, constraints) | Database domain | All backend domains request schema changes via Database; no domain runs its own `ALTER TABLE` |

## Cross-domain events (who notifies whom)

| Event | Producer | Consumers |
|---|---|---|
| Order confirmed | Commerce | Inventory (stock decrement, same tx) → Bot (notify user) → Owner analytics (P2) |
| Payment approved/rejected | Payments | Commerce (order transition) → Bot (notify user) |
| Stock becomes available | Inventory | Engagement (stock-notification subscribers) → Bot |
| Sell-request approved/converted | Marketplace | Catalog (draft product created) |
| Reservation expired | Workers (reservation-expiry) | Commerce (order → EXPIRED), Inventory (release) |
| Bot blocked (403) | Bot | Identity (`bot_blocked_at`), Communication (broadcast exclusion, in-app notification only) |

## Sequencing implication for the roadmap

Because of the graph above, `docs/tasks/` phases run in this order: **Architecture → Database → Backend (Identity/Security first, then Catalog, then Commerce/Payments/Inventory, including P0 worker business logic) → Bot → Mini App → Admin/Owner UI → Security hardening → Deploy (worker scheduling/infra + P0 worker logic already built) → Optimization (P1/P2 rollout, including the P1 broadcast worker's logic).** This matches Phase-01..10 in `docs/tasks/`.

Corrected per Phase 0 review: there is no standalone "Workers" phase. Worker *business logic* ships together with the domain that owns it (`comfort-reservation-expiry` in Phase-03 with `backend-commerce`; `comfort-receipt-purge`/`comfort-idempotency-cleanup` early, with `security`'s Phase-03-prerequisite primitives; `comfort-broadcast` in Phase-10 with `backend-engagement`'s P1 rollout; `comfort-backup`/`comfort-health` are devops-owned end to end and are authored in Phase-09). Only the systemd scheduling/locking *infrastructure* for all six workers is deployed in Phase-09 — see `docs/tasks/Phase-03-Backend.md`, `Phase-09-Deploy.md`, `Phase-10-Optimization.md`.

### Relationship to Master TZ §22's own phase/timeline breakdown

TZ §22 ("RIVOJLANISH BOSQICHLARI") defines the TZ's own 13-step timeline (server setup 3d → TZ+schema → migrations+seed+roles 1wk → backend auth/catalog/cart 1.5wk → backend order/payment/stock 1.5wk → **workers+backup 0.5wk** → Mini App 2wk → admin panel 1wk → bot notifications 0.5wk → security+test 1wk → deploy 0.5wk → v1.1 → v1.2, ~10 weeks MVP total). This is captured as a source requirement (`REQ-BE-013` in `01_REQUIREMENTS_MAP.md`) but the `docs/tasks/Phase-01..10` roadmap is organized by **owning agent/deliverable** rather than by TZ §22's week-by-week grouping, and differs from it in one deliberate way: TZ §22 places "workers+backup" as its own standalone step (its phase 5) immediately after order/payment backend work. This Phase 0 roadmap does **not** carry a standalone Workers phase — instead, per the correction above, each worker's business logic is embedded in the phase of the domain that owns it, which is actually a closer match to TZ §22's own intent (workers built right after order/payment backend, not deferred) than the roadmap's earlier draft was. The one remaining difference from TZ §22 is that `comfort-broadcast`'s logic ships in Phase-10 (with P1 Communication work) rather than TZ §22's phase 5, because broadcast cannot exist before the `broadcasts`/`broadcast_targets` tables and Communication domain — which are themselves P1, not P0 — exist; TZ §22 itself doesn't separately break out P1 timing within its "workers+backup" step. No other TZ §22 sequencing intent is overridden.
