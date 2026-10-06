"""User-level Telegram notification preference — v2 rebuild P3B-2.

Revision ID: 0022_notification_prefs
Revises: 0021_discount_targets_softdel
Create Date: 2026-09-30

Source: "COMFORT UZB — P3B" brief. §10/ADR-12's dual-channel design
(Telegram message + `notifications` row visible in the Mini App) is
unchanged — this only adds a per-user opt-out of the Telegram half. No new
notification "types"/categories are invented: `notifications.type` still
has no live producer (ADR-016 "Consequences" — Phase 04 shipped the
consumer only; a real producer is P1/backend-engagement scope, out of
bounds here per CLAUDE.md phase discipline). A single boolean is the
honest minimal preference the *existing* delivery mechanism
(`bot/notifications/poller.py`) can actually enforce today, uniformly,
regardless of what `type` a future notification carries.

`NOT NULL DEFAULT true` — Telegram delivery is opt-out, not opt-in,
matching current (undocumented-preference) behavior for every existing
user: nothing changes for anyone until they explicitly turn it off.
"""
from __future__ import annotations

from alembic import op

revision = "0022_notification_prefs"
down_revision = "0021_discount_targets_softdel"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE users ADD COLUMN telegram_notifications_enabled BOOLEAN NOT NULL DEFAULT true;"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN telegram_notifications_enabled;")
