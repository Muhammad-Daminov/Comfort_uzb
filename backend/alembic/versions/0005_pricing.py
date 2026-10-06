"""PRICING domain: discounts, discount_targets.

Revision ID: 0005_pricing
Revises: 0004_vehicle
Create Date: 2026-08-17

Source: docs/00_MASTER_TZ.md §7.1, §7.2.

Design notes:
- `discount_targets.target_id` is a polymorphic reference (target_type
  decides whether it points at product_variants, products, brands, or
  car_models) — Postgres has no native polymorphic FK, so this is a plain
  BIGINT with no FK constraint, and the CHECK below only guards the
  ALL-has-no-target-id / non-ALL-has-a-target-id invariant. Resolving the
  reference to the right table is application-layer logic (backend-core,
  per AGENTS/backend-core.md), same as any polymorphic-association design.
- `discounts.value` is BIGINT regardless of `kind`: for kind='FIXED' it's
  so'm (ADR-3); for kind='PERCENT' it's a whole-number percentage. The
  `value <= 100` CHECK only applies when kind='PERCENT' — a pure
  data-integrity guard (a 150% discount is never valid), not a workflow.
"""
from alembic import op

revision = "0005_pricing"
down_revision = "0004_vehicle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE discounts (
            id         BIGSERIAL PRIMARY KEY,
            name       TEXT NOT NULL,
            kind       TEXT NOT NULL CHECK (kind IN ('PERCENT', 'FIXED')),
            value      BIGINT NOT NULL CHECK (value >= 0),
            starts_at  TIMESTAMPTZ,
            ends_at    TIMESTAMPTZ,
            is_active  BOOLEAN NOT NULL DEFAULT true,
            priority   SMALLINT NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CHECK (ends_at IS NULL OR starts_at IS NULL OR ends_at >= starts_at),
            CHECK (kind <> 'PERCENT' OR value <= 100)
        );
        CREATE INDEX ON discounts (is_active, starts_at, ends_at);
        """
    )

    op.execute(
        """
        CREATE TABLE discount_targets (
            id          BIGSERIAL PRIMARY KEY,
            discount_id BIGINT NOT NULL REFERENCES discounts(id),
            target_type TEXT NOT NULL
                            CHECK (target_type IN ('VARIANT', 'PRODUCT', 'BRAND', 'CAR_MODEL', 'ALL')),
            target_id   BIGINT,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            CHECK (
                (target_type = 'ALL' AND target_id IS NULL)
                OR (target_type <> 'ALL' AND target_id IS NOT NULL)
            )
        );
        CREATE INDEX ON discount_targets (target_type, target_id);
        CREATE INDEX ON discount_targets (discount_id);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS discount_targets;")
    op.execute("DROP TABLE IF EXISTS discounts;")
