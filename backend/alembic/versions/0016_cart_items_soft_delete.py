"""COMMERCE domain: soft-delete support on cart_items.

Revision ID: 0016_cart_items_soft_delete
Revises: 0015_store_settings
Create Date: 2026-08-18

Source: docs/00_MASTER_TZ.md §5.4/§21 ("soft delete is used everywhere"),
§12.2 (comfort_app has zero DELETE privilege on any table, blanket, no
per-table exceptions).

PROVEN NECESSARY, NOT ASSUMED (Phase 08): `app/domains/commerce/cart/
repository.py`'s `delete_item` (wired to `DELETE /cart/items/{id}`,
production-reachable) and `clear_cart` (currently unused, same bug) both
issued a genuine `DELETE FROM cart_items`. Identical failure mode to the
Phase 06 `product_compatibilities` bug: fails in production with
`InsufficientPrivilegeError: permission denied for table cart_items`
against the real `comfort_app` role. `cart_items` was the one business
table in the schema without a `deleted_at` column even though every
comparable table (`products`, `product_variants`, `product_images`,
`brands`, `colors`, `product_compatibilities`) already has one — this
migration brings it in line with the schema's own dominant, already-
established pattern rather than inventing a new mechanism (e.g. reusing
`quantity = 0` as a removal marker, which would overload that column's
meaning and still require loosening its `CHECK (quantity > 0)`).

Design notes:
- Purely additive: one nullable column. No existing row's meaning changes.
- The existing `UNIQUE(cart_id, variant_id)` index (migration 0007_commerce)
  is replaced with a partial one, `WHERE deleted_at IS NULL` — same shape
  as every other soft-deleted table's uniqueness constraint in this schema
  (e.g. `product_variants(sku) WHERE deleted_at IS NULL`). This is required,
  not cosmetic: without it, a user could never re-add a variant to their
  cart after removing it once (the old row would still occupy the unique
  slot forever). `cart/repository.py::upsert_item`'s `ON CONFLICT` target
  is updated to match this predicate exactly — Postgres requires an
  ON CONFLICT inference target to match a partial unique index's predicate
  precisely, not just its columns.
"""
from alembic import op

revision = "0016_cart_items_soft_delete"
down_revision = "0015_store_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE cart_items ADD COLUMN deleted_at TIMESTAMPTZ;")
    op.execute("DROP INDEX IF EXISTS cart_items_cart_id_variant_id_idx;")
    op.execute(
        """
        CREATE UNIQUE INDEX idx_cart_items_active_variant
            ON cart_items (cart_id, variant_id)
            WHERE deleted_at IS NULL;
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_cart_items_active_variant;")
    op.execute("CREATE UNIQUE INDEX ON cart_items (cart_id, variant_id);")
    op.execute("ALTER TABLE cart_items DROP COLUMN IF EXISTS deleted_at;")
