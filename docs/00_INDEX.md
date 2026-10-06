# 00 — Documentation Index

**Purpose:** Entry point into the COMFORT UZB documentation set. Start here.
**Owner:** docs
**Last updated:** 2026-08-17
**Dependencies:** none (this is the root)

## Source of truth
- [00_MASTER_TZ.md](00_MASTER_TZ.md) — the Master Technical Specification, treated as TZ v1.0. Never edit its meaning; only these derived documents get updated as work proceeds.

## Phase 0 — architecture & agent bootstrap
1. [01_REQUIREMENTS_MAP.md](01_REQUIREMENTS_MAP.md) — every requirement, ID'd and traced to a TZ section.
2. [02_FEATURE_INVENTORY.md](02_FEATURE_INVENTORY.md) — every feature, by domain and priority phase (P0–P3).
3. [03_FEATURE_DEPENDENCY_MAP.md](03_FEATURE_DEPENDENCY_MAP.md) — what must exist before what; shared-state ownership boundaries.
4. [04_DOMAIN_ARCHITECTURE.md](04_DOMAIN_ARCHITECTURE.md) — the 12 business + 4 technical domains and their table ownership.
5. [05_AGENT_ARCHITECTURE.md](05_AGENT_ARCHITECTURE.md) — the 11 agents, why this split, escalation policy.
6. [06_OPEN_DECISIONS.md](06_OPEN_DECISIONS.md) — points the TZ leaves genuinely unresolved; not blocking, tracked to a phase.

## Architecture Decision Records
See [adr/](adr/) — ADR-001 through ADR-017, one per architectural decision already made in the Master TZ (§1) or, for ADR-017, a v2-rebuild-brief decision formalized the same way.

## v2 rebuild (cost/refund/cancellation/AI admin assistant)
- [13_V2_REBUILD_AUDIT.md](13_V2_REBUILD_AUDIT.md) — Phase 1 audit for the v2 brief: what's reusable, the Hamyon capability matrix (100% NOT DOCUMENTED), the AI-assistant gap, and the credential-handling incident during this work.
- [14_AI_PROVIDERS.md](14_AI_PROVIDERS.md) — AI admin assistant provider architecture: `AnthropicAIProvider`/`GeminiAIProvider`/`StubAIProvider`, fallback, `AI_PROVIDER`/`*_API_KEY`/`GEMINI_MODEL` config, local/live testing, voice/image extension point (not yet built).
- [adr/ADR-017-post-confirmation-cancellation-refund.md](adr/ADR-017-post-confirmation-cancellation-refund.md) — closes OPEN-4/OPEN-6: CONFIRMED-order cancellation via admin-decided request, independent refund lifecycle.

## Implementation roadmap
See [tasks/](tasks/) — Phase-01 through Phase-10, each with objective/prerequisites/deliverables/definition of done.

## Implementation deliverables (Phase 02 onward)
- [03_DB_SCHEMA_PLAN.md](03_DB_SCHEMA_PLAN.md) — Phase 02's implementation record (schema decisions, roles/grants, migration/seed/verification strategy). The actual schema lives in code: `backend/alembic/versions/` (16 migrations), `backend/db/provision_roles.sql` (role/grant DDL), `backend/tests/db/` (32 verification tests, run against a real Postgres 16 instance).

## Audit
- [12_POST_AUDIT_STABILIZATION_REPORT.md](12_POST_AUDIT_STABILIZATION_REPORT.md) — 2026-09-19 stabilization pass: independent re-verification of every audit finding, state-transition/RBAC/concurrency matrices, financial-model assessment, AI-readiness, verdict. **Start here.**
- [11_FULL_SYSTEM_AUDIT_REPORT.md](11_FULL_SYSTEM_AUDIT_REPORT.md) — 2026-09-19 whole-system audit: every confirmed defect with evidence, what was fixed (with regression tests), what remains, what could not be verified. Read this before trusting any earlier phase's "PASS".

## Agents
See [../AGENTS/](../AGENTS/) — one file per specialized agent, plus [../AGENTS/README.md](../AGENTS/README.md) as the roster index.

## Root project files
- [../CLAUDE.md](../CLAUDE.md) — permanent project instructions (source-of-truth policy, model policy, escalation rules).
- [../AGENTS.md](../AGENTS.md) — agent responsibilities, ownership, communication rules (project-level summary; per-agent detail lives in `AGENTS/*.md`).

## Downstream documents named by Master TZ §25
1. ~~Server Setup Runbook~~ — **written**, see [09_DEPLOYMENT.md](09_DEPLOYMENT.md) and `deploy/` (Phase-09). Configuration and scripts exist and were verified locally where possible; no real VPS/domain exists yet — see that document's own "Deferred items"/"Known limitations".
2. ~~Complete PostgreSQL Schema (full DDL)~~ — **done**, see [03_DB_SCHEMA_PLAN.md](03_DB_SCHEMA_PLAN.md) and `backend/alembic/versions/`
3. ~~Backend API Specification (per-endpoint)~~ — **done**, see [04_API_SPEC.md](04_API_SPEC.md)
4. ~~Bot Specification (handlers, FSM, copy)~~ — **done**, see [05_BOT_SPEC.md](05_BOT_SPEC.md)
5. Mini App UI/UX Spec (screen by screen) — USER screens **done** ([06_MINIAPP_SPEC.md](06_MINIAPP_SPEC.md), Phase-05); ADMIN + OWNER screens **done** ([07_ADMIN_PANEL_SPEC.md](07_ADMIN_PANEL_SPEC.md), Phase-06/07)
6. ~~Deployment & Backup Runbook~~ — **written**, see [09_DEPLOYMENT.md](09_DEPLOYMENT.md) (Phase-09) — same real-VPS caveat as item 1 above.

~~`08_SECURITY.md` and `10_TESTING.md` (splitting Master TZ §12 and §19 out respectively)~~ — **done**, see [08_SECURITY.md](08_SECURITY.md) and [10_TESTING.md](10_TESTING.md) (Phase 08-FINAL, updated Phase 09). Load testing, browser/device testing, and the Nginx-dependent §12.6 cases remain explicitly undone within them — see each document's own labeling.
