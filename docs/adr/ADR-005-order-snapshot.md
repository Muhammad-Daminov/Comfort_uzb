# ADR-005 — Orders Store a Full Snapshot, Not Live References

**Status:** Accepted
**Owner:** backend-commerce
**Domain:** Commerce
**Last updated:** 2026-08-17
**Source:** [00_MASTER_TZ.md](../00_MASTER_TZ.md) §1 ADR-5

## Context
If `order_items` only referenced `product_variants` by FK, a later price edit or product rename would retroactively change historical orders — breaking receipts, disputes, and financial reporting.

## Decision
`order_items` captures a snapshot at order-creation time: `product_name_snapshot`, `variant_label_snapshot`, `sku_snapshot`, `unit_price`, `discount_amount`, `quantity`, `required_initial_payment`, `line_total`. Order-level aggregates are derived and stored: `total_amount = SUM(line_total)`, `required_initial_amount = SUM(required_initial_payment × quantity)`, `paid_amount` = sum of approved payments, `remaining_amount = total − paid`.

## Consequences
- Editing a product's price/name after an order exists never changes that order's numbers — required for REQ-BIZ-014 and financial audit integrity.
- `backend-commerce` computes and writes the snapshot once, at order creation (§7.3 server-side re-check happens right before this write) — it is never recomputed from live catalog data afterward.
- Reporting (`owner/finance`) reads snapshot fields, not live product/variant joins, when reconstructing historical revenue.
