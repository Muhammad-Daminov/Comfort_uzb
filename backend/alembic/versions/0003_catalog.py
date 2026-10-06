"""CATALOG domain: brands, colors, products, product_variants, product_images.

Revision ID: 0003_catalog
Revises: 0002_owner_bootstrap
Create Date: 2026-08-17

Source: docs/00_MASTER_TZ.md §6.1-6.3, ADR-4 (variant owns price/stock),
REQ-CAT-005 (brands/colors as normalized lookup tables, added by the
Phase 0 review — required so PRICING's discount_targets(target_type=
'BRAND', target_id) in migration 0005 can reference a stable ID).

Design notes:
- `products.source_sell_request_id` (ADR-10) is deliberately NOT included
  here. It has no FK target in P0 — `sell_requests` is a MARKETPLACE/P1
  table not created until that domain ships — and a CONSIGNMENT product
  can't exist without the sell-request flow that populates it. Adding a
  dangling nullable column now would be dead weight; it's added via
  ALTER TABLE in the Marketplace domain's own migration when P1 ships.
  `products.source` itself IS included since §6.1 lists it as a base P0
  catalog field regardless of whether CONSIGNMENT is reachable yet.
- §6.3's "1-5 images per product" cap is NOT enforced as a DB constraint
  (a per-row CHECK can't express a per-group count limit; would need a
  trigger). Per Phase-02 scope rules ("do not encode complex business
  workflows into DB constraints unless the TZ explicitly requires it") —
  TZ states the rule but doesn't demand DB-level enforcement, so it's an
  application-layer check. The one-primary-image-per-product rule DOES
  get DB enforcement (a partial unique index), since that's a simple,
  TZ-explicit invariant (§6.3), not a workflow.
- `required_initial_payment <= price` and `stock_reserved <= stock_on_hand`
  are enforced as CHECK constraints: both are pure data-integrity
  invariants (like a non-negative check), not multi-step workflows.
- Stock quantities use INTEGER, not BIGINT — TZ doesn't specify a type for
  quantities (only for money, ADR-3), and INTEGER's ~2.1B range is not a
  realistic constraint for a single store's stock.
"""
from alembic import op

revision = "0003_catalog"
down_revision = "0002_owner_bootstrap"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE brands (
            id         BIGSERIAL PRIMARY KEY,
            name       TEXT NOT NULL,
            deleted_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE UNIQUE INDEX ON brands (name) WHERE deleted_at IS NULL;
        """
    )

    op.execute(
        """
        CREATE TABLE colors (
            id         BIGSERIAL PRIMARY KEY,
            name       TEXT NOT NULL,
            hex_code   TEXT,
            deleted_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CHECK (hex_code IS NULL OR hex_code ~ '^#[0-9A-Fa-f]{6}$')
        );
        CREATE UNIQUE INDEX ON colors (name) WHERE deleted_at IS NULL;
        """
    )

    op.execute(
        """
        CREATE TABLE products (
            id          BIGSERIAL PRIMARY KEY,
            name        TEXT NOT NULL,
            description TEXT,
            brand_id    BIGINT NOT NULL REFERENCES brands(id),
            status      TEXT NOT NULL DEFAULT 'DRAFT'
                            CHECK (status IN ('DRAFT', 'ACTIVE', 'ARCHIVED')),
            source      TEXT NOT NULL DEFAULT 'OWN'
                            CHECK (source IN ('OWN', 'CONSIGNMENT')),
            search_text TEXT,
            deleted_at  TIMESTAMPTZ,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX ON products (status) WHERE deleted_at IS NULL;
        CREATE INDEX ON products (brand_id);
        """
    )

    op.execute(
        """
        CREATE TABLE product_variants (
            id                        BIGSERIAL PRIMARY KEY,
            product_id                BIGINT NOT NULL REFERENCES products(id),
            sku                       TEXT NOT NULL,
            color_id                  BIGINT REFERENCES colors(id),
            price                     BIGINT NOT NULL CHECK (price >= 0),
            required_initial_payment  BIGINT NOT NULL DEFAULT 0
                                          CHECK (required_initial_payment >= 0),
            stock_on_hand             INTEGER NOT NULL DEFAULT 0
                                          CHECK (stock_on_hand >= 0),
            stock_reserved            INTEGER NOT NULL DEFAULT 0
                                          CHECK (stock_reserved >= 0),
            status                    TEXT NOT NULL DEFAULT 'ACTIVE'
                                          CHECK (status IN ('ACTIVE', 'ARCHIVED')),
            deleted_at                TIMESTAMPTZ,
            created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
            CHECK (stock_reserved <= stock_on_hand),
            CHECK (required_initial_payment <= price)
        );
        CREATE UNIQUE INDEX ON product_variants (sku) WHERE deleted_at IS NULL;
        CREATE INDEX ON product_variants (product_id, status);
        CREATE INDEX ON product_variants (price);
        """
    )

    op.execute(
        """
        CREATE TABLE product_images (
            id           BIGSERIAL PRIMARY KEY,
            product_id   BIGINT NOT NULL REFERENCES products(id),
            storage_path TEXT NOT NULL,
            sort_order   SMALLINT NOT NULL DEFAULT 0,
            is_primary   BOOLEAN NOT NULL DEFAULT false,
            width        INTEGER,
            height       INTEGER,
            bytes        INTEGER,
            deleted_at   TIMESTAMPTZ,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE UNIQUE INDEX ON product_images (product_id)
            WHERE is_primary AND deleted_at IS NULL;
        CREATE INDEX ON product_images (product_id, sort_order);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS product_images;")
    op.execute("DROP TABLE IF EXISTS product_variants;")
    op.execute("DROP TABLE IF EXISTS products;")
    op.execute("DROP TABLE IF EXISTS colors;")
    op.execute("DROP TABLE IF EXISTS brands;")
