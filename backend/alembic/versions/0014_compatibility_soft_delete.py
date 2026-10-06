"""VEHICLE domain: soft-delete support on product_compatibilities.

Revision ID: 0014_compatibility_soft_delete
Revises: 0013_notification_delivery
Create Date: 2026-08-18

Source: docs/00_MASTER_TZ.md §5.4/§21 ("soft delete is used everywhere"),
§12.2 (comfort_app has zero DELETE privilege on any table, blanket, no
per-table exceptions — `backend/db/provision_roles.sql`'s own comment:
"No DELETE (soft delete is used everywhere, §5.4/§21)").

PROVEN NECESSARY, NOT ASSUMED (Phase 06): migration 0004_vehicle's own
design notes explicitly chose no `deleted_at` on `product_compatibilities`,
reasoning it's "a pure association row, not a business entity" needing a
real DELETE. That reasoning didn't account for §12.2's blanket DELETE
revoke — live-reproduced while building Phase 06's admin compatibility-
removal endpoint: a genuine `DELETE FROM product_compatibilities` as
`comfort_app` fails with `InsufficientPrivilegeError: permission denied for
table product_compatibilities`. The existing schema genuinely cannot
support the required Phase 06 behavior (an admin removing a compatibility
link) without this column — this is the smallest fix that makes it work
within the existing, unchanged privilege architecture, rather than either
(a) granting a comfort_app-wide or per-table DELETE exception (undermines
the documented "no DELETE, ever" guarantee for a role compromise's blast
radius) or (b) leaving the endpoint broken.

Design notes:
- Purely additive: one nullable column, one partial index (mirrors every
  other soft-delete column in the schema, e.g. `products.deleted_at`).
  No existing row's meaning changes; NULL means "not removed," matching
  every pre-existing row's actual state.
- This does NOT retroactively fix `cart_items`' own DELETE calls
  (`app/domains/commerce/cart/repository.py`), which have the identical
  underlying problem (comfort_app cannot DELETE `cart_items` either,
  live-confirmed the same way). That is pre-existing Phase 03 code, out of
  this migration's and Phase 06's scope per this phase's explicit
  instructions ("do not modify unrelated Phase 02/03 code") — flagged
  instead in the Phase 06 report as a known, separately-fixable issue.
"""
from alembic import op

revision = "0014_compatibility_soft_delete"
down_revision = "0013_notification_delivery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE product_compatibilities
            ADD COLUMN deleted_at TIMESTAMPTZ;
        """
    )
    # Explicit name — migration 0004_vehicle already created a plain,
    # non-partial index on (product_id), which would otherwise collide
    # with Postgres's auto-generated name for this new partial one.
    op.execute(
        """
        CREATE INDEX idx_product_compatibilities_active
            ON product_compatibilities (product_id)
            WHERE deleted_at IS NULL;
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_product_compatibilities_active;")
    op.execute("ALTER TABLE product_compatibilities DROP COLUMN IF EXISTS deleted_at;")
