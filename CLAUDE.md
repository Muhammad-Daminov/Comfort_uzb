# CLAUDE.md — COMFORT UZB Permanent Project Instructions

This file governs every agent and every session working in this repository.

## Source of truth
`docs/00_MASTER_TZ.md` is the Single Source of Truth for this project, treated as TZ v1.0 regardless of the "v3.0" label inside the document itself. Every other document under `docs/` and `AGENTS/` is derived from it and must never contradict it. If code and the TZ disagree, the TZ is updated first, then the code — never the reverse (Master TZ's own closing principle).

## Business rules are non-negotiable
Never violate a business rule stated in `docs/01_REQUIREMENTS_MAP.md` §20 (`REQ-BIZ-*`) or an accepted ADR in `docs/adr/`. Examples: stock never negative, a `CONFIRMED` order is never `UPDATE`d directly, an `APPROVED` payment never reverts to `PENDING`, ADMIN never sees financial data, exactly one OWNER, audit log is append-only, no file is ever served unsigned. If a task seems to require breaking one of these, stop and escalate — do not quietly work around it.

## Never silently change requirements
If the TZ is ambiguous, under-specified, or internally inconsistent, do not guess. Log it in `docs/06_OPEN_DECISIONS.md` with the affected domain and proposed alternatives, and route it to the `architect` agent. Do not resolve it by picking whichever reading is easiest to implement.

## Every architecture change requires an ADR
A decision that changes a table's meaning, a state machine, an auth mechanism, a file-handling scheme, or any other cross-cutting behavior gets a new or amended ADR in `docs/adr/` before implementation, not after. Routine implementation choices within an already-decided ADR (e.g. which library function to call) do not need one.

## Keep docs synchronized
Every completed task updates the relevant documentation in the same change: the owning `AGENTS/*.md` file's Definition of Done, the relevant `docs/tasks/Phase-*.md` status, and `docs/00_INDEX.md` if a new document was added. Undocumented "done" work is not done. The `docs` agent exists specifically to catch drift — use it, don't bypass it.

## Model usage policy
Default to **Sonnet** for all agents, all the time: documentation, CRUD, API work, frontend work, bot handlers, SQL, tests, refactoring, routine debugging.

Use **Opus** only for the narrow set of cases named per-agent in `AGENTS/*.md` — architecture decisions with real trade-offs, database normalization conflicts, security-critical design, concurrency/race-condition work (order-confirm, stock reservation), payment-flow design, audit architecture, hard cross-domain bugs, and ADR authorship for the above. Never use Opus for formatting or simple file generation. State the specific reason before escalating.

Token efficiency is a hard requirement: never rewrite an unchanged file, edit only the affected section, reuse prior context, avoid duplicated explanations, keep exactly one source of truth per topic.

## Agent system
See `AGENTS.md` for responsibilities/ownership/escalation/communication rules, and `AGENTS/README.md` for the full roster with links to each agent's detailed charter.

## Phase discipline
Follow `docs/tasks/Phase-01` through `Phase-10` in order. Do not implement P1/P2/P3 features (Master TZ §2) while P0 (MVP) items in the same area are incomplete, unless explicitly instructed otherwise.
