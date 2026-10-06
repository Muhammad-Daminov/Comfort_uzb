"""OWNER domain: generic store_settings key/value persistence.

Revision ID: 0015_store_settings
Revises: 0014_compatibility_soft_delete
Create Date: 2026-08-18

Source: docs/00_MASTER_TZ.md §14.1 names a "Sozlamalar" (Settings) screen
for OWNER, and §13.4 lists `GET/PUT /owner/settings` in the API surface —
but the TZ never once states what a *setting* actually is anywhere in the
document (confirmed by exhaustive search during Phase 07 planning). Per
this phase's explicit instruction ("do NOT invent arbitrary application
settings... if the specification genuinely requires persistence, introduce
the smallest justified schema change"): this migration provides the
persistence mechanism and OWNER-only contract only — a generic key/value
store, seeded with zero rows. No business-specific setting field is
invented here. Populating real settings is a future, content-driven task
once the TZ or product owner names one (see docs/tasks/Phase-07-Owner.md
"Known limitations").

Design notes:
- `value` is JSONB so a future setting can be scalar, object, or array
  without another migration.
- `updated_by` is a plain FK to `users(id)` (no ON DELETE CASCADE, per the
  project's no-cascade policy) — nullable, since a hypothetical
  system-seeded default would have no human actor.
- PUT is an upsert (`INSERT ... ON CONFLICT (key) DO UPDATE`) — no DELETE
  operation is ever needed for this table's normal use, consistent with
  `comfort_app` having zero DELETE privilege on any table (§12.2; this is
  the lesson the Phase 06 acceptance audit's `product_compatibilities` bug
  already taught — designing the write path to never need DELETE in the
  first place, rather than adding a soft-delete column preemptively for a
  table with no delete requirement at all).
"""
from alembic import op

revision = "0015_store_settings"
down_revision = "0014_compatibility_soft_delete"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE store_settings (
            key        TEXT PRIMARY KEY,
            value      JSONB NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_by BIGINT REFERENCES users(id)
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS store_settings;")
