"""SECURITY domain: audit_logs (append-only), idempotency_keys.

Revision ID: 0011_security
Revises: 0010_communication_p0
Create Date: 2026-08-17

Source: docs/00_MASTER_TZ.md §12.3 (audit_logs + trigger, copied verbatim),
ADR-7 (idempotency_keys, copied verbatim), §18.2 (indexes).

Design notes:
- The append-only trigger is the one place in the whole schema TZ
  explicitly demands DB-level enforcement (§12.3) rather than leaving it
  to application discipline — contrast with orders.status/payments.status/
  inventory_movements elsewhere in this migration set, which are
  deliberately NOT trigger-enforced because TZ doesn't ask for it there.
  This is also the concrete mechanism behind the Phase 0 review's
  "audit-write transaction safety" rule (docs/03_FEATURE_DEPENDENCY_MAP.md
  "Shared-state boundaries"): because this INSERT is a normal statement
  inside whatever transaction calls it, and the table has no other write
  path, a caller that includes this INSERT in the same transaction as
  its order-confirm UPDATEs gets atomicity for free from Postgres itself
  — the trigger only has to block illegitimate UPDATE/DELETE, not
  participate in transaction plumbing.
- `idempotency_keys` gets one extra index beyond ADR-7's literal schema:
  `created_at`, to support the `comfort-idempotency-cleanup` worker's
  24h-TTL scan (REQ-WRK-004) without a sequential scan.

FIX (Phase 02 acceptance audit, finding "audit_logs REVOKE executed before
the table exists"): `backend/db/provision_roles.sql` is documented to run
BEFORE the first `alembic upgrade head`, which meant its audit_logs-specific
`REVOKE UPDATE, DELETE ... / GRANT INSERT, SELECT ...` (narrowing §12.2's
blanket `comfort_app` grant) referenced a table that didn't exist yet,
failed silently (psql doesn't abort on a statement error by default), and
never got reapplied — leaving `comfort_app` with UPDATE on `audit_logs` via
the blanket `ALTER DEFAULT PRIVILEGES` grant, contradicting §12.2. Fixed at
the root here: this migration creates the table, so it owns the table (the
role that issues CREATE TABLE becomes its owner), which gives it authority
to REVOKE/GRANT on it regardless of run order — applying the narrowing
immediately after creation guarantees the correct privilege state exists
the instant `audit_logs` does, independent of whether/when
`provision_roles.sql` ran. Guarded by `IF EXISTS (... pg_roles ...)` so
this migration still runs cleanly in local dev setups that never provision
`comfort_app` at all (see `backend/README.md`'s quick start).
"""
from alembic import op

revision = "0011_security"
down_revision = "0010_communication_p0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE audit_logs (
            id         BIGSERIAL PRIMARY KEY,
            actor_id   BIGINT REFERENCES users(id),
            actor_role TEXT,
            action     TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id  BIGINT,
            old_data   JSONB,
            new_data   JSONB,
            ip         TEXT,
            metadata   JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX ON audit_logs (actor_id, created_at DESC);
        CREATE INDEX ON audit_logs (entity_type, entity_id, created_at DESC);
        """
    )

    # §12.3, copied verbatim from the Master TZ.
    op.execute(
        """
        CREATE FUNCTION prevent_audit_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'audit_logs is append-only';
        END $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_no_mutation
            BEFORE UPDATE OR DELETE ON audit_logs
            FOR EACH ROW EXECUTE FUNCTION prevent_audit_mutation();
        """
    )

    # §12.2's audit_logs-specific narrowing, applied here (not only in
    # provision_roles.sql) so it's guaranteed regardless of provisioning
    # order — see module docstring "FIX" note above. No psql :'var'
    # interpolation involved here, so the DO $$ ... $$ block is safe
    # (that pitfall was specific to psql variables, not DO blocks
    # in general — see provision_roles.sql's own comment on that).
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'comfort_app') THEN
                REVOKE UPDATE, DELETE ON audit_logs FROM comfort_app;
                GRANT INSERT, SELECT ON audit_logs TO comfort_app;
            END IF;
        END
        $$;
        """
    )

    op.execute(
        """
        CREATE TABLE idempotency_keys (
            key           UUID PRIMARY KEY,
            endpoint      TEXT NOT NULL,
            user_id       BIGINT NOT NULL REFERENCES users(id),
            request_hash  TEXT NOT NULL,
            response_body JSONB,
            status_code   INTEGER,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX ON idempotency_keys (created_at);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS idempotency_keys;")
    op.execute("DROP TRIGGER IF EXISTS audit_no_mutation ON audit_logs;")
    op.execute("DROP FUNCTION IF EXISTS prevent_audit_mutation();")
    op.execute("DROP TABLE IF EXISTS audit_logs;")
