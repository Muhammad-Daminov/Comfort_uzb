# 05 — Agent Architecture

**Purpose:** Maps the 12 business + 4 technical domains onto a working set of specialized agents, sized to the actual TZ rather than a fixed template. States why each split (or merge) was made.
**Owner:** architect
**Last updated:** 2026-08-17
**Dependencies:** [04_DOMAIN_ARCHITECTURE.md](04_DOMAIN_ARCHITECTURE.md), [03_FEATURE_DEPENDENCY_MAP.md](03_FEATURE_DEPENDENCY_MAP.md)

## Why 11 agents, not 16 or 6

16 domains 1:1 would fragment ownership across concerns that share a single database transaction (e.g. order-confirm touches Commerce + Inventory + Security/audit atomically — splitting those into separate agents would force every confirm-order change through a 3-way handoff for no benefit). 6 broad agents ("backend", "frontend") would blur the finance/security/concurrency boundaries the TZ is explicit about (ADMIN must never reach `finance.view`; stock math must never be "close enough").

The actual fault lines in the TZ are: **transactional core** (money, stock, order state — needs the most care, most likely Opus escalation) vs. **read-heavy catalog** (browsing, search — low risk, pure Sonnet) vs. **engagement/comms** (bolt-on P1 features layered on top, low risk) vs. **delivery channels** (bot, frontend — presentation only, no business logic per §13.1) vs. **non-functional concerns that cut across everything** (security, database, devops, qa, docs, architecture). That gives 11 agents.

## Agent list and domain ownership

| # | Agent | Owns (business domains) | Model default | Opus trigger |
|---|---|---|---|---|
| 1 | `architect` | Cross-domain architecture, ADRs | Sonnet | Major cross-module design conflicts |
| 2 | `database` | Schema/DDL for all 12 business domains | Sonnet | Transaction design, normalization conflicts |
| 3 | `backend-core` | IDENTITY, CATALOG, VEHICLE, PRICING, SEARCH, OWNER ANALYTICS/REPORTING (read-only, no owned tables) | Sonnet | — (escalate to architect if conflict) |
| 4 | `backend-commerce` | COMMERCE, PAYMENTS, INVENTORY | Sonnet | Concurrency (order-confirm race), payment-flow design |
| 5 | `backend-engagement` | ENGAGEMENT, COMMUNICATION, MARKETPLACE | Sonnet | — |
| 6 | `bot` | Bot delivery channel (aiogram, FSM) — no domain tables | Sonnet | — |
| 7 | `frontend` | Mini App (USER/ADMIN/OWNER screens) — no domain tables | Sonnet | — |
| 8 | `security` | SECURITY domain + FILE STORAGE signing | Sonnet | Security-critical design, audits |
| 9 | `devops` | INFRASTRUCTURE, workers scheduling, deploy, backup | Sonnet | — |
| 10 | `qa` | Cross-cutting: testing, acceptance criteria | Sonnet | — |
| 11 | `docs` | Documentation sync, no product domain | Sonnet | — |

Full per-agent detail (responsibilities, inputs/outputs, escalation, DoD) lives in `AGENTS/<name>.md`.

## Why Commerce+Payments+Inventory are one agent

Order-confirm is a single Postgres transaction spanning `orders.status`, `product_variants.stock_*`, `inventory_movements`, and `audit_logs` (§8.2). Splitting Commerce from Inventory would mean two agents co-owning one `BEGIN...COMMIT` block — exactly the "no agent may silently change another agent's domain" rule this bootstrap is supposed to prevent. Payments joins the same agent because payment-approval is the trigger for that same transaction (ADR-6: "To'lov tasdiqlandi → on_hand -= qty"). Security/audit stays a separate agent because the audit *schema and write path* (REQ-SEC-008) is shared infrastructure used by every domain, not something Commerce should own — `backend-commerce` calls the shared audit helper `security` defines, same as everyone else.

## Why Bot and Frontend are separate from all backend agents

§13.1 is explicit: "Bot da biznes logika yozilmaydi" (no business logic in the bot) — both Bot and Mini App are pure consumers of the Service layer that `backend-*` agents own. Keeping them as their own agents matches the TZ's own layering and keeps presentation changes (copy, screens, FSM flow) from ever touching business rules.

## Why Database is separate from backend-* agents

Per §17.4, all schema change goes through Alembic and is versioned; "server ga psql bilan qo'lda kirib ALTER TABLE qilish taqiqlanadi." Centralizing schema ownership in one agent enforces that no backend agent can silently alter another domain's table shape, and gives one place to reconcile ~30 tables' worth of cross-domain FKs, indexes (§18.2), and constraints.

## Why OWNER analytics/reporting belongs to `backend-core`, not a new agent

The Phase 0 review found these features (finance report, top products, admin activity report, analytics events) had no documented owner anywhere in the agent set. They don't warrant a 12th agent: they create no new tables (§4's domain model has no "analytics" domain) and are pure read/aggregation over data `backend-commerce` (orders, payments) and `security` (audit) already own. `backend-core` already owns IDENTITY (roles/permissions, including `finance.view`/`analytics.view` enforcement) and is the natural place for read-only cross-domain reporting endpoints — it reads through the same Service-layer boundary every other consumer uses, and writes nothing new.

## Postgres role/grant DDL ownership — `database`, not `devops` or `security`

The Phase 0 review found three documents implying partial, unreconciled ownership of §12.2's `CREATE ROLE`/`GRANT`/`REVOKE` statements. Resolved as: **`database` is the single final owner of this DDL** — it is DDL, and §17.4 already makes `database` the sole owner of all DDL, versioned through Alembic. `security` defines the least-privilege *policy* (which grants each role should and shouldn't have) and reviews the DDL for compliance, but does not write or execute it. `devops` owns only the runtime/network side of Postgres access control — `pg_hba.conf`, `postgresql.conf`, `listen_addresses` — never `CREATE ROLE`/`GRANT` statements themselves.

## Escalation summary (model policy)

- Default: **Sonnet** for all agents, all routine work (CRUD, docs, formatting, tests, refactors, bot/frontend work).
- **Opus**, and only when genuinely warranted: architecture decisions with real trade-offs, DB normalization conflicts, security-critical design, concurrency/race conditions (order-confirm, stock reservation), payment-flow design, audit architecture, hard cross-domain bugs, ADR authorship for the above.
- An agent that thinks it needs Opus states *why* in one sentence before escalating (see each agent file's "Escalation Rules"). No agent escalates for formatting, boilerplate, or "just to be safe."

## Communication rules between agents

1. A domain's tables/contracts are only ever changed by their owning agent (see [03_FEATURE_DEPENDENCY_MAP.md](03_FEATURE_DEPENDENCY_MAP.md) "Shared-state boundaries").
2. A schema change request from `backend-*` to `database` is a written request (a docs/tasks note or PR description), not a direct edit to another agent's migration.
3. Cross-domain events (see dependency map's "Cross-domain events" table) are the only sanctioned way one domain reacts to another's state change — no domain polls or peeks at another's internal table.
4. Ambiguity in the TZ is never silently resolved by guessing — it's written up as an Open Decision (see [06_OPEN_DECISIONS.md](06_OPEN_DECISIONS.md)) and routed to `architect`.
5. `docs` is the only agent that edits files outside its own domain's docs — specifically to fix cross-links, indexes, and staleness, never to change decisions.
