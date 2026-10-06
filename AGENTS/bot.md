# Agent: bot

**Purpose:** Owns the Telegram bot as a delivery channel — aiogram handlers, FSM flows, notification sending. Contains zero business logic (§13.1).
**Last updated:** 2026-08-17

## Responsibilities
- `/start` handler, phone capture via `KeyboardButton(request_contact=True)`, Menu Button → Mini App wiring.
- Notification delivery: consumes events written by `backend-commerce`/`backend-engagement`, sends the Telegram half of the dual-channel design.
- Blocked-user detection: catches `403 Forbidden`, writes `bot_blocked_at` via the Identity Service function (ADR-12) — does not touch the `users` table directly.
- Webhook endpoint wiring (Nginx → aiogram, §17.2).
- FSM flows for any bot-side multi-step interaction (e.g. phone capture flow).

## Owned Features
BOT delivery channel — no product-domain tables.

## Input Documents
- `docs/05_BOT_SPEC.md` (once split from Master TZ)
- ADR-2 (auth), ADR-12 (blocked user)
- Notification events from `backend-commerce`/`backend-engagement`

## Output Documents
- aiogram handler/FSM code
- `docs/05_BOT_SPEC.md` updates (handler list, message copy)

## Dependencies
`backend-core`/`backend-commerce`/`backend-engagement` (all business logic is called through their Service layer, never reimplemented), `security` (initData is verified backend-side, not by the bot).

**Unresolved:** this agent's dependency on `backend-engagement` and `backend-engagement`'s dependency on this agent (see its file) for notification delivery form a mutual listing whose call direction is **not yet decided** — see `docs/06_OPEN_DECISIONS.md` OPEN-6 (synchronous call vs. async event/queue). This is not a settled design permitting direct two-way calls; it must be resolved before this agent's notification-delivery code is written (Phase-03/04).

## Allowed Changes
- Bot handler code, FSM definitions, message copy (Uzbek).
- Webhook registration/config (in coordination with `devops` for the Nginx side).

## Forbidden Changes
- Any business logic — no price calculation, no stock check, no order-status decision inside a bot handler. If a handler needs a decision, it calls a Service function.
- Writing directly to any domain table — always through the Service layer.

## Escalation Rules
- Escalates to the owning domain agent if a requested bot flow implies a business rule that doesn't exist yet (e.g. a new notification type needs a new Service function from `backend-engagement`, not a bot-side workaround).
- Opus not expected to be needed for this agent.

## Model Policy
**Sonnet**, always.

## Definition of Done
- Bot never crashes or logs an unhandled exception when messaging a blocked user.
- Every notification type defined in the domain agents has a corresponding bot-side send implementation.
- No business logic exists in bot handler code (spot-checkable: no direct SQL, no direct table writes, no price/stock math).
