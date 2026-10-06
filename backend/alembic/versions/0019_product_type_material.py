"""Product type (SIDENA / SIDENA_COVER) and variant material — v2 rebuild P1-3.

Revision ID: 0019_product_type_material
Revises: 0018_ai_pending_media
Create Date: 2026-09-30

Source: "COMFORT UZB — P1 implementation" brief, §P1-3. Business scope is
currently exactly two product types (seat covers and seat-cover slipcovers)
— a CHECK-constrained enum matches that scope without inventing a generic
universal category system the business doesn't need yet; extending it
later (a third type) is a one-line CHECK change, not a redesign.

Material is deliberately free text, not a lookup table or enum: unlike
`product_type` (a fixed, small, business-defined set), material names
("Koja", "Eco-koja", ...) are a growing, admin-entered vocabulary — forcing
them through a `materials` table or CHECK list now would hardcode exactly
the kind of business constraint the brief says not to build.

Design notes:
- Both columns are NULLABLE and NOT backfilled for existing rows —
  "migration-safe, eski products buzilmasin": this is a schema-only
  change, no existing product/variant data is touched or guessed at.
  Admin/Owner sets these going forward via the edit UI.
- `product_type` lives on `products` (one type per product, matches
  `status`/`brand_id` which are also product-level); `material` lives on
  `product_variants` (same level as `color_id` — a variant already varies
  by color, and material is exactly the same kind of per-variant
  attribute, e.g. a leather vs eco-leather variant of the same product).
"""
from alembic import op

revision = "0019_product_type_material"
down_revision = "0018_ai_pending_media"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE products
            ADD COLUMN product_type TEXT CHECK (product_type IN ('SIDENA', 'SIDENA_COVER'));

        ALTER TABLE product_variants
            ADD COLUMN material TEXT;
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE product_variants DROP COLUMN IF EXISTS material;")
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS product_type;")
