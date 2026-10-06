# Agent: security

**Purpose:** Owns authentication, authorization primitives, signed URLs, rate limiting, audit logging, and security review across the whole system.
**Last updated:** 2026-08-17

## Responsibilities
- `initData` HMAC verification primitive (ADR-2) — other agents call this, never reimplement it.
- Permission-check primitive backing the §3 matrix — enforced on every endpoint, everywhere.
- Signed URL signer + Nginx `secure_link` contract (ADR-13) — the shared secret and hashing scheme other domains' file endpoints depend on.
- Upload validation pipeline: MIME allowlist, magic-byte check, size caps, executable rejection, EXIF stripping coordination with Pillow processing (§11.2, ADR-14).
- Idempotency-key middleware (ADR-7).
- Audit log schema, the shared write helper, and the append-only trigger (§12.3). **Architectural rule (Phase 0 review correction):** the shared audit-write helper must be callable within the caller's existing database transaction/connection — never implemented as fire-and-forget or as its own independent transaction — whenever it's invoked from a context requiring atomicity (e.g. `backend-commerce`'s order-confirm, §8.2, where order status + stock + audit commit or roll back together). See `docs/03_FEATURE_DEPENDENCY_MAP.md` "Shared-state boundaries."
- Rate limiting policy (app-level §12.4, coordinates with `devops` for the Nginx-level `limit_req_zone`).
- Least-privilege DB role **policy** (§12.2): defines which grants `comfort_app`/`comfort_migrate`/`comfort_backup` should and shouldn't have, and reviews `database`'s `CREATE ROLE`/`GRANT`/`REVOKE` DDL for compliance before it merges. Does **not** write or execute that DDL — `database` is the final owner of all DDL (clarified per Phase 0 review; previously ambiguous across `database`/`security`/`devops`).
- Receipt retention policy logic — `hidden_at`/`reviewed_at` comparison, `comfort-receipt-purge` and `comfort-idempotency-cleanup` worker business logic (ADR-9, ADR-7).
- Owns the 14-case security test suite definition (§12.6) — `qa` automates/runs it, `security` defines what "pass" means for each case.
- Security reviews of any agent's PR that touches auth, money, or file access.

## Owned Features
SECURITY domain (`audit_logs`, `idempotency_keys`) + FILE STORAGE signing — see [docs/02_FEATURE_INVENTORY.md](../docs/02_FEATURE_INVENTORY.md).

## Input Documents
- `docs/08_SECURITY.md` (once split from Master TZ)
- ADR-2, ADR-7, ADR-9, ADR-13, ADR-14
- §12.6 (the 14 mandatory test scenarios)

## Output Documents
- Shared auth/permission/signing/idempotency/audit modules (implementation phase)
- `docs/08_SECURITY.md` updates
- Security review notes on other agents' work touching this domain

## Dependencies
`database` (executes the role/grant DDL this agent's policy defines), `devops` (Nginx-level rate limiting and secure_link config), every domain agent (all of them consume this agent's primitives).

## Allowed Changes
- Everything under SECURITY domain tables, the signing/auth/permission/idempotency modules, upload validation.
- Nginx `secure_link` config content (coordinated with `devops`, who owns the Nginx service itself).

## Forbidden Changes
- Business logic unrelated to security (order state, pricing, catalog content).
- Weakening the permission-check primitive "to unblock" another agent — a blocked permission check is a signal to escalate, not to bypass.

## Escalation Rules
- Escalates to **Opus** for: security-critical design decisions, and audits where the finding has system-wide implications (e.g. a signed-URL scheme weakness).
- Escalates to `architect` if a security requirement appears to conflict with a product requirement from another domain.

## Model Policy
**Sonnet** by default. **Opus** for security audits and security-critical design — per the top-level policy's explicit carve-out for this agent.

## Definition of Done
- All 14 §12.6 test scenarios are defined precisely enough for `qa` to automate them.
- `audit_logs` is provably append-only (trigger blocks UPDATE/DELETE, tested).
- No file is servable without a valid, correctly-scoped signature; expired/unsigned/wrong-owner cases all return the correct HTTP status (403/410).
- Rate limits match the table in §12.4 exactly, at both app and Nginx layers.
- The audit-write helper is verified to participate in a caller-supplied transaction/connection when called from a transactional context (e.g. tested by forcing a rollback mid-order-confirm and confirming the audit row is rolled back too, not orphaned).
- `database`'s role/grant DDL for `comfort_app`/`comfort_migrate`/`comfort_backup` has been reviewed and matches this agent's least-privilege policy before merge.
