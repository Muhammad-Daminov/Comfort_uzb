# ADR-002 — Auth via Telegram initData Only, SMS OTP Removed

**Status:** Accepted
**Owner:** security
**Domain:** Identity / Security
**Last updated:** 2026-08-17
**Source:** [00_MASTER_TZ.md](../00_MASTER_TZ.md) §1 ADR-2, §0.4

## Context
v1.0 had a contradiction: "SMS should not be the primary auth" vs. SMS OTP code still present. SMS via Eskiz.uz is paid, and OTP storage/expiry/brute-force protection is complexity Telegram already solves — Telegram has already verified the user before the Mini App ever opens.

## Decision
SMS OTP is removed entirely — not deprioritized, removed. Auth is Telegram `initData` only:
1. Mini App sends `window.Telegram.WebApp.initData`.
2. Backend recomputes `secret_key = HMAC_SHA256(key="WebAppData", msg=bot_token)` and `computed_hash = HMAC_SHA256(key=secret_key, msg=data_check_string)`, and requires `computed_hash == received_hash`.
3. `auth_date` must be less than 24h old.
4. Only after this check does the backend trust `telegram_id`.
5. If a phone number is needed, it's collected via the bot's `KeyboardButton(request_contact=True)` — free, no OTP.

`user_id` supplied by the frontend is never accepted as identity by itself.

## Consequences
- No SMS provider dependency, no OTP table, no brute-force-protection surface to build or test.
- REQ-SEC-004 (14-case security suite) includes "broken/expired initData → 401" as a mandatory test.
- Any future reintroduction of SMS auth requires a new ADR — do not silently re-add it because it "used to be in the code."
