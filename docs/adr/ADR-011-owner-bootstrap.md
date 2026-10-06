# ADR-011 — OWNER Bootstrap via Migration Only

**Status:** Accepted
**Owner:** database
**Domain:** Identity
**Last updated:** 2026-08-17
**Source:** [00_MASTER_TZ.md](../00_MASTER_TZ.md) §1 ADR-11

## Context
Exactly one OWNER must exist, and that account is the root of the permission tree — it cannot be created through any UI/API path an attacker or a bug could reach.

## Decision
Migration 001 seeds the OWNER row directly from an environment variable:
```sql
INSERT INTO users (telegram_id, role, status)
VALUES (:OWNER_TELEGRAM_ID, 'OWNER', 'ACTIVE')
ON CONFLICT (telegram_id) DO NOTHING;

CREATE UNIQUE INDEX idx_single_owner ON users ((role))
  WHERE role = 'OWNER' AND deleted_at IS NULL;
```
`OWNER_TELEGRAM_ID` is an env var, set before first deploy. No API endpoint, admin UI, or bot command can create or promote a user to OWNER.

## Consequences
- `database` owns this migration; `backend-core` (Identity) must never expose a code path that sets `role='OWNER'` — the partial unique index makes a second OWNER a constraint violation, but the API layer should reject the attempt before it reaches the DB.
- Losing access to the OWNER Telegram account requires a manual DB/migration intervention, not a self-service recovery flow — document this operational risk in the Server Setup Runbook (downstream doc, §25).
