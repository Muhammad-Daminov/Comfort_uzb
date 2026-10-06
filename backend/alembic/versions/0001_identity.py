"""IDENTITY domain: roles, permissions, role_permissions, users.

Revision ID: 0001_identity
Revises:
Create Date: 2026-08-17

Source: docs/00_MASTER_TZ.md §3 (roles & permissions), §5.3 (phone),
§5.5 (telegram_id/BIGSERIAL), ADR-11 (OWNER bootstrap — the single-OWNER
partial unique index is created here; the actual OWNER row is seeded by
migration 0002_owner_bootstrap, kept separate so schema and data changes
are never mixed in one migration).

Design notes (implementation necessities beyond the literal TZ text,
called out per Phase-02-Database.md's traceability requirement):
- `users.role` is a TEXT column with a FOREIGN KEY to `roles.name`, not a
  `role_id` FK to `roles.id`. This preserves ADR-11's literal example SQL
  (`INSERT INTO users (telegram_id, role, status) VALUES (...)`, which
  treats `role` as directly settable text) while still satisfying §3's
  requirement that roles be data-driven, not hardcoded — the FK enforces
  that only a row in `roles` can be referenced, so adding SENIOR_ADMIN or
  OPERATOR later is a `roles` INSERT, not a schema change.
- `users.status` values (ACTIVE/DEACTIVATED) are not enumerated anywhere
  in the TZ prose; ACTIVE is confirmed by ADR-11's own seed SQL, and
  DEACTIVATED is inferred from the §12.6 test case "Deaktivlangan admin
  amal qiladi -> 403". Documented here since it's inferred, not stated.
- Permission keys are split more granularly than §3's table header
  (e.g. "products.create / update / archive" -> three separate keys) so
  each is independently grantable, consistent with §3's data-driven
  requirement.
- Status/role fields are TEXT + CHECK, never native Postgres ENUM types,
  per §5.6's explicit instruction ("text + CHECK... kodda va DB da bir
  xil ro'yxat") — adding a new status value later is a CHECK constraint
  change, not an ALTER TYPE.
"""
from alembic import op

revision = "0001_identity"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE roles (
            id          BIGSERIAL PRIMARY KEY,
            name        TEXT NOT NULL,
            description TEXT,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE UNIQUE INDEX ON roles (name);
        """
    )

    op.execute(
        """
        CREATE TABLE permissions (
            id          BIGSERIAL PRIMARY KEY,
            key         TEXT NOT NULL,
            description TEXT,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE UNIQUE INDEX ON permissions (key);
        """
    )

    op.execute(
        """
        CREATE TABLE role_permissions (
            role_id       BIGINT NOT NULL REFERENCES roles(id),
            permission_id BIGINT NOT NULL REFERENCES permissions(id),
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (role_id, permission_id)
        );
        """
    )

    op.execute(
        """
        CREATE TABLE users (
            id             BIGSERIAL PRIMARY KEY,
            telegram_id    BIGINT NOT NULL,
            role           TEXT NOT NULL REFERENCES roles(name) ON UPDATE CASCADE,
            status         TEXT NOT NULL DEFAULT 'ACTIVE'
                               CHECK (status IN ('ACTIVE', 'DEACTIVATED')),
            phone          TEXT,
            first_name     TEXT,
            last_name      TEXT,
            username       TEXT,
            bot_blocked_at TIMESTAMPTZ,
            deleted_at     TIMESTAMPTZ,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            CHECK (phone IS NULL OR phone ~ '^\\+998[0-9]{9}$')
        );

        -- §18.2: plain (non-partial) unique index — deliberately NOT
        -- filtered by deleted_at. Unlike a SKU, a telegram_id identifies
        -- a real person permanently; soft-deleting a user must not free
        -- their telegram_id up for reuse by a different row.
        CREATE UNIQUE INDEX ON users (telegram_id);

        CREATE INDEX ON users (role) WHERE deleted_at IS NULL;

        -- §5.3: unique phone among non-deleted users (partial, per §5.4's
        -- soft-delete + UNIQUE pattern).
        CREATE UNIQUE INDEX ON users (phone)
            WHERE phone IS NOT NULL AND deleted_at IS NULL;

        -- ADR-11: exactly one OWNER, ever. Schema-level guarantee;
        -- the actual OWNER row is seeded in migration 0002.
        CREATE UNIQUE INDEX idx_single_owner ON users ((role))
            WHERE role = 'OWNER' AND deleted_at IS NULL;
        """
    )

    # --- Seed data: role/permission catalog (§3's data-driven requirement) ---
    # This is reference/config data explicitly required by §3, not
    # speculative catalog content — see Phase-02-Database.md "Seed data".
    op.execute(
        """
        INSERT INTO roles (name, description) VALUES
            ('OWNER', 'Do''kon egasi — aniq 1 ta (ADR-11)'),
            ('ADMIN', 'Sotuvchi / ishchi'),
            ('USER', 'Xaridor');
        """
    )

    op.execute(
        """
        INSERT INTO permissions (key, description) VALUES
            ('catalog.view',        'View product catalog'),
            ('products.create',     'Create products/variants'),
            ('products.update',     'Update products/variants'),
            ('products.archive',    'Archive products/variants'),
            ('inventory.manage',    'Adjust stock, view inventory movements'),
            ('orders.view.all',     'View all orders'),
            ('orders.view.own',     'View own orders'),
            ('orders.confirm',      'Confirm an order'),
            ('orders.cancel',       'Cancel an order'),
            ('payments.review',     'Approve/reject a payment'),
            ('receipts.view',       'View payment receipts (USER: own only, app-enforced)'),
            ('sell_requests.review','Review sell-requests'),
            ('chat.reply',          'Reply in user<->admin chat'),
            ('broadcast.send',      'Send a broadcast'),
            ('finance.view',        'View financial reports'),
            ('analytics.view',      'View analytics dashboards'),
            ('admins.manage',       'Create/deactivate admins'),
            ('audit.view',          'View audit log'),
            ('settings.manage',     'Manage store settings');
        """
    )

    # §3 permission matrix, restated exactly:
    op.execute(
        """
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id FROM roles r, permissions p
        WHERE r.name = 'OWNER';

        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id FROM roles r, permissions p
        WHERE r.name = 'ADMIN' AND p.key IN (
            'catalog.view', 'products.create', 'products.update', 'products.archive',
            'inventory.manage', 'orders.view.all', 'orders.view.own',
            'orders.confirm', 'orders.cancel', 'payments.review', 'receipts.view',
            'sell_requests.review', 'chat.reply', 'broadcast.send'
        );

        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id FROM roles r, permissions p
        WHERE r.name = 'USER' AND p.key IN (
            'catalog.view', 'orders.view.own', 'receipts.view'
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS role_permissions;")
    op.execute("DROP TABLE IF EXISTS users;")
    op.execute("DROP TABLE IF EXISTS permissions;")
    op.execute("DROP TABLE IF EXISTS roles;")
