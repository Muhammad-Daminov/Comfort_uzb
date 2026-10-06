# ADR-003 — Money Is BIGINT So'm, Never Float

**Status:** Accepted
**Owner:** database
**Domain:** Pricing / cross-cutting
**Last updated:** 2026-08-17
**Source:** [00_MASTER_TZ.md](../00_MASTER_TZ.md) §1 ADR-3, §5.1, §20

## Context
So'm has no subunit in practical use here (no tiyin). Floating-point money fields are a classic source of rounding drift across discount math, snapshot totals, and payment reconciliation.

## Decision
Every money column is `BIGINT NOT NULL CHECK (price >= 0)`, storing whole so'm. `FLOAT`, `REAL`, `DOUBLE PRECISION` are forbidden for any monetary value anywhere in the stack — DB, backend, frontend display formatting included.

## Consequences
- Discount math (§7), order totals (ADR-5), and payment amounts (§8.3) all do integer arithmetic — no rounding-mode decisions needed.
- Code review / QA checklist item: reject any PR introducing a float for a price, discount value, or payment amount.
- Applies to `products`/`product_variants.price`, `variants.required_initial_payment`, `discounts.value` (when `kind='FIXED'`), `orders.total_amount/required_initial_amount/paid_amount/remaining_amount`, `order_items.unit_price/discount_amount/line_total`, `payments.amount`.
