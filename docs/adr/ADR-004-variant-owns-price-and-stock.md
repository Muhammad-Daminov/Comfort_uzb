# ADR-004 — Variant Owns Price and Stock, Never the Product

**Status:** Accepted
**Owner:** database
**Domain:** Catalog
**Last updated:** 2026-08-17
**Source:** [00_MASTER_TZ.md](../00_MASTER_TZ.md) §1 ADR-4, §6.2

## Context
v1.0 had `price` on both `product` and `variant`, which is a contradiction: two sources of truth for the same number, no rule for which wins.

## Decision
`price`, `stock_on_hand`/`stock_reserved`, `required_initial_payment`, and `color` live only on `product_variants`. `products` holds name, description, brand, compatibility, and search text — never price or stock. Every product has at least one variant; if there's no real color distinction, a single `DEFAULT` variant is created. Catalog listing shows `MIN(variant.price)` as "850 000 so'mdan" (starting from).

## Consequences
- `backend-core` (Catalog) never writes a price or stock column on `products` — if such a column exists, it's a schema bug to flag to `database`.
- Any "product price" concept in UI copy or API responses must resolve to `MIN(variant.price)` across active variants, not a stored product-level field.
- Simplifies ADR-5 (order snapshot) — there's exactly one place price comes from.
