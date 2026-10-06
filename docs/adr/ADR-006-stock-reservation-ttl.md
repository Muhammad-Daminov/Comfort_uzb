# ADR-006 — Stock Reservation With TTL

**Status:** Accepted
**Owner:** backend-commerce
**Domain:** Inventory / Commerce
**Last updated:** 2026-09-19 (amended — see "Amendment 2026-09-19")
**Source:** [00_MASTER_TZ.md](../00_MASTER_TZ.md) §1 ADR-6, §9

## Context
Without a reservation mechanism, two users could both "buy" the last unit before payment review resolves either order, or stock could get permanently stuck reserved by an abandoned checkout.

## Decision
Each variant tracks three numbers: `stock_on_hand` (physically present), `stock_reserved` (committed to open orders), `available = on_hand − reserved` (never negative, `CHECK` constraints on all three). Lifecycle:

| Event | Effect |
|---|---|
| Order created | `reserved += qty`, `expires_at = now() + 24h` |
| Order confirmed (admin, §8.2) | `on_hand -= qty`, `reserved -= qty`, reservation rows **consumed** (`released_at` stamped, no RELEASE movement) |
| Order cancelled | `reserved -= qty` |
| TTL elapsed (worker) | `reserved -= qty`, order → `EXPIRED` |

## Consequences
- Requires the `comfort-reservation-expiry` worker (§15, every 5min) — logic owned by `backend-commerce`, scheduling infra owned by `devops` (see [Open Decision 5](../06_OPEN_DECISIONS.md#open-5)).
- Every stock mutation goes through `inventory_movements` (append-only ledger, §9) and uses `FOR UPDATE` row locking to survive concurrent confirms (§8.2).
- A reservation never outlives 24h (REQ-BIZ-016) — this is a hard invariant the worker enforces, not a UI-level nicety.

## Amendment 2026-09-19 (full-system audit, finding H2)
The table's "Payment approved" row described the stock decrement as happening at payment approval; the implementation (`orders/service.py::confirm_order`, §8.2's exact SQL) performs it at **order confirm**, and payment approval only updates `paid_amount`. The row above is corrected to say so.

More importantly, nothing closed the `stock_reservations` rows at confirm: they stayed `released_at IS NULL`, and 24h later `comfort-reservation-expiry` released them a second time — `stock_reserved` either went negative (CHECK violation, worker wedged permanently on that row) or, with other open reservations on the variant, was silently under-counted (oversell). The lifecycle is therefore made explicit: **a reservation ends in exactly one of two ways** — *released* (cancel/expiry: `reserved -= qty`, RELEASE movement) or *consumed* (confirm: stock already deducted by the OUT movement, row stamped only). The worker additionally never selects reservations of `CONFIRMED` orders (backstop for rows confirmed before this amendment). Regression tests: `tests/integration/test_audit_regressions.py::test_h2_*`.
