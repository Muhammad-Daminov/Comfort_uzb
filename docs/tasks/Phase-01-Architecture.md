# Phase 01 — Architecture

**Owner:** architect
**Status:** ✅ Complete (this Phase 0 bootstrap)
**Last updated:** 2026-08-17
**Dependencies:** [00_MASTER_TZ.md](../00_MASTER_TZ.md)

## Objective
Turn the Master TZ into a maintainable documentation and agent system before any code is written: requirements map, feature inventory, dependency map, domain architecture, agent architecture, ADRs, and open decisions.

## Prerequisites
- Master TZ available and readable in full (`docs/00_MASTER_TZ.md`).

## Deliverables
- `docs/01_REQUIREMENTS_MAP.md` through `docs/06_OPEN_DECISIONS.md`
- `docs/adr/ADR-001` through `ADR-014`
- `AGENTS/*.md` (11 agent files + README)
- `docs/tasks/Phase-01` through `Phase-10` (this roadmap)
- Root `CLAUDE.md` and `AGENTS.md`

## Definition of Done
- [x] Every requirement in the Master TZ has a traced ID in `01_REQUIREMENTS_MAP.md`.
- [x] Every feature has an owning domain and an owning agent.
- [x] All 14 TZ-decided architecture points are formalized as ADRs.
- [x] Every genuinely open/ambiguous TZ point is logged in `06_OPEN_DECISIONS.md`, not guessed.
- [x] No application code, migrations, or deployment config written in this phase.
