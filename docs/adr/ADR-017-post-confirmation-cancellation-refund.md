# ADR-017 — Post-Confirmation Cancellation and Independent Refund Lifecycle

**Status:** Accepted
**Owner:** backend-commerce
**Domain:** Commerce / Finance
**Last updated:** 2026-09-29
**Source:** v2 rebuild brief §10-§11; closes `docs/06_OPEN_DECISIONS.md` OPEN-4 and OPEN-9.

## Context

ADR-005/ADR-006 and the P0 state machine (`orders/state_machine.py`) made `CONFIRMED` a terminal state —
correct for P0, but OPEN-4 flagged that refund states were only deferred, not rejected, and OPEN-9 flagged
that a *paid* order (`paid_amount > 0` while still `UNDER_REVIEW`) could still be user-cancelled directly,
leaving money recorded as revenue with no way to reverse it. The v2 brief requires: a paid customer must
never self-cancel; cancellation after payment goes through an admin decision; cancellation and refund are
independently tracked, never conflated.

## Decision

1. **`cancel_order` (user-facing, existing endpoint) is unchanged in mechanics but gains a guard**: it
   already only accepts pre-`CONFIRMED` statuses via `assert_transition_allowed`; we additionally forbid
   it whenever `orders.paid_amount > 0`, regardless of status (closes OPEN-9 option (a)). A user with an
   approved payment sitting on a not-yet-confirmed order must go through the same request flow as #2.
2. **New `cancellation_requests` table.** A `USER` on their own `CONFIRMED` order (or any order with
   `paid_amount > 0`) files a request (reason required, ≥10 chars, same discipline as `orders.cancel`).
   At most one `PENDING` request per order (partial unique index). An `ADMIN`/`OWNER` approves or denies
   it — never the requesting user, never automatic.
3. **Approval transitions `CONFIRMED → CANCELLED`** (new edge in `ALLOWED_TRANSITIONS`, reachable *only*
   from the dedicated `approve_cancellation_request` service function, never from the generic
   `cancel_order` path — preserving "a CONFIRMED order is never UPDATEd directly outside its own guarded
   transition"). Stock is restored with a fresh `IN` inventory movement (there is no open reservation to
   release on a CONFIRMED order — it was already consumed at confirm time per ADR-006's amendment).
4. **New `refunds` table, independent of both `orders.status` and `cancellation_requests.status`.**
   Approving a cancellation never auto-creates or auto-completes a refund. An authorized admin separately
   records one: `method` (`CASH` or `CARD`), `amount`, `reason`, `status`
   (`PENDING`/`COMPLETED`/`FAILED`), linked to the order and optionally a payment. `CARD` refunds are
   recorded manually (status set by the admin after confirming the reversal happened out-of-band) because
   no Hamyon refund API is documented (`docs/13_V2_REBUILD_AUDIT.md` §2) — automating it would be
   inventing an endpoint. If Hamyon's refund API is documented later, `PaymentProvider.refund()` gets a
   real implementation and `CARD` refunds can auto-transition to `COMPLETED`; until then every refund
   (`CASH` or `CARD`) is admin-attested.
5. **Historical revenue is untouched.** `orders.paid_amount`/`order_items.line_total` snapshots
   (ADR-005) are never rewritten by a cancellation or refund — a `CANCELLED` order with a `COMPLETED`
   refund is how the ledger represents "money came in, then went back out," not a retroactive edit of
   what was sold.

## Consequences

- `orders/state_machine.py`: `CONFIRMED: set()` becomes `CONFIRMED: {"CANCELLED"}`, but the code path
  that performs it is new and separate from `cancel_order`; `cancel_order` itself gets the
  `paid_amount > 0` guard.
- New permissions: `cancellation_requests.create` (USER, ADMIN, OWNER), `cancellation_requests.review`
  (ADMIN, OWNER), `refunds.manage` (ADMIN, OWNER) — migration 0017.
- Owner/finance reporting can now show `gross revenue` vs `refunded` vs `net`, all from stored,
  independently-stated fields — no derived/implied state.
- Closes OPEN-4 and OPEN-9 in `docs/06_OPEN_DECISIONS.md`.
