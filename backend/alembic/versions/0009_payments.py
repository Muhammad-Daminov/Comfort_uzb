"""PAYMENTS domain: payments, payment_receipts.

Revision ID: 0009_payments
Revises: 0008_inventory
Create Date: 2026-08-17

Source: docs/00_MASTER_TZ.md §8.3, ADR-9 (receipt retention).

Design notes:
- `payments.status` one-way APPROVED->never-PENDING rule (REQ-BIZ-008) is
  application-enforced (Service layer guarded UPDATE), not a DB trigger —
  same reasoning as orders.status in migration 0007.
- `payment_receipts` columns are copied verbatim from ADR-9's own schema
  sketch; `hidden_at`/`reviewed_at` are compared at read time by the app
  to answer "hidden before or after review?" — no DB-level derived column
  needed, the raw timestamps are sufficient.
"""
from alembic import op

revision = "0009_payments"
down_revision = "0008_inventory"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE payments (
            id               BIGSERIAL PRIMARY KEY,
            order_id         BIGINT NOT NULL REFERENCES orders(id),
            amount           BIGINT NOT NULL CHECK (amount >= 0),
            method           TEXT NOT NULL DEFAULT 'CARD_TRANSFER'
                                 CHECK (method IN ('CARD_TRANSFER')),
            status           TEXT NOT NULL DEFAULT 'PENDING'
                                 CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED')),
            submitted_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            reviewed_at      TIMESTAMPTZ,
            reviewed_by      BIGINT REFERENCES users(id),
            rejection_reason TEXT,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX ON payments (order_id);
        CREATE INDEX ON payments (status, submitted_at DESC);
        """
    )

    op.execute(
        """
        CREATE TABLE payment_receipts (
            id                BIGSERIAL PRIMARY KEY,
            payment_id        BIGINT NOT NULL REFERENCES payments(id),
            storage_path      TEXT NOT NULL,
            visibility_status TEXT NOT NULL DEFAULT 'VISIBLE'
                CHECK (visibility_status IN ('VISIBLE', 'HIDDEN_BY_USER', 'HIDDEN_BY_ADMIN')),
            hidden_at         TIMESTAMPTZ,
            hidden_by         BIGINT REFERENCES users(id),
            retention_until   TIMESTAMPTZ NOT NULL,
            file_purged_at    TIMESTAMPTZ,
            reviewed_at       TIMESTAMPTZ,
            review_result     TEXT CHECK (review_result IN ('APPROVED', 'REJECTED')),
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX ON payment_receipts (retention_until) WHERE file_purged_at IS NULL;
        CREATE INDEX ON payment_receipts (payment_id);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS payment_receipts;")
    op.execute("DROP TABLE IF EXISTS payments;")
