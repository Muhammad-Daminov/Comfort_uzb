"""Short-lived IMAGE+VOICE/TEXT correlation for the AI admin assistant.

Revision ID: 0018_ai_pending_media
Revises: 0017_finance_cancel_refund_ai
Create Date: 2026-09-29

Source: v2 rebuild brief Priority 3 ("IMAGE + VOICE correlation").

Design notes:
- One row per (admin_id, chat_id) with status='PENDING' at a time (partial
  unique index) — a second photo from the same admin/chat replaces the
  first rather than stacking (bot/handlers/ai.py expires the old one
  first, in its own transaction, before inserting the new one).
- `consume()` (app/ai/pending_media.py) claims a row with a single guarded
  `UPDATE ... WHERE status='PENDING' AND expires_at > now() RETURNING *` —
  the same atomic-claim pattern as ai_command_drafts' confirm path, so two
  concurrent messages can never both correlate against the same photo.
- No file bytes are stored here, only the Telegram file_id — the actual
  download still happens exactly once, at AI-draft confirm time
  (app/ai/executor.py::_attach_telegram_image), never here.
"""
from alembic import op

revision = "0018_ai_pending_media"
down_revision = "0017_finance_cancel_refund_ai"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE ai_pending_media (
            id                    BIGSERIAL PRIMARY KEY,
            admin_id              BIGINT NOT NULL REFERENCES users(id),
            chat_id               BIGINT NOT NULL,
            telegram_file_id      TEXT NOT NULL,
            media_type            TEXT NOT NULL CHECK (media_type IN ('PHOTO')),
            status                TEXT NOT NULL DEFAULT 'PENDING'
                                      CHECK (status IN ('PENDING', 'CONSUMED', 'EXPIRED')),
            expires_at            TIMESTAMPTZ NOT NULL,
            created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX ON ai_pending_media (admin_id, chat_id, status);
        CREATE UNIQUE INDEX idx_ai_pending_media_one_pending
            ON ai_pending_media (admin_id, chat_id) WHERE status = 'PENDING';
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ai_pending_media;")
