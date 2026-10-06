"""COMMERCE domain: carts, cart_items, orders, order_items, stock_reservations.

Revision ID: 0007_commerce
Revises: 0006_search
Create Date: 2026-08-17

Source: docs/00_MASTER_TZ.md ADR-5 (order snapshot), ADR-6 (stock
reservation), §8.1 (lifecycle), §8.4 (cancellation reason), §18.2 (indexes).

Design notes:
- `orders.status` CHECK list is exactly REQ-COM-003's P0 transition set:
  CREATED/AWAITING_PAYMENT/PAYMENT_SUBMITTED/UNDER_REVIEW/CONFIRMED/
  REJECTED/CANCELLED/EXPIRED. REFUND_PENDING/REFUNDED are deliberately
  excluded — they're P3 (OPEN-4, resolved: not scheduled until P3 lands).
  Full transition-graph validation (which status can move to which) is
  NOT a DB constraint — TZ explicitly places that "kodda aniq jadval"
  (an explicit table in code, §8.1), not in the schema; a CHECK can only
  validate a single row's current value, not a transition, so enforcing
  the full graph here would require a stateful trigger the TZ doesn't ask
  for. Same reasoning applies to payments.status in migration 0009 (an
  APPROVED payment never reverting to PENDING, REQ-BIZ-008) — enforced by
  the Service layer's guarded UPDATE, not a DB trigger.
- `cancellation_reason` DOES get a DB-level CHECK (min 10 chars, mandatory
  whenever status='CANCELLED') because it's a simple, TZ-explicit,
  single-row invariant (§8.4), not a multi-step workflow.
- `orders.remaining_amount = total_amount - paid_amount` is enforced as a
  CHECK — ADR-5 defines it as a direct formula, appropriate for DB
  enforcement.
- `carts` has one row per user (UNIQUE(user_id)) — TZ's domain model names
  the table but never describes a multi-cart-per-user scenario; §13.4's
  `GET /cart` (singular, no cart_id param) is the strongest signal this is
  a one-cart-per-user design. Documented as an inferred, not literal,
  requirement.
- `order_items.variant_id` keeps its FK for traceability/join queries
  ("all orders containing this variant") even though ADR-5's snapshot
  fields (not this FK) are what must be trusted for historical accuracy.
"""
from alembic import op

revision = "0007_commerce"
down_revision = "0006_search"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE carts (
            id         BIGSERIAL PRIMARY KEY,
            user_id    BIGINT NOT NULL REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE UNIQUE INDEX ON carts (user_id);
        """
    )

    op.execute(
        """
        CREATE TABLE cart_items (
            id         BIGSERIAL PRIMARY KEY,
            cart_id    BIGINT NOT NULL REFERENCES carts(id),
            variant_id BIGINT NOT NULL REFERENCES product_variants(id),
            quantity   INTEGER NOT NULL CHECK (quantity > 0),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE UNIQUE INDEX ON cart_items (cart_id, variant_id);
        """
    )

    op.execute(
        """
        CREATE TABLE orders (
            id                       BIGSERIAL PRIMARY KEY,
            order_number             TEXT NOT NULL,
            user_id                  BIGINT NOT NULL REFERENCES users(id),
            status                   TEXT NOT NULL DEFAULT 'CREATED'
                CHECK (status IN (
                    'CREATED', 'AWAITING_PAYMENT', 'PAYMENT_SUBMITTED',
                    'UNDER_REVIEW', 'CONFIRMED', 'REJECTED', 'CANCELLED', 'EXPIRED'
                )),
            total_amount             BIGINT NOT NULL DEFAULT 0 CHECK (total_amount >= 0),
            required_initial_amount  BIGINT NOT NULL DEFAULT 0 CHECK (required_initial_amount >= 0),
            paid_amount              BIGINT NOT NULL DEFAULT 0 CHECK (paid_amount >= 0),
            remaining_amount         BIGINT NOT NULL DEFAULT 0,
            cancellation_reason      TEXT,
            confirmed_at             TIMESTAMPTZ,
            confirmed_by             BIGINT REFERENCES users(id),
            cancelled_at             TIMESTAMPTZ,
            cancelled_by             BIGINT REFERENCES users(id),
            created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
            CHECK (remaining_amount = total_amount - paid_amount),
            CHECK (
                status <> 'CANCELLED'
                OR (cancellation_reason IS NOT NULL AND length(cancellation_reason) >= 10)
            )
        );
        CREATE UNIQUE INDEX ON orders (order_number);
        CREATE INDEX ON orders (user_id, created_at DESC);
        CREATE INDEX ON orders (status, created_at DESC);
        """
    )

    op.execute(
        """
        CREATE TABLE order_items (
            id                        BIGSERIAL PRIMARY KEY,
            order_id                  BIGINT NOT NULL REFERENCES orders(id),
            variant_id                BIGINT NOT NULL REFERENCES product_variants(id),
            product_name_snapshot     TEXT NOT NULL,
            variant_label_snapshot    TEXT,
            sku_snapshot              TEXT NOT NULL,
            unit_price                BIGINT NOT NULL CHECK (unit_price >= 0),
            discount_amount           BIGINT NOT NULL DEFAULT 0 CHECK (discount_amount >= 0),
            quantity                  INTEGER NOT NULL CHECK (quantity > 0),
            required_initial_payment  BIGINT NOT NULL DEFAULT 0 CHECK (required_initial_payment >= 0),
            line_total                BIGINT NOT NULL CHECK (line_total >= 0),
            created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
            CHECK (discount_amount <= unit_price * quantity)
        );
        CREATE INDEX ON order_items (order_id);
        """
    )

    op.execute(
        """
        CREATE TABLE stock_reservations (
            id          BIGSERIAL PRIMARY KEY,
            order_id    BIGINT NOT NULL REFERENCES orders(id),
            variant_id  BIGINT NOT NULL REFERENCES product_variants(id),
            quantity    INTEGER NOT NULL CHECK (quantity > 0),
            expires_at  TIMESTAMPTZ NOT NULL,
            released_at TIMESTAMPTZ,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX ON stock_reservations (expires_at) WHERE released_at IS NULL;
        CREATE INDEX ON stock_reservations (variant_id) WHERE released_at IS NULL;
        CREATE INDEX ON stock_reservations (order_id);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS stock_reservations;")
    op.execute("DROP TABLE IF EXISTS order_items;")
    op.execute("DROP TABLE IF EXISTS orders;")
    op.execute("DROP TABLE IF EXISTS cart_items;")
    op.execute("DROP TABLE IF EXISTS carts;")
