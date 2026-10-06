"""VEHICLE domain: car_brands, car_models, car_generations, product_compatibilities.

Revision ID: 0004_vehicle
Revises: 0003_catalog
Create Date: 2026-08-17

Source: docs/00_MASTER_TZ.md §6.4.

Design notes:
- `UNIQUE(car_brand_id, name)` on car_models and `UNIQUE(car_model_id, name)`
  on car_generations are implementation necessities (dedup guards), not
  literal TZ text, but low-risk pure data-integrity invariants.
- product_compatibilities intentionally has NO uniqueness constraint on
  (product_id, generation_id): §6.4's year_from/year_to/note fields exist
  specifically to let a product declare multiple compatibility rows for
  the same generation (e.g. "faqat sedan 2010-2012" and a separate row
  for "faqat universal 2013-2015"). A uniqueness constraint would block
  that legitimate case, so none is added — not an oversight.
"""
from alembic import op

revision = "0004_vehicle"
down_revision = "0003_catalog"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE car_brands (
            id         BIGSERIAL PRIMARY KEY,
            name       TEXT NOT NULL,
            deleted_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE UNIQUE INDEX ON car_brands (name) WHERE deleted_at IS NULL;
        """
    )

    op.execute(
        """
        CREATE TABLE car_models (
            id           BIGSERIAL PRIMARY KEY,
            car_brand_id BIGINT NOT NULL REFERENCES car_brands(id),
            name         TEXT NOT NULL,
            deleted_at   TIMESTAMPTZ,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE UNIQUE INDEX ON car_models (car_brand_id, name)
            WHERE deleted_at IS NULL;
        """
    )

    op.execute(
        """
        CREATE TABLE car_generations (
            id            BIGSERIAL PRIMARY KEY,
            car_model_id  BIGINT NOT NULL REFERENCES car_models(id),
            name          TEXT NOT NULL,
            year_from     SMALLINT,
            year_to       SMALLINT,
            deleted_at    TIMESTAMPTZ,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            CHECK (year_to IS NULL OR year_from IS NULL OR year_to >= year_from)
        );
        CREATE UNIQUE INDEX ON car_generations (car_model_id, name)
            WHERE deleted_at IS NULL;
        """
    )

    op.execute(
        """
        CREATE TABLE product_compatibilities (
            id            BIGSERIAL PRIMARY KEY,
            product_id    BIGINT NOT NULL REFERENCES products(id),
            generation_id BIGINT NOT NULL REFERENCES car_generations(id),
            year_from     SMALLINT,
            year_to       SMALLINT,
            note          TEXT,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            CHECK (year_to IS NULL OR year_from IS NULL OR year_to >= year_from)
        );
        CREATE INDEX ON product_compatibilities (generation_id);
        CREATE INDEX ON product_compatibilities (product_id);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS product_compatibilities;")
    op.execute("DROP TABLE IF EXISTS car_generations;")
    op.execute("DROP TABLE IF EXISTS car_models;")
    op.execute("DROP TABLE IF EXISTS car_brands;")
