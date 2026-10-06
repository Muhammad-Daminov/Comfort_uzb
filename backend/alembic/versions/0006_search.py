"""SEARCH domain: pg_trgm extension, products.search_text index, search_aliases.

Revision ID: 0006_search
Revises: 0005_pricing
Create Date: 2026-08-17

Source: docs/00_MASTER_TZ.md ADR-8 (Cyrillic/Latin normalization). The
actual normalization function (Cyrillic->Latin transliteration, apostrophe
variants) is application code, not a DB object — TZ describes it as logic
applied "yozishda va qidirishda" (at write and query time), which is
naturally a shared Python function `backend-core` owns, not a Postgres
function; keeping it in application code also makes it trivially unit
testable without a DB connection (REQ-TST-002).
"""
from alembic import op

revision = "0006_search"
down_revision = "0005_pricing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")

    op.execute(
        """
        CREATE INDEX idx_products_search_trgm
            ON products USING gin (search_text gin_trgm_ops);
        """
    )

    op.execute(
        """
        CREATE TABLE search_aliases (
            id          BIGSERIAL PRIMARY KEY,
            alias       TEXT NOT NULL,
            canonical   TEXT NOT NULL,
            entity_type TEXT NOT NULL CHECK (entity_type IN ('car_model', 'brand')),
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE UNIQUE INDEX ON search_aliases (alias, entity_type);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS search_aliases;")
    op.execute("DROP INDEX IF EXISTS idx_products_search_trgm;")
    # pg_trgm extension intentionally left installed on downgrade — other
    # objects/extensions in a shared cluster may depend on it (§16.4).
