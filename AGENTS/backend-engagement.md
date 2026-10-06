# Agent: backend-engagement

**Purpose:** Owns the P1 layer that sits on top of Catalog and Commerce — favorites, stock alerts, chat, broadcast, and the sell-request marketplace.
**Last updated:** 2026-08-17

## Responsibilities
- Favorites (`UNIQUE(user_id, variant_id)`, §10).
- Stock-availability notification subscriptions and firing logic (§10).
- Sell-request submission and review workflow, including the `APPROVED → CONVERTED` action that calls into `backend-core` to create a draft product (ADR-10).
- Chat: `conversations`/`messages`, admin reassignment preserving history (§10).
- Notification writing to the `notifications` table (the in-app half of the dual-channel design — the Telegram-send half is `bot`'s job) (ADR-12).
- Broadcast business logic: rate-limit/backoff rules, `broadcast_targets` tracking, resumability (§10) — scheduling infra for the `comfort-broadcast` worker is `devops`'s job.

## Owned Features
ENGAGEMENT, COMMUNICATION, MARKETPLACE — all P1, per [docs/02_FEATURE_INVENTORY.md](../docs/02_FEATURE_INVENTORY.md). Do not build ahead of P0 (REQ-BIZ-005) — this agent's work starts once P0 is stable.

## Input Documents
- `docs/04_API_SPEC.md`, ADR-10, ADR-12
- `backend-core`'s product-creation Service function (for sell-request conversion)
- `backend-commerce`'s order data (for order-related notifications)

## Output Documents
- FastAPI routers/services/repositories for `/favorites/*`, `/stock-notifications/*`, `/sell-requests/*`, `/conversations/*`, `/notifications`, `/admin/broadcasts`
- Broadcast worker business logic (called by `devops`'s systemd timer)

## Dependencies
`database`, `security` (idempotency on broadcast), `backend-core` (product creation on sell-request conversion), `backend-commerce` (order state for notifications), `bot` (Telegram-send half of notifications).

**Unresolved:** the dependency on `bot` above and `bot`'s reciprocal dependency on this agent are **not** a settled two-way-call design — see `docs/06_OPEN_DECISIONS.md` OPEN-6. Until OPEN-6 resolves, treat this agent's notification writes as producing a row (e.g. to `notifications`) that `bot` is responsible for observing, not as a direct call into `bot`'s send function — this keeps the two agents' code decoupled regardless of which alternative OPEN-6 picks.

## Allowed Changes
- Everything under ENGAGEMENT, COMMUNICATION, MARKETPLACE.

## Forbidden Changes
- Creating a product directly (must call `backend-core`'s Service function on sell-request conversion, not insert into `products` itself).
- Sending Telegram messages directly (must go through `bot`'s send path so blocked-user handling, ADR-12, is respected in one place).
- Approving a sell-request rejection without a reason (REQ-MKT-002).

## Escalation Rules
- Escalates to `architect` if broadcast rate-limiting needs to change (Telegram API limits are a platform constraint, not a local tuning knob).
- No routine Opus need identified for this domain; escalate only if a genuinely hard cross-domain bug surfaces (e.g. a broadcast/notification race with order state).

## Model Policy
**Sonnet**, always.

## Definition of Done
- Broadcast respects the 25 msg/sec cap, backs off correctly on 429, and never retries a 403.
- Resuming an interrupted broadcast only retries `FAILED` targets (idempotent).
- Stock notifications fire once per `(user, variant)` when stock crosses 0→positive, and `notified_at` prevents duplicate sends.
- Sell-request conversion produces a valid draft product with images correctly moved, source-tagged `CONSIGNMENT`.
