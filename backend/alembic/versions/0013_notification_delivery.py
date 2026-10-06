"""COMMUNICATION domain: track Telegram-channel delivery on `notifications`.

Revision ID: 0013_notification_delivery
Revises: 0012_seed_search_aliases
Create Date: 2026-08-18

Source: docs/00_MASTER_TZ.md §10 (dual-channel notification design), ADR-12,
resolves OPEN-6 (docs/06_OPEN_DECISIONS.md) via ADR-016.

Design notes:
- `notifications.read_at` (migration 0010_communication_p0) tracks whether
  the user has read the notification *in the Mini App* — a different fact
  from whether the Telegram half of the dual-channel design (§10) has been
  sent yet. Without a separate column, `bot`'s poll loop (ADR-016) would
  have no durable, crash-safe way to know what it has already sent, and
  would either re-send on every restart or need an unsafe in-memory-only
  watermark. `telegram_sent_at` is that column: NULL means "not yet sent
  via Telegram," matching every pre-existing row's actual state exactly
  (nothing has been sent by anything yet), so no backfill/data migration
  is needed.
- Partial index on `telegram_sent_at IS NULL` mirrors the existing
  `stock_reservations (expires_at) WHERE released_at IS NULL` pattern
  (migration 0007_commerce) — same shape of problem (find the small
  not-yet-handled subset of a table that is mostly already handled).
- Purely additive: one nullable column, one partial index. No existing
  reader of `notifications` is affected.
"""
from alembic import op

revision = "0013_notification_delivery"
down_revision = "0012_seed_search_aliases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE notifications
            ADD COLUMN telegram_sent_at TIMESTAMPTZ;
        """
    )
    op.execute(
        """
        CREATE INDEX ON notifications (created_at)
            WHERE telegram_sent_at IS NULL;
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS notifications_created_at_idx;")
    op.execute("ALTER TABLE notifications DROP COLUMN IF EXISTS telegram_sent_at;")
