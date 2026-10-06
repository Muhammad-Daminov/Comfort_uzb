# ADR-007 — Idempotency Keys on All Mutating Endpoints

**Status:** Accepted
**Owner:** security
**Domain:** Security (cross-cutting)
**Last updated:** 2026-08-17
**Source:** [00_MASTER_TZ.md](../00_MASTER_TZ.md) §1 ADR-7

## Context
Mobile networks retry requests; a naive retry on order-create, payment-submit, or admin confirm/cancel could double-charge, double-reserve stock, or double-send a broadcast.

## Decision
Clients send `Idempotency-Key: <uuid v4>` on: order creation, payment, receipt upload, stock adjustment, confirm/cancel, broadcast. Backend stores `idempotency_keys(key, endpoint, user_id, request_hash, response_body, status_code, created_at)`. A repeated key returns the stored response without re-executing the action. Keys are purged after 24h by `comfort-idempotency-cleanup`.

## Consequences
- `security` owns the shared idempotency middleware/helper; `backend-commerce` and `backend-engagement` (broadcast) consume it, they don't reimplement it.
- REQ-TST-001 mandates a test: duplicate `Idempotency-Key` → action executes exactly once.
- The 24h TTL means clients must not reuse a key across unrelated requests, and the cleanup worker must run reliably (§15) or the table grows unbounded.
