"""ADR-11: seed the single OWNER row from the OWNER_TELEGRAM_ID env var.

Revision ID: 0002_owner_bootstrap
Revises: 0001_identity
Create Date: 2026-08-17

Source: docs/00_MASTER_TZ.md ADR-11. Kept as its own migration (separate
from 0001_identity's schema) so schema changes and data changes are never
mixed, and so this step is easy to skip/rerun independently if a
deployment ever needs to reseed against a fresh DB (the INSERT itself is
already idempotent via ON CONFLICT DO NOTHING, matching ADR-11's own SQL).

No UI path may create an OWNER (REQ-IDT-001) — this migration, run once
per environment from `OWNER_TELEGRAM_ID`, is the only sanctioned path.
"""
import os

from alembic import op
from sqlalchemy import text

revision = "0002_owner_bootstrap"
down_revision = "0001_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    owner_telegram_id = os.environ.get("OWNER_TELEGRAM_ID")
    if not owner_telegram_id:
        raise RuntimeError(
            "OWNER_TELEGRAM_ID is not set. Refusing to skip OWNER bootstrap "
            "silently — ADR-11 requires exactly one OWNER, seeded from this "
            "env var. Set it and rerun `alembic upgrade head`."
        )

    bind = op.get_bind()
    bind.execute(
        text(
            """
            INSERT INTO users (telegram_id, role, status)
            VALUES (:owner_telegram_id, 'OWNER', 'ACTIVE')
            ON CONFLICT (telegram_id) DO NOTHING;
            """
        ),
        {"owner_telegram_id": int(owner_telegram_id)},
    )


def downgrade() -> None:
    # Only removes the row this migration would have inserted; does not
    # touch any OWNER created by later, unrelated activity.
    owner_telegram_id = os.environ.get("OWNER_TELEGRAM_ID")
    if not owner_telegram_id:
        return
    bind = op.get_bind()
    bind.execute(
        text("DELETE FROM users WHERE telegram_id = :t AND role = 'OWNER';"),
        {"t": int(owner_telegram_id)},
    )
