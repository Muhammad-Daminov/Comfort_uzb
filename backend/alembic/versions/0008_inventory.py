"""INVENTORY domain: inventory_movements.

Revision ID: 0008_inventory
Revises: 0007_commerce
Create Date: 2026-08-17

Source: docs/00_MASTER_TZ.md §9.

Design notes:
- No append-only trigger here (unlike audit_logs in migration 0011). TZ's
  append-only trigger requirement (§12.3) is explicitly scoped to
  audit_logs only; inventory_movements is described as append-only in
  prose (§9) but without the same explicit DB-trigger mandate. Enforced
  instead by application discipline (the Service layer only INSERTs,
  never UPDATEs/DELETEs this table) — adding a trigger not asked for
  would be scope creep per Phase-02's "do not encode complex workflows
  unless explicitly required" rule. If this needs to become a hard DB
  guarantee later, that's an ADR-worthy escalation, not a silent add.
"""
from alembic import op

revision = "0008_inventory"
down_revision = "0007_commerce"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE inventory_movements (
            id                BIGSERIAL PRIMARY KEY,
            variant_id        BIGINT NOT NULL REFERENCES product_variants(id),
            movement_type     TEXT NOT NULL
                CHECK (movement_type IN ('IN', 'OUT', 'RESERVE', 'RELEASE', 'ADJUST')),
            quantity_change   INTEGER NOT NULL,
            quantity_before   INTEGER NOT NULL,
            quantity_after    INTEGER NOT NULL,
            reason            TEXT,
            reference_type    TEXT,
            reference_id      BIGINT,
            actor_id          BIGINT REFERENCES users(id),
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            CHECK (quantity_after = quantity_before + quantity_change)
        );
        CREATE INDEX ON inventory_movements (variant_id, created_at DESC);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS inventory_movements;")
