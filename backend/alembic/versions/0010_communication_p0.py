"""COMMUNICATION domain, P0 slice only: notifications.

Revision ID: 0010_communication_p0
Revises: 0009_payments
Create Date: 2026-08-17

Source: docs/00_MASTER_TZ.md §10, ADR-12, §18.2 (index). Only `notifications`
ships in P0 (docs/04_DOMAIN_ARCHITECTURE.md "Domain -> phase mapping");
`conversations`, `messages`, `broadcasts`, `broadcast_targets` are P1 and
are NOT created here — see docs/tasks/Phase-10-Optimization.md, which is
where backend-engagement's P1 rollout adds them via a later migration.

Design notes:
- Columns beyond `user_id`/`read_at`/`created_at` (which come directly
  from §18.2's index) are not given an exact schema anywhere in the TZ —
  `type`, `title`, `body`, `entity_type`, `entity_id` are implementation
  necessities for a notification row to actually carry content and let
  the Mini App link back to the relevant order/payment/etc. Documented
  here since they're inferred, not literal TZ text.
"""
from alembic import op

revision = "0010_communication_p0"
down_revision = "0009_payments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE notifications (
            id          BIGSERIAL PRIMARY KEY,
            user_id     BIGINT NOT NULL REFERENCES users(id),
            type        TEXT NOT NULL,
            title       TEXT NOT NULL,
            body        TEXT,
            entity_type TEXT,
            entity_id   BIGINT,
            read_at     TIMESTAMPTZ,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX ON notifications (user_id, read_at, created_at DESC);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS notifications;")
