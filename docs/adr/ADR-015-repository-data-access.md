# ADR-015 — Repository Layer Uses Raw asyncpg, Not SQLAlchemy Core

**Status:** Accepted
**Owner:** architect
**Domain:** Backend Architecture (cross-cutting: database, backend-core, backend-commerce, backend-engagement)
**Last updated:** 2026-08-17
**Source:** [00_MASTER_TZ.md](../00_MASTER_TZ.md) §13.2, §13.3; resolves [06_OPEN_DECISIONS.md](../06_OPEN_DECISIONS.md) OPEN-3

## Context
§13.2 names `asyncpg` as the required driver and lists `SQLAlchemy Core` as explicitly optional ("asyncpg (SQLAlchemy Core ixtiyoriy)"), without picking one. `06_OPEN_DECISIONS.md` OPEN-3 logged this as unresolved and required it to close before Phase-03 Repository-layer code is written, since it is a repo-wide convention affecting every domain's data-access code, not a per-feature choice.

## Decision
The Repository layer is written directly against `asyncpg` — hand-written parametrized SQL, no SQLAlchemy Core query-building layer, no ORM. Rationale:
- §13.3's own performance framing ("unix socket, ~0.1ms") and §0.1's minimal-overhead narrative both lean toward fewer layers between the Service layer and Postgres.
- Alembic (already adopted in Phase-02, raw-SQL migrations, no ORM models) already provides the schema-versioning safety that SQLAlchemy Core would otherwise add on top — adding a second query-building abstraction duplicates that value without a corresponding requirement.
- Every table and query pattern for the P0 domain set is already fully specified by Phase-02's migrations; there is no schema-discovery or dynamic-query-composition need that would justify Core's extra indirection.
- Matches the Open Decision document's own stated recommendation (option (a)), which this ADR formalizes rather than overrides.

Concretely: Repository functions take an `asyncpg.Connection` (or a transaction started on one) and return plain dict-like `Record` objects or typed dataclasses assembled by the Service layer — never raw dicts passed back to the Router layer un-typed. All parameters are passed positionally via asyncpg's `$1, $2, ...` placeholders — never string-interpolated (§12.1 SQL injection control).

## Consequences
- Every Repository module across `backend-core`, `backend-commerce`, and (later) `backend-engagement` follows this pattern; no domain may introduce SQLAlchemy Core or an ORM without a new ADR superseding this one.
- Connection/transaction passing is explicit: any Service function that must guarantee atomicity across multiple statements (order-confirm §8.2, reservation release, audit-write participation) passes the same `asyncpg.Connection`/transaction through every Repository call it makes — there is no session/unit-of-work object hiding this.
- `backend/app/db/pool.py` owns the single `asyncpg.create_pool(...)` instance (unix socket DSN per §13.3, `min_size=2, max_size=10`); Repository code never opens its own connection.
- OPEN-3 is now closed. This ADR is binding on all Phase-03+ Repository-layer code.
