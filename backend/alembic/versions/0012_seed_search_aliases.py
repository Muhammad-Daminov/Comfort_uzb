"""Seed search_aliases with the examples the Master TZ itself names.

Revision ID: 0012_seed_search_aliases
Revises: 0011_security
Create Date: 2026-08-17

Source: docs/00_MASTER_TZ.md ADR-8's own worked example: "Odam yozadi:
Nexia, Neksiya, Нексия, nexiya, Lasetti, Ласетти." This is reference/config
data explicitly evidenced by the TZ text, not invented production catalog
content (Phase-02-Database.md: "do not invent production catalog data" —
this is a small alias-normalization seed, not a catalog of real products).
Deterministic and idempotent (ON CONFLICT DO NOTHING against the
(alias, entity_type) unique index from migration 0006).

Entity rows referenced by `canonical` (e.g. an actual `nexia` car_model
row) are NOT created here — seeding real vehicle compatibility data is
catalog content, out of Phase 02's scope; `search_aliases` only maps a
spelling to a canonical string the search-normalization function
(backend-core, ADR-8) resolves against whatever `car_models`/`brands`
rows exist.
"""
from alembic import op

revision = "0012_seed_search_aliases"
down_revision = "0011_security"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO search_aliases (alias, canonical, entity_type) VALUES
            ('neksiya', 'nexia', 'car_model'),
            ('нексия', 'nexia', 'car_model'),
            ('ласетти', 'lasetti', 'car_model')
        ON CONFLICT (alias, entity_type) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM search_aliases
        WHERE (alias, entity_type) IN (
            ('neksiya', 'car_model'),
            ('нексия', 'car_model'),
            ('ласетти', 'car_model')
        );
        """
    )
