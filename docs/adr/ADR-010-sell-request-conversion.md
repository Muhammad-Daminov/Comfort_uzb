# ADR-010 — Sell-Request → Product Conversion

**Status:** Accepted
**Owner:** backend-engagement
**Domain:** Marketplace
**Last updated:** 2026-08-17
**Source:** [00_MASTER_TZ.md](../00_MASTER_TZ.md) §1 ADR-10

## Context
The store buys consignment items from users (§10 marketplace) and needs a controlled path from "user offered to sell this" to "this is now a listed product," without letting a sell-request become a product automatically or silently.

## Decision
Lifecycle: `PENDING → UNDER_REVIEW → APPROVED → CONVERTED` (product created), with side-branches `REJECTED` (reason mandatory) and `SOLD` (sold outside the store, never listed). Only after `APPROVED` does an admin explicitly click "convert to product," which:
1. Creates a draft `product` with `source = 'CONSIGNMENT'` and `source_sell_request_id = <id>`.
2. Copies images from `sell-requests/{request_id}/` to `products/{product_id}/`.
3. Leaves price/stock empty for the admin to fill in before publish.

## Consequences
- `backend-engagement` (Marketplace) owns the sell-request state machine and the conversion action; it calls into `backend-core` (Catalog) to create the draft product rather than inserting into `products` directly — respects the domain-ownership rule.
- Rejection without a reason is invalid input (REQ-MKT-002) — enforce at the API layer, not just in the UI.
- This is a P1 feature — do not build ahead of P0 per REQ-BIZ-005.
