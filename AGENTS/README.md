# COMFORT UZB — Agent Roster

**Purpose:** Index of all specialized agents, their ownership, and the rules governing how they work together.
**Owner:** architect
**Last updated:** 2026-08-17
**Dependencies:** [docs/05_AGENT_ARCHITECTURE.md](../docs/05_AGENT_ARCHITECTURE.md)

11 agents, sized to the actual domains in the Master TZ — see [docs/05_AGENT_ARCHITECTURE.md](../docs/05_AGENT_ARCHITECTURE.md) for why this split (not a fixed template) was chosen.

| Agent | File | Owns |
|---|---|---|
| architect | [architect.md](architect.md) | Cross-domain architecture, ADRs, dispute resolution |
| database | [database.md](database.md) | Schema/DDL/migrations for all 12 business domains; final owner of Postgres role/grant DDL (§12.2) |
| backend-core | [backend-core.md](backend-core.md) | Identity, Catalog, Vehicle, Pricing, Search, OWNER analytics/reporting (read-only) |
| backend-commerce | [backend-commerce.md](backend-commerce.md) | Commerce, Payments, Inventory |
| backend-engagement | [backend-engagement.md](backend-engagement.md) | Engagement, Communication, Marketplace (all P1) |
| bot | [bot.md](bot.md) | Telegram bot delivery channel |
| frontend | [frontend.md](frontend.md) | Telegram Mini App (USER/ADMIN/OWNER) |
| security | [security.md](security.md) | Auth, permissions, signed URLs, audit, rate limiting |
| devops | [devops.md](devops.md) | Server, Nginx, Postgres runtime config (not roles/grants), workers infra/scheduling, backup |
| qa | [qa.md](qa.md) | Testing, edge cases, acceptance criteria |
| docs | [docs.md](docs.md) | Documentation sync, indexing, de-duplication |

## Ownership rule (restated from [docs/05_AGENT_ARCHITECTURE.md](../docs/05_AGENT_ARCHITECTURE.md))

Every table, contract, and shared invariant has exactly one owning agent. See [docs/03_FEATURE_DEPENDENCY_MAP.md](../docs/03_FEATURE_DEPENDENCY_MAP.md) "Shared-state boundaries" for the concrete list (order status, stock fields, permission matrix, audit schema, signed-URL scheme, idempotency table, DB schema, audit-write transaction-safety). No agent edits another's owned state directly — it goes through that agent's Service layer or, for schema (including Postgres role/grant DDL — `database`'s final call, `security` sets the policy), a request to `database`. OWNER-only analytics/reporting (finance, top products, admin activity — no owned tables) is `backend-core`'s, corrected per the Phase 0 review. The `bot`↔`backend-engagement` notification-delivery dependency is unresolved pending [OPEN-6](../docs/06_OPEN_DECISIONS.md) — do not treat it as a settled direct-call design.

## Escalation rules (restated from CLAUDE.md model policy)

- Default model: **Sonnet**, for every agent, on all routine work.
- **Opus**, only when genuinely warranted, and only for: `architect` (major cross-module conflicts), `database` (transaction design, normalization conflicts), `backend-commerce` (concurrency, payment-flow design), `security` (security-critical design, audits). Every other agent stays on Sonnet by policy — if one of them thinks it needs Opus, it escalates to `architect` first rather than invoking it directly.
- An escalation states the specific problem in one sentence before switching models — never "just to be safe."

## Communication rules

1. A change to another agent's owned table/contract is a written request, not a direct edit.
2. Cross-domain reactions happen only through the events listed in [docs/03_FEATURE_DEPENDENCY_MAP.md](../docs/03_FEATURE_DEPENDENCY_MAP.md) "Cross-domain events" — no agent polls another's internal state.
3. TZ ambiguity is documented in [docs/06_OPEN_DECISIONS.md](../docs/06_OPEN_DECISIONS.md), never silently guessed.
4. `docs` may fix formatting/links/staleness anywhere; it never changes a decision.

## Documentation policy

Every completed task updates documentation in the same change — a feature isn't "done" if the relevant `AGENTS/*.md` Definition of Done or `docs/tasks/Phase-*.md` status wasn't updated. See root [CLAUDE.md](../CLAUDE.md).
