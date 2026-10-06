"""Financial model (cost price / actual sale price snapshot), post-confirmation
cancellation requests, independent refund lifecycle, and AI command-draft
storage for the AI admin assistant's confirmation workflow.

Revision ID: 0017_finance_cancel_refund_ai
Revises: 0016_cart_items_soft_delete
Create Date: 2026-09-29

Source: v2 rebuild brief §10-§25; docs/adr/ADR-017-post-confirmation-cancellation-refund.md;
docs/06_OPEN_DECISIONS.md OPEN-4/OPEN-6 (closed by ADR-017).

Design notes:
- `product_variants.cost_price` and `order_items.cost_price_snapshot` are both
  nullable: most existing variants have no recorded cost, and the brief
  explicitly forbids claiming profit when cost data doesn't exist. Gross
  profit queries must treat NULL cost as "unknown", not zero.
- `order_items.cost_price_snapshot` follows ADR-005's snapshot discipline: set
  once at order-creation time from the variant's cost_price at that moment,
  never recomputed from live data afterward.
- `cancellation_requests` allows at most one PENDING row per order (partial
  unique index) — a second request while one is open is rejected at the
  service layer using this index as the backstop.
- `refunds` is independent of `orders.status`/`cancellation_requests.status`
  by design (ADR-017): approving a cancellation never auto-creates a refund.
- `ai_command_drafts.payload` is the exact structured command shown to the
  admin in the preview. Confirmation re-reads and re-validates *this* stored
  payload — it never accepts new values at confirm time — which is what
  makes a confirmation token non-reusable for a different command (brief §24).
"""
from alembic import op

revision = "0017_finance_cancel_refund_ai"
down_revision = "0016_cart_items_soft_delete"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE product_variants
            ADD COLUMN cost_price BIGINT CHECK (cost_price >= 0);

        ALTER TABLE order_items
            ADD COLUMN cost_price_snapshot BIGINT CHECK (cost_price_snapshot >= 0);
        """
    )

    op.execute(
        """
        CREATE TABLE cancellation_requests (
            id              BIGSERIAL PRIMARY KEY,
            order_id        BIGINT NOT NULL REFERENCES orders(id),
            requested_by    BIGINT NOT NULL REFERENCES users(id),
            reason          TEXT NOT NULL CHECK (length(trim(reason)) >= 10),
            status          TEXT NOT NULL DEFAULT 'PENDING'
                                CHECK (status IN ('PENDING', 'APPROVED', 'DENIED')),
            decided_by      BIGINT REFERENCES users(id),
            decision_note   TEXT,
            decided_at      TIMESTAMPTZ,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX ON cancellation_requests (order_id);
        CREATE UNIQUE INDEX idx_cancellation_requests_one_pending
            ON cancellation_requests (order_id) WHERE status = 'PENDING';
        """
    )

    op.execute(
        """
        CREATE TABLE refunds (
            id                  BIGSERIAL PRIMARY KEY,
            order_id            BIGINT NOT NULL REFERENCES orders(id),
            payment_id          BIGINT REFERENCES payments(id),
            amount              BIGINT NOT NULL CHECK (amount > 0),
            method              TEXT NOT NULL CHECK (method IN ('CASH', 'CARD')),
            status              TEXT NOT NULL DEFAULT 'PENDING'
                                    CHECK (status IN ('PENDING', 'COMPLETED', 'FAILED')),
            reason              TEXT NOT NULL CHECK (length(trim(reason)) >= 10),
            provider_reference  TEXT,
            created_by          BIGINT NOT NULL REFERENCES users(id),
            completed_by        BIGINT REFERENCES users(id),
            completed_at        TIMESTAMPTZ,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX ON refunds (order_id);
        """
    )

    op.execute(
        """
        CREATE TABLE ai_command_drafts (
            id                  BIGSERIAL PRIMARY KEY,
            admin_id            BIGINT NOT NULL REFERENCES users(id),
            command_type        TEXT NOT NULL,
            payload             JSONB NOT NULL,
            status              TEXT NOT NULL DEFAULT 'PENDING'
                                    CHECK (status IN ('PENDING', 'CONFIRMED', 'CANCELLED', 'EXPIRED', 'FAILED')),
            source              TEXT NOT NULL CHECK (source IN ('TEXT', 'VOICE', 'IMAGE', 'IMAGE_VOICE')),
            confirmation_token  TEXT NOT NULL,
            expires_at          TIMESTAMPTZ NOT NULL,
            confirmed_at        TIMESTAMPTZ,
            result_entity_type  TEXT,
            result_entity_id    BIGINT,
            error               TEXT,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE UNIQUE INDEX ON ai_command_drafts (confirmation_token);
        CREATE INDEX ON ai_command_drafts (admin_id, status);
        """
    )

    op.execute(
        """
        INSERT INTO permissions (key, description) VALUES
            ('cancellation_requests.create', 'Request cancellation of a paid/confirmed order'),
            ('cancellation_requests.review', 'Approve/deny a cancellation request'),
            ('refunds.manage',               'Record and view refunds'),
            ('ai.assistant.use',              'Use the AI administrative assistant');
        """
    )

    op.execute(
        """
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id FROM roles r, permissions p
        WHERE r.name = 'OWNER' AND p.key IN (
            'cancellation_requests.create', 'cancellation_requests.review',
            'refunds.manage', 'ai.assistant.use'
        );

        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id FROM roles r, permissions p
        WHERE r.name = 'ADMIN' AND p.key IN (
            'cancellation_requests.review', 'refunds.manage', 'ai.assistant.use'
        );

        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id FROM roles r, permissions p
        WHERE r.name = 'USER' AND p.key IN (
            'cancellation_requests.create'
        );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM role_permissions WHERE permission_id IN (
            SELECT id FROM permissions WHERE key IN (
                'cancellation_requests.create', 'cancellation_requests.review',
                'refunds.manage', 'ai.assistant.use'
            )
        );
        DELETE FROM permissions WHERE key IN (
            'cancellation_requests.create', 'cancellation_requests.review',
            'refunds.manage', 'ai.assistant.use'
        );
        """
    )
    op.execute("DROP TABLE IF EXISTS ai_command_drafts;")
    op.execute("DROP TABLE IF EXISTS refunds;")
    op.execute("DROP TABLE IF EXISTS cancellation_requests;")
    op.execute("ALTER TABLE order_items DROP COLUMN IF EXISTS cost_price_snapshot;")
    op.execute("ALTER TABLE product_variants DROP COLUMN IF EXISTS cost_price;")
