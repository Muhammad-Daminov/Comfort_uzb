# ADR-001 — Unified Backend, Frontend Never Touches DB

**Status:** Accepted (decided in Master TZ v1.0/v3.0)
**Owner:** architect
**Domain:** Backend Architecture (cross-cutting)
**Last updated:** 2026-08-17
**Source:** [00_MASTER_TZ.md](../00_MASTER_TZ.md) §1 ADR-1, §0.4

## Context
Earlier drafts (v1.0/v2.0, Supabase-based) considered letting the frontend read/write Postgres directly through RLS policies. That created a real conflict: "frontend should reach the DB via RLS" vs. "the server is the single source of truth" (§0.4). Price re-validation, stock atomicity, and permission checks cannot be safely delegated to RLS alone.

## Decision
One backend (FastAPI) is the only thing that talks to PostgreSQL. Both the Telegram Mini App and the Telegram Bot go through Nginx to FastAPI, which routes to a single shared Service layer regardless of which channel the request came from. The frontend never connects to the database, directly or through a generated REST layer.

```
Telegram Mini App ──HTTPS──▶ Nginx ──▶ FastAPI ──unix socket──▶ PostgreSQL
Telegram Bot ─────webhook──▶ Nginx ──▶ FastAPI ──▶ (same Service layer)
```

## Consequences
- No RLS is needed (see ADR context in §12.2) — Postgres is reachable only from the backend, on `localhost`.
- Backend and DB co-located on one VPS over a Unix socket instead of a network round trip (was 20–100ms on Supabase, now ~0.1ms) — this is what makes the §18 performance targets (catalog p95 <150ms) realistic.
- Bot must never contain business logic (§13.1) — it is a thin client of the same Service layer the Mini App uses.
- Every other backend agent (`backend-core`, `backend-commerce`, `backend-engagement`) builds on top of this layering; `bot` and `frontend` are presentation-only.
