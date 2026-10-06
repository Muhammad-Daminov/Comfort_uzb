# Phase 04 — Bot

**Owner:** bot
**Status:** ✅ Complete
**Last updated:** 2026-08-18
**Dependencies:** [Phase-03-Backend.md](Phase-03-Backend.md)

## Objective
Ship the Telegram bot as a thin delivery channel: onboarding, Mini App entry point, and notification delivery — zero business logic, per §13.1.

## Prerequisites
- Phase 03 backend endpoints/Service functions this agent will call already exist (at least auth, and whichever domain Service functions notifications originate from).

## Deliverables
- `/start` handler, phone capture flow, Menu Button wired to the Mini App URL.
- Notification send path consuming events from `backend-commerce`/`backend-engagement`.
- Blocked-user (`403`) handling wired to the Identity Service function (ADR-12).
- `docs/05_BOT_SPEC.md` written (handlers, FSM, Uzbek message copy).

## Definition of Done
- [x] Bot never crashes on a blocked-user send; `bot_blocked_at` set/cleared correctly (ADR-12, tested) — `tests/unit/test_notifications_poller.py`, `tests/integration/test_notification_delivery.py`, `tests/integration/test_bot_identity.py`.
- [x] Every notification type defined by domain agents has a working bot-side sender — the poller sends any `notifications` row regardless of `type`; no domain agent has shipped a concrete notification-writing type yet (`backend-engagement` is P1/Phase-10), so this is verified against manually-inserted test rows (see ADR-016 "Consequences").
- [x] No direct table writes or business logic present in bot handler code (spot-check) — every mutation in `backend/bot/handlers/start.py` and `backend/bot/notifications/poller.py` goes through `app.domains.identity.service`.
- [x] `docs/05_BOT_SPEC.md` matches implemented handlers exactly.

## OPEN-6 resolution (required before this phase's notification code)
Closed via [ADR-016](../adr/ADR-016-notification-delivery.md): async outbox through the existing `notifications` table, extended by migration `0013_notification_delivery` with one nullable `telegram_sent_at` column + partial index. The bot owns an in-process poll loop; `backend-engagement`/`backend-commerce` only ever write a row, never call the bot directly — no circular dependency.

Test totals: 45 unit (17 new: phone normalization, poller, start-handler) + 30 integration (8 new: bot identity flows, notification delivery) + the pre-existing 36 database tests (updated: `tests/db/test_migration_role_e2e.py` now expects 13 migrations/head `0013_notification_delivery`, otherwise unaffected) = 108 automated tests.

## Audit correction (2026-09-19)
- "FSM" above is aspirational: the phone-capture flow is two stateless handlers (contact share, and — added by the audit — a typed `+998…` number, which `uz.PHONE_INVALID` had promised but nothing handled). No aiogram FSM is used.
- `handlers/start.py` used to contain one direct `SELECT phone FROM users`; it now reads through `identity.repository.get_by_id`, so the "no direct SQL" DoD line in `AGENTS/bot.md` holds (stabilization pass, 2026-09-19).
- The notification poller now fetches with `FOR UPDATE SKIP LOCKED` inside one transaction (two uvicorn workers each run a poller), marks permanently-undeliverable rows handled instead of retrying them every 5 s, and honours `retry_after` on 429. Address-book contacts with no Telegram `user_id` are rejected. Malformed webhook bodies return 400.
