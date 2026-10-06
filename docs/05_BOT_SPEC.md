# 05 — Bot Spec (Phase 04 scope)

**Purpose:** Handler-by-handler contract for the Telegram bot, matching `backend/bot/` exactly. The bot is a thin delivery channel per `docs/tasks/Phase-04-Bot.md` — onboarding, Mini App entry point, notification delivery. It contains zero business logic; every mutation goes through `app.domains.identity.service`, the same Service functions the Mini App's `/auth/session` path uses.
**Owner:** bot
**Last updated:** 2026-08-18
**Dependencies:** [00_MASTER_TZ.md](00_MASTER_TZ.md) §13.1, ADR-1, ADR-2, ADR-12, [ADR-016](adr/ADR-016-notification-delivery.md)

## Identity trust boundary
The bot never re-verifies `initData` (that's the Mini App's mechanism, ADR-2). A webhook update's `message.from_user.id` is trusted only after the webhook route itself validates `X-Telegram-Bot-Api-Secret-Token` against `TELEGRAM_WEBHOOK_SECRET` — requests without a matching header get `401` before any handler runs (`bot/main.py::build_webhook_router`).

## Handlers (`backend/bot/handlers/start.py`)

### `/start` (`CommandStart`)
1. Resolves/creates the user via `identity.service.get_or_create_user_from_telegram` (the exact function `POST /auth/session` also calls — one place a user row is ever created).
2. Clears `bot_blocked_at` unconditionally (guarded no-op if not set) — ADR-12: "Qayta /start bosganda bot_blocked_at = NULL." If this actually cleared a block, sends `BLOCKED_USER_WELCOME_BACK` first.
3. If the user has no `phone` yet: sends `WELCOME_NEW_USER` with the phone-request keyboard (`KeyboardButton(request_contact=True)`, ADR-2).
4. Otherwise: sends `WELCOME_BACK`.

### Contact share (`F.contact`)
1. Rejects a contact whose `user_id` doesn't match the sender (never trusts a forwarded contact for someone else).
2. Resolves/creates the user (same function as `/start`).
3. Calls `identity.service.record_phone`, which normalizes (§5.3: strips whitespace/-/(), adds a missing leading `+`) and writes through the guarded `UPDATE users SET phone = ...` — the same CHECK/unique-index constraints from migration `0001_identity` are the actual source of truth; this is not re-validated business logic, just a clear pre-check before the write.
4. `InvalidPhone` → `PHONE_INVALID`. Any other Postgres error → logged, `GENERIC_ERROR` shown, no traceback ever reaches the user.

## Menu Button (`bot/keyboards.py::miniapp_menu_button`)
`MenuButtonWebApp` pointed at `MINIAPP_URL` — the bot's Mini App entry point (ADR-1). Set once at bot startup (`bot/main.py::configure_bot`); no per-message logic.

## Notification delivery (`backend/bot/notifications/poller.py`) — ADR-016
An in-process poll loop (`run_notification_poller_forever`, 5s interval), not a systemd timer:
1. Selects `notifications` rows with `telegram_sent_at IS NULL`, joined to the owning user.
2. A blocked user's row is marked `telegram_sent_at` without a send attempt (ADR-12 — in-app channel still gets it, Telegram doesn't retry forever).
3. On send: `TelegramForbiddenError` → `identity.service.mark_bot_blocked`, row marked handled. Any other `TelegramAPIError` → logged, row left unmarked (retried next cycle). On success → row marked sent.
4. Guarded/idempotent throughout: a row is only ever selected while unsent, and every branch stamps `telegram_sent_at` exactly once (mirrors the reservation-release pattern from `AGENTS/backend-commerce.md`).

`backend-engagement` (P1) is the only agent that will write real `notifications` rows for domain events — Phase 04 ships the consumer with no live producer yet, verified with manually-inserted test rows (see `docs/adr/ADR-016-notification-delivery.md` "Consequences").

## Error handling (`backend/bot/errors.py`)
A router-level `@router.errors()` handler catches anything a handler's own try/except didn't — logs the exception, best-effort sends `GENERIC_ERROR` to the originating chat, never lets a traceback/internal detail reach a user.

## Localization (`backend/bot/locales/uz.py`)
Plain Uzbek-language constants module — no i18n framework exists elsewhere in the project (Master TZ names Uzbek/lotin as the only supported language), so none was introduced here.

## Deferred to later phases
Catalog/search/cart/order/payment/receipt UI — Mini App, Phase 05. Admin/Owner UI — Phase 06/07. `comfort-broadcast` worker logic and P1 `notifications` producers — `backend-engagement`, Phase 10. Nginx-level webhook proxy config, systemd unit for the bot process — `devops`, Phase 09.
