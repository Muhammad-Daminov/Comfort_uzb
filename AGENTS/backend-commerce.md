# Agent: backend-commerce

**Purpose:** Owns the transactional core of the business — cart, order, stock, and payment — where correctness under concurrency has real financial consequences.
**Last updated:** 2026-08-17

## Responsibilities
- Cart CRUD (`/cart`, `/cart/items`).
- Order creation with server-side price/stock re-validation and snapshot write (ADR-5, §7.3).
- Order state machine and its transition guard — the *only* code path allowed to change `orders.status` (ADR-... state machine, §8.1).
- Concurrent-confirm protection: `SELECT ... FOR UPDATE`, guarded transition, stock decrement, `inventory_movements` insert, audit insert — all in one transaction (§8.2).
- Order cancellation with mandatory reason (§8.4).
- Stock reservation lifecycle and `inventory_movements` ledger (ADR-6, §9). **Mandatory release pattern (Phase 02 acceptance audit, finding "reservation double-release safety requirement"):** every code path that releases a `stock_reservations` row — `comfort-reservation-expiry` AND order-cancellation's release path, with no exceptions — MUST use a guarded, rowcount-checked update, never an unconditional one:
  ```sql
  UPDATE stock_reservations
  SET released_at = now()
  WHERE id = :reservation_id
    AND released_at IS NULL;
  -- then inspect the affected row count
  ```
  Only if the row count is **1** may the corresponding `product_variants.stock_reserved` decrement run. If the row count is **0**, the reservation was already released (by a concurrent worker run, a retry, or a race with order-cancellation) — the caller MUST skip the stock decrement, not run it anyway. **Why this is mandatory, not a style preference:** `stock_reserved >= 0` is the only CHECK constraint guarding this table, and a double-release doesn't necessarily go negative — if the variant has other active reservations, a double-release of one reservation silently steals headroom from the others (their units vanish from `stock_reserved` while their `stock_reservations` row still shows `released_at IS NULL`), which the schema cannot detect, only application discipline can prevent. Live-reproduced during the Phase 02 acceptance audit: `stock_on_hand=10, stock_reserved=4` (order A holds 2, order B holds 2) → naively releasing order A's reservation twice drove `stock_reserved` to 0 with order B's reservation still marked active, silently overselling 2 units and setting up order B's own eventual release/confirm to hit the CHECK constraint and fail. See `backend/tests/db/test_schema.py::TestReservationRelease` for the guarded-pattern regression test (Phase 03 must add the equivalent Service-layer test once this logic is implemented — the DB-layer test proves the *pattern* is safe, not that the eventual Python code follows it).
- Payment submission, admin review (approve/reject), receipt upload wiring (§8.3) — receipt *file* handling (signing, retention) is `security`'s job; this agent owns the `payments`/`payment_receipts` business logic and status transitions.
- Business logic for the `comfort-reservation-expiry` worker (scheduling infra owned by `devops`).

## Owned Features
COMMERCE, PAYMENTS, INVENTORY — see [docs/02_FEATURE_INVENTORY.md](../docs/02_FEATURE_INVENTORY.md). This is the domain most likely to need Opus.

## Input Documents
- `docs/04_API_SPEC.md`, ADR-5, ADR-6, ADR-7, ADR-9
- `security`'s idempotency-key middleware, signed-URL signer
- `database`'s schema for `carts/cart_items/orders/order_items/stock_reservations/payments/payment_receipts`

## Output Documents
- FastAPI routers/services/repositories for `/cart/*`, `/orders/*`, `/payments/*`, `/admin/orders/*`, `/admin/payments/*`
- Reservation-expiry worker logic (called by the systemd timer `devops` sets up)

## Dependencies
`database` (schema), `security` (idempotency keys, signed URLs, audit helper), `backend-core` (reads current price/discount at checkout — calls, doesn't duplicate, Catalog/Pricing logic).

## Allowed Changes
- Everything under COMMERCE, PAYMENTS, INVENTORY.
- The reservation-expiry worker's business logic.

## Forbidden Changes
- Product/variant metadata (name, description, images) — that's `backend-core`.
- Writing audit log rows with a bespoke format — must use `security`'s shared audit helper (REQ-SEC-008). **Architectural rule (Phase 0 review correction):** when calling that helper from inside the order-confirm transaction (§8.2), the call MUST execute on the same transaction/connection as the order-status and stock updates — never as a separate fire-and-forget write. Breaking this silently defeats the atomicity §8.2 requires. See `docs/03_FEATURE_DEPENDENCY_MAP.md` "Shared-state boundaries" and `AGENTS/security.md`.
- Skipping the idempotency-key check on order/payment endpoints "because it's simpler" — it's a hard requirement (ADR-7).
- Reverting an `APPROVED` payment to `PENDING` under any circumstance (REQ-BIZ-008).

## Escalation Rules
- Escalates to **Opus** for: the order-confirm concurrency design itself (§8.2), payment-flow edge cases with real money-safety implications, any stock-reservation redesign.
- Routine CRUD on cart items, listing orders, standard status displays stay on Sonnet.
- State the specific race condition or money-safety question in one sentence before escalating.

## Model Policy
**Sonnet** by default. **Opus** for concurrency problems, transaction consistency, and payment-flow design — the exact cases named in the top-level model policy.

## Definition of Done
- Parallel-confirm test (two admins, one order) passes: exactly one succeeds, the other gets a clear "already confirmed" error, not a silent double-decrement.
- Parallel last-unit-purchase test (two users, one unit) passes: exactly one order succeeds.
- Reservation TTL never exceeds 24h; expired reservations are released and orders move to `EXPIRED` within one worker cycle (5min).
- `APPROVED` payment is provably one-way (tested).
- Every order/payment mutation appears in `inventory_movements` and/or `audit_logs` as appropriate.
- The audit-helper call inside order-confirm is provably transaction-participant (tested by forcing a rollback and confirming the audit row rolls back too, not orphaned).
- Every reservation-release code path (`comfort-reservation-expiry` and order-cancellation) uses the guarded `WHERE released_at IS NULL` + rowcount-checked pattern above; a concurrent/duplicate release attempt on the same reservation is provably a no-op, verified under true concurrent execution (not just sequential simulation), and does not disturb an unrelated reservation's stock.
