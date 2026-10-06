# Phase 10 — Optimization & P1/P2 Rollout

**Owner:** all agents (coordinated by architect)
**Status:** Not started
**Last updated:** 2026-08-17
**Dependencies:** [Phase-09-Deploy.md](Phase-09-Deploy.md)

## Objective
Post-launch: tune performance against §18 targets under real traffic, then roll out P1 (favorites, stock notifications, sell-request, chat, broadcast, order history, dark/light mode) and P2 (finance report, analytics, admin management, audit panel) in priority order, never skipping ahead of P0 stability.

## Prerequisites
- Phase 09 complete, production stable for a reasonable observation window.
- No open Sev-1/Sev-2 issues from the initial production run.

## Deliverables
- Performance tuning pass against §18 targets using real traffic data (index tuning, query plan review, connection pool sizing).
- P1 feature set (`backend-engagement` + corresponding `frontend`/`bot` work): favorites, stock notifications, sell-request, chat, broadcast, order history, dark/light mode.
- `backend-engagement`: **`comfort-broadcast` worker BUSINESS LOGIC** (rate-limit/backoff rules, `broadcast_targets` tracking, resumability — REQ-WRK-003, §10) built alongside the rest of the Communication P1 work, not deferred to a later deploy step. `devops` adds this worker's systemd timer once the logic exists (either here or as a small follow-up to Phase-09, whichever lands first) — the logic itself must not be authored at deploy time.
- P2 feature set (OWNER analytics/finance, admin management, audit panel) if not already covered in Phase 07.
- Updated `docs/tasks/` status across all phases.

## Definition of Done
- [ ] §18 performance targets hold under real production load, not just the Phase 08 synthetic load test.
- [ ] P1 features shipped without regressing any P0 Definition-of-Done item.
- [ ] `comfort-broadcast` business logic is implemented and unit-tested (rate limit, backoff, resumability) independent of its systemd wiring.
- [ ] P2 features shipped, OWNER-only access verified in production.
- [ ] `docs/` fully reflects the shipped system state (owned by `docs`, verified by `architect`).
