"""discount_targets soft delete — v2 rebuild P2-4.

Revision ID: 0021_discount_targets_softdel
Revises: 0020_discounts_manage_permission
Create Date: 2026-09-30

`comfort_app` has zero DELETE privilege on any table, blanket, no
exceptions (§12.2, backend/db/provision_roles.sql) — the same rule
migration 0014_compatibility_soft_delete already documents and fixed for
`product_compatibilities`. `discount_targets` (migration 0005_pricing)
never got the same treatment because P2-4 is the first time anything
removes a row from it. Add `deleted_at` and switch removal to an UPDATE.
"""
from __future__ import annotations

from alembic import op

revision = "0021_discount_targets_softdel"
down_revision = "0020_discounts_manage_permission"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE discount_targets ADD COLUMN deleted_at TIMESTAMPTZ;")


def downgrade() -> None:
    op.execute("ALTER TABLE discount_targets DROP COLUMN deleted_at;")
