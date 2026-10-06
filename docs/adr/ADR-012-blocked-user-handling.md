# ADR-012 — Bot-Blocked User Handling

**Status:** Accepted
**Owner:** bot
**Domain:** Communication / Identity
**Last updated:** 2026-08-17
**Source:** [00_MASTER_TZ.md](../00_MASTER_TZ.md) §1 ADR-12

## Context
Users block the bot. A naive notification sender would crash or keep retrying against a `403 Forbidden` response, and broadcasts would waste rate-limit budget on dead recipients.

## Decision
On Telegram `403 Forbidden: bot was blocked`:
1. `UPDATE users SET bot_blocked_at = now() WHERE telegram_id = ?`
2. Exclude the user from broadcast targeting.
3. Still write the notification to the `notifications` table — it's visible next time they open the Mini App.
4. `bot_blocked_at` clears back to `NULL` automatically when the user sends `/start` again.

## Consequences
- `bot` catches the `403` at the send call site and performs step 1; `backend-engagement` (Communication) reads `bot_blocked_at` when building broadcast target lists (step 2) and always writes to `notifications` regardless of blocked status (step 3) — this is why REQ-CMN-002 calls notifications a "dual channel."
- No notification-sending code path may treat a blocked user as an error to surface to the admin/owner — it's an expected, handled state, not a failure.
- REQ-TST test coverage: "bot notification lari boradi, bloklangan user crash qilmaydi" is part of the MVP definition of done (§24).
