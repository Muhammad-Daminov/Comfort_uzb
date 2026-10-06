"""Owner-only `discounts.manage` permission — v2 rebuild P2-4.

Revision ID: 0020_discounts_manage_permission
Revises: 0019_product_type_material
Create Date: 2026-09-30

Migration 0001_identity's OWNER row already got every permission that
existed *at that time* via a one-off cross-join (`SELECT r.id, p.id FROM
roles r, permissions p WHERE r.name = 'OWNER'`) — that join ran once and
does not retroactively pick up permissions added later. A discount-CRUD
permission introduced now must therefore be granted to OWNER explicitly
here, same as this project has done for every permission added after
0001 (see 0017_finance_cancel_refund_ai for the same pattern). ADMIN is
deliberately not granted this key — CLAUDE.md P2 brief: discount
management is OWNER-only, ADMIN must not see or edit it.
"""
from __future__ import annotations

from alembic import op

revision = "0020_discounts_manage_permission"
down_revision = "0019_product_type_material"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO permissions (key, description) VALUES
            ('discounts.manage', 'Create/edit/activate/deactivate discounts (owner only)');
        """
    )
    op.execute(
        """
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id FROM roles r, permissions p
        WHERE r.name = 'OWNER' AND p.key = 'discounts.manage';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM role_permissions WHERE permission_id = (SELECT id FROM permissions WHERE key = 'discounts.manage');
        DELETE FROM permissions WHERE key = 'discounts.manage';
        """
    )
