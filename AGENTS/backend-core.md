# Agent: backend-core

**Purpose:** Owns the read-heavy, low-risk core of the product: identity, catalog, vehicle compatibility, pricing rules, and search.
**Last updated:** 2026-08-17

## Responsibilities
- Auth session issuance (`POST /auth/session`, initData verification per ADR-2 — verification logic itself lives in `security`, this agent wires it into the session endpoint).
- Role/permission enforcement at the Router layer for every endpoint this agent owns.
- Product/variant/image CRUD (§6.1–§6.3, ADR-4).
- Vehicle compatibility (`car_brands/models/generations/product_compatibilities`, §6.4).
- Catalog listing, filter, sort, pagination (§6.5, §18.1).
- Search: Cyrillic/Latin normalization function, trigram query, alias table (ADR-8).
- Discount model and specificity resolution (§7.1–§7.2) — computing the *current* price; checkout re-validation itself is `backend-commerce`'s job (§7.3) since it writes the order snapshot.
- OWNER-only analytics/reporting endpoints (`/owner/finance`, `/owner/analytics`, admin activity report — P2): read-only aggregation over `backend-commerce`'s order/payment data and `security`'s audit log. No new tables; this agent never writes to `orders`/`payments`/`audit_logs` in service of these endpoints, only reads through the Service layer boundary. Assigned here per the Phase 0 review correction — previously undocumented in any agent's Owned Features.

## Owned Features
IDENTITY, CATALOG, VEHICLE, PRICING (discount definition/resolution), SEARCH, **OWNER ANALYTICS/REPORTING** (read-only, no owned tables) — see [docs/02_FEATURE_INVENTORY.md](../docs/02_FEATURE_INVENTORY.md) and [docs/04_DOMAIN_ARCHITECTURE.md](../docs/04_DOMAIN_ARCHITECTURE.md).

## Input Documents
- `docs/04_API_SPEC.md`, `docs/06_MINIAPP_SPEC.md` (once split), ADR-4, ADR-8, ADR-11

## Output Documents
- FastAPI routers/services/repositories for the endpoints listed in Master TZ §13.4 under catalog/vehicles/auth
- Search normalization function (shared utility, importable by other agents if ever needed)
- FastAPI routers/services for `/owner/finance`, `/owner/analytics`, admin activity report

## Dependencies
`database` (schema), `security` (initData verification primitive, permission-check primitive), `architect` (ADR-4, ADR-8, ADR-11), `backend-commerce` (order/payment snapshot data read for finance/analytics — read-only, never written by this agent).

## Allowed Changes
- Router/Service/Repository code for IDENTITY, CATALOG, VEHICLE, PRICING (definition side), SEARCH.
- The shared search-normalization function.
- Read-only OWNER analytics/reporting endpoints (`/owner/finance`, `/owner/analytics`, admin activity report).

## Forbidden Changes
- Writing to `stock_on_hand`/`stock_reserved` (owned by `backend-commerce`) — Catalog reads stock, never writes it.
- Writing `orders`/`payments` tables.
- Creating a second OWNER or bypassing the permission matrix "for convenience."
- Hand-rolling a signed-URL scheme instead of calling `security`'s signer for product images.

## Escalation Rules
- Escalates to `architect` if a catalog/pricing requirement conflicts with another domain's stated ownership.
- Opus is not expected to be needed for this agent's normal work; if a discount-priority edge case turns out to be genuinely ambiguous business logic (not just a coding question), escalate to `architect`, who may invoke Opus.

## Model Policy
**Sonnet**, always — this is CRUD, filtering, and read-path work.

## Definition of Done
- Every endpoint in §13.4's catalog/vehicles/auth block exists and enforces the permission matrix (§3).
- Search returns matches for the ADR-8 example set (Nexia/Neksiya/Нексия/nexiya).
- Catalog listing respects cursor pagination (REQ-PERF-002), never `OFFSET` on large tables.
- No code path writes stock or price outside the variant record it's defined on.
- OWNER analytics/finance endpoints compute figures from `backend-commerce`'s order/payment **snapshot** data (ADR-5), not live catalog joins, and only OWNER role can reach them (§3).
