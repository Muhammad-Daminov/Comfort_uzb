# ADR-016 — Notification Delivery: Async Outbox via the `notifications` Table

**Status:** Accepted
**Owner:** architect
**Domain:** Communication / Bot (cross-cutting: bot, backend-engagement)
**Last updated:** 2026-08-18
**Source:** [00_MASTER_TZ.md](../00_MASTER_TZ.md) §10, ADR-12; resolves [06_OPEN_DECISIONS.md](../06_OPEN_DECISIONS.md) OPEN-6

## Context
§10 and ADR-12 specify the dual-channel notification design (Telegram message + `notifications` row for the Mini App) but not the trigger mechanism connecting the domain agent that decides a notification is needed (`backend-commerce`/`backend-engagement`) to the agent that sends the Telegram half (`bot`). `AGENTS/bot.md` and `AGENTS/backend-engagement.md` list each other as dependencies with no stated call direction — read literally as direct two-way function calls, this becomes a real circular code dependency. OPEN-6 logged this and required it to close before Phase-04's notification-delivery code is written.

## Decision
**Asynchronous, one-directional outbox** — option (b) from the Open Decision document, formalized here rather than re-derived:

- The domain agent that decides a notification is needed only ever writes a row to `notifications` (already created in migration `0010_communication_p0`). It never calls into `bot` directly.
- `bot` owns a polling loop, entirely within its own process, that reads unsent `notifications` rows and sends the Telegram half. It never calls into `backend-commerce`/`backend-engagement` to "ask" for notifications — it only reads the table through the standard connection pool, same access pattern as every other Repository-layer read.
- This requires the table to distinguish "sent via Telegram" from "read in the Mini App" — `read_at` already covers the latter, but nothing tracked the former. Migration `0013_notification_delivery` adds one nullable column, `telegram_sent_at TIMESTAMPTZ`, plus a partial index `WHERE telegram_sent_at IS NULL` for the poll query (same shape as `stock_reservations (expires_at) WHERE released_at IS NULL` from Phase 02). No existing row's meaning changes; the column is `NULL` for all pre-existing rows, which is exactly "not yet sent."
- The poll loop's send step is guarded and idempotent: a row is only ever picked up while `telegram_sent_at IS NULL`, and every send attempt (success, blocked-user, or otherwise-handled) results in `telegram_sent_at` being stamped exactly once — the same "guarded UPDATE, check the effect, never re-run a completed side effect" discipline already established for `stock_reservations` release (Phase 02 acceptance audit) and reused verbatim here, not reinvented.

## Consequences
- No circular dependency: `backend-engagement` -> `notifications` table -> `bot`. One direction, decoupled by the table itself acting as the durable queue.
- `bot`'s poll loop is an in-process background task, not a new systemd timer — it runs for as long as the bot process runs, which is already always-on (webhook delivery requires it). This does not expand `devops`'s Phase-09 worker-scaffolding scope.
- A blocked user's row (per ADR-12) is still marked `telegram_sent_at` by the poller — "handled," not "delivered" — so the poller doesn't retry it forever; the in-app `notifications` row remains visible in the Mini App regardless.
- `backend-engagement` (P1, Phase-10) is the only agent that writes rows for real events; Phase 04 ships the consumer with nothing yet producing real rows, verified instead with a manually-inserted test row. This is expected, not a gap — P1 work does not build ahead of P0 (REQ-BIZ-005).
- OPEN-6 is now closed. This ADR is binding on `bot` and `backend-engagement`.

## Addendum (2026-10-06) — `backend-commerce` also writes real rows for the P0 order/payment lifecycle

**Context.** The original decision above (and `AGENTS/backend-engagement.md`'s ownership listing) assigned all real-event notification writes to `backend-engagement` (P1, Phase-10), with Phase 04 shipping only the consumer. A full stabilization audit (2026-10-06) confirmed this literally: `bot/notifications/poller.py` was real and tested, but zero domain code anywhere wrote a `notifications` row — every existing test proved the consumer only, via a manually-inserted row (`tests/integration/test_notification_delivery.py`'s own docstring says so explicitly). This meant a user's order being confirmed, cancelled, or their payment being approved/rejected — all P0 `backend-commerce` events — never actually produced a Telegram message or an in-app row, in practice, for as long as `backend-engagement` remained unbuilt.

**Decision.** Rather than wait for the P1 `backend-engagement` module to exist, `backend-commerce` now writes `notifications` rows directly for the four order/payment transitions users need to see in the P0 checkout flow: order confirmed, order cancelled (admin/owner-initiated only — a self-cancel needs no notification), payment approved, payment rejected. Implemented in `app/notifications.py` (one `create_notification()` helper, same table, same poller, same ADR-016 mechanics — not a second notification system) and called from `orders/service.py`/`payments/service.py` on the same connection/transaction as the state transition itself, so a rollback of the transition rolls the notification back too.

**What this does not change.** The *mechanism* (async one-directional outbox via the `notifications` table, poller as sole consumer) is exactly as originally decided above — this addendum only moves *which domain is allowed to write rows for which events* for this one slice of events. `backend-engagement`'s eventual P1 scope (favorites, stock-availability, chat, sell-request, broadcast notifications) is unaffected and still belongs entirely to that future module; this addendum does not pull any of *that* forward, only the four order/payment events already named above.

**Consequence for `AGENTS/backend-engagement.md`.** That file's "Notification writing to the `notifications` table" ownership line should be read as "every notification type except the four order/payment ones `backend-commerce` now owns directly" — not amended line-by-line here to avoid rewriting that agent's whole scope description for one addendum.
