# AGENTS.md — COMFORT UZB Agent System

This is the project-level summary of the agent system. Per-agent detail (Purpose, Responsibilities, Owned Features, Input/Output Documents, Dependencies, Allowed/Forbidden Changes, Escalation Rules, Model Policy, Definition of Done) lives in `AGENTS/*.md`; the roster index is `AGENTS/README.md`.

## Why this agent set exists
The Master TZ (`docs/00_MASTER_TZ.md`) defines ~30 tables across 12 business domains plus infrastructure concerns. Rather than one agent trying to hold the whole system in mind, work is split along the TZ's real fault lines — see `docs/05_AGENT_ARCHITECTURE.md` for the full reasoning. 11 agents:

`architect`, `database`, `backend-core`, `backend-commerce`, `backend-engagement`, `bot`, `frontend`, `security`, `devops`, `qa`, `docs`.

## Responsibilities and ownership
Each agent owns a fixed set of domains/tables/contracts (see `docs/04_DOMAIN_ARCHITECTURE.md` for domain-to-table mapping and each `AGENTS/*.md` for the agent-to-domain mapping). Ownership means: that agent is the only one who changes that domain's schema shape, business rules, or shared contract. Everyone else consumes it through the Service layer (backend) or through documented cross-domain events (`docs/03_FEATURE_DEPENDENCY_MAP.md`).

The load-bearing ownership boundaries, restated:
- **Order status** — `backend-commerce` only.
- **Stock fields** (`stock_on_hand`/`stock_reserved`) — `backend-commerce` only; `backend-core` (Catalog) reads, never writes.
- **Permission matrix** — `backend-core` (Identity) defines it, every agent enforces it, none redefine it.
- **Audit log schema/write path** — `security` only. When an audit write participates in an atomic business transaction (e.g. order-confirm, §8.2), it MUST run on the same transaction/connection as the caller — never fire-and-forget.
- **Signed URL scheme** — `security` defines it, `devops` operates the Nginx side, every file-producing domain calls it rather than inventing its own.
- **DB schema (DDL), including Postgres role/grant DDL (§12.2)** — `database` only; no backend agent runs its own migration, and neither `security` nor `devops` write `CREATE ROLE`/`GRANT` statements (`security` sets the least-privilege policy, `devops` owns only runtime config like `pg_hba.conf`).
- **OWNER-only analytics/reporting** (finance, top products, admin activity — no owned tables) — `backend-core`, read-only over `backend-commerce`/`security` data. Corrected per Phase 0 review; previously undocumented.

## Escalation rules
- Default model for every agent: **Sonnet**.
- **Opus**, only for the specific cases named in each agent's `Model Policy` section — primarily `architect` (cross-module conflicts), `database` (transaction design/normalization), `backend-commerce` (concurrency/payment-flow), `security` (security-critical design/audits). No other agent escalates to Opus without first routing through `architect`.
- A TZ ambiguity or contradiction is never resolved by guessing — it's logged in `docs/06_OPEN_DECISIONS.md` and routed to `architect`.
- A cross-domain conflict (two agents' work implies different answers for a shared invariant) is routed to `architect` for adjudication, not resolved unilaterally by either agent.

## Communication rules
1. Changing another agent's owned state is a written request (a docs/tasks note, a PR description), never a direct edit.
2. Cross-domain reactions happen only through the documented event list in `docs/03_FEATURE_DEPENDENCY_MAP.md`.
3. `docs` may fix formatting, links, and staleness anywhere in the docs tree; it never changes a decision's content.
4. Every agent's `AGENTS/<name>.md` Definition of Done is the checklist that agent's own work is measured against — keep it current as scope evolves.

## Documentation policy
- `docs/00_MASTER_TZ.md` is the Single Source of Truth; nothing here overrides it, everything here derives from it.
- Every Markdown file under `docs/` and `AGENTS/` carries title/purpose/owner/last-updated/dependencies (enforced by `docs`).
- A completed task is not done until its documentation (Definition of Done checkboxes, phase status, index entries) is updated in the same change.
- No duplicated documentation: one topic, one source of truth, everything else links to it.

See `CLAUDE.md` for the permanent, always-in-context version of these rules.
