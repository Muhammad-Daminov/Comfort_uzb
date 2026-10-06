"""OWNER ANALYTICS/REPORTING (ADR-015: raw asyncpg). Per AGENTS/backend-core.md:
"No new tables; this agent never writes to orders/payments/audit_logs in
service of these endpoints, only reads through the Service layer boundary."
Every query here is a SELECT except the admin-management writes (on the
existing `users` table) and settings writes (on `store_settings`, new this
phase) — both live in service.py, not here, to keep this module's SQL
surface auditable at a glance as "reporting only" plus the two documented
exceptions.

"Revenue" reads `orders.paid_amount` (ADR-5's already-authoritative running
total of approved payments per order, kept in sync by
`payments.service.review_payment` since Phase 03) rather than re-deriving
from `payments` — one source of truth, no recomputation drift.
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import datetime

import asyncpg

LOW_STOCK_THRESHOLD = 5  # operational display default, not a TZ business rule — see Phase-07 report


async def get_dashboard_summary(conn: asyncpg.Connection) -> dict:
    order_counts = await conn.fetch(
        "SELECT status, count(*) AS count FROM orders GROUP BY status"
    )
    revenue_row = await conn.fetchrow("SELECT COALESCE(SUM(paid_amount), 0) AS total_revenue FROM orders")
    product_counts = await conn.fetchrow(
        "SELECT count(*) AS total, count(*) FILTER (WHERE status = 'ACTIVE') AS active "
        "FROM products WHERE deleted_at IS NULL"
    )
    low_stock = await conn.fetch(
        """
        SELECT v.id AS variant_id, v.sku, p.name AS product_name,
               v.stock_on_hand - v.stock_reserved AS available
        FROM product_variants v
        JOIN products p ON p.id = v.product_id
        WHERE v.deleted_at IS NULL AND v.status = 'ACTIVE'
          AND v.stock_on_hand - v.stock_reserved <= $1
        ORDER BY available ASC
        LIMIT 20
        """,
        LOW_STOCK_THRESHOLD,
    )
    recent_orders = await conn.fetch(
        "SELECT id, order_number, status, total_amount, created_at FROM orders ORDER BY created_at DESC LIMIT 10"
    )
    recent_payments = await conn.fetch(
        "SELECT id, order_id, amount, status, submitted_at FROM payments ORDER BY submitted_at DESC LIMIT 10"
    )

    return {
        "order_counts_by_status": {row["status"]: row["count"] for row in order_counts},
        "total_revenue": revenue_row["total_revenue"],
        "product_count": product_counts["total"],
        "active_product_count": product_counts["active"],
        "low_stock_threshold": LOW_STOCK_THRESHOLD,
        "low_stock_variants": [dict(r) for r in low_stock],
        "recent_orders": [dict(r) for r in recent_orders],
        "recent_payments": [dict(r) for r in recent_payments],
    }


async def get_finance_summary(conn: asyncpg.Connection, *, date_from, date_to) -> dict:
    revenue_row = await conn.fetchrow(
        """
        SELECT COALESCE(SUM(o.paid_amount), 0) AS revenue, count(DISTINCT o.id) AS order_count
        FROM orders o
        WHERE o.created_at >= $1 AND o.created_at < $2
        """,
        date_from,
        date_to,
    )
    status_breakdown = await conn.fetch(
        """
        SELECT status, count(*) AS count, COALESCE(SUM(amount), 0) AS total_amount
        FROM payments
        WHERE submitted_at >= $1 AND submitted_at < $2
        GROUP BY status
        """,
        date_from,
        date_to,
    )
    # ADR-9: "hidden before review" warning — hidden_at < reviewed_at means
    # the user hid the receipt before an admin ever reviewed it. No
    # endpoint currently sets payment_receipts.hidden_at (no hide-receipt
    # feature has shipped yet, Phase 03/05/06 never built one) — this
    # comparison is forward-compatible logic, ready the moment one does,
    # not dead code covering an unreachable state today.
    payments = await conn.fetch(
        """
        SELECT p.id AS payment_id, p.order_id, p.amount, p.status, p.submitted_at, p.reviewed_at,
               pr.hidden_at, pr.reviewed_at AS receipt_reviewed_at,
               (pr.hidden_at IS NOT NULL AND pr.reviewed_at IS NOT NULL AND pr.hidden_at < pr.reviewed_at) AS hidden_before_review
        FROM payments p
        LEFT JOIN LATERAL (
            SELECT hidden_at, reviewed_at FROM payment_receipts
            WHERE payment_id = p.id ORDER BY created_at DESC LIMIT 1
        ) pr ON true
        WHERE p.submitted_at >= $1 AND p.submitted_at < $2
        ORDER BY p.submitted_at DESC
        LIMIT 100
        """,
        date_from,
        date_to,
    )

    # v2 brief §13: COGS/gross profit computed only from historical
    # order_items snapshots (unit_price/cost_price_snapshot), never from
    # live catalog data — and only over CONFIRMED orders, since those are
    # the only ones that represent an actual completed sale. Cost is NULL
    # for any variant that never had a cost_price recorded; those items are
    # surfaced as `items_missing_cost_price` rather than silently treated
    # as zero cost (which would overstate profit).
    cogs_row = await conn.fetchrow(
        """
        SELECT COALESCE(SUM(oi.line_total), 0) AS gross_sales,
               COALESCE(SUM(oi.cost_price_snapshot * oi.quantity) FILTER (WHERE oi.cost_price_snapshot IS NOT NULL), 0) AS cogs_known,
               COUNT(*) FILTER (WHERE oi.cost_price_snapshot IS NULL) AS items_missing_cost_price
        FROM order_items oi
        JOIN orders o ON o.id = oi.order_id
        WHERE o.status = 'CONFIRMED' AND o.created_at >= $1 AND o.created_at < $2
        """,
        date_from,
        date_to,
    )
    refunded_row = await conn.fetchrow(
        """
        SELECT COALESCE(SUM(r.amount), 0) AS refunded
        FROM refunds r
        JOIN orders o ON o.id = r.order_id
        WHERE r.status = 'COMPLETED' AND o.created_at >= $1 AND o.created_at < $2
        """,
        date_from,
        date_to,
    )
    items_missing_cost_price = cogs_row["items_missing_cost_price"]
    gross_profit_known = cogs_row["gross_sales"] - cogs_row["cogs_known"]

    return {
        "revenue": revenue_row["revenue"],
        "order_count": revenue_row["order_count"],
        "payment_status_breakdown": [dict(r) for r in status_breakdown],
        "payments": [dict(r) for r in payments],
        "gross_sales_confirmed": cogs_row["gross_sales"],
        "cogs_known": cogs_row["cogs_known"],
        "gross_profit_known": gross_profit_known,
        "items_missing_cost_price": items_missing_cost_price,
        "cogs_complete": items_missing_cost_price == 0,
        "refunded": refunded_row["refunded"],
        "net_revenue": revenue_row["revenue"] - refunded_row["refunded"],
    }


async def get_analytics(conn: asyncpg.Connection, *, date_from, date_to) -> dict:
    orders_over_time = await conn.fetch(
        """
        SELECT date_trunc('day', created_at) AS day, count(*) AS order_count,
               COALESCE(SUM(paid_amount), 0) AS revenue
        FROM orders
        WHERE created_at >= $1 AND created_at < $2
        GROUP BY day ORDER BY day
        """,
        date_from,
        date_to,
    )
    order_status_distribution = await conn.fetch(
        "SELECT status, count(*) AS count FROM orders WHERE created_at >= $1 AND created_at < $2 GROUP BY status",
        date_from,
        date_to,
    )
    payment_status_distribution = await conn.fetch(
        "SELECT status, count(*) AS count FROM payments WHERE submitted_at >= $1 AND submitted_at < $2 GROUP BY status",
        date_from,
        date_to,
    )
    # Best-selling products: SQL aggregation over order_items, bounded —
    # never loads all rows into Python (§16 performance requirement).
    best_selling = await conn.fetch(
        """
        SELECT oi.variant_id, oi.sku_snapshot, oi.product_name_snapshot,
               SUM(oi.quantity) AS total_quantity, COALESCE(SUM(oi.line_total), 0) AS total_revenue
        FROM order_items oi
        JOIN orders o ON o.id = oi.order_id
        WHERE o.created_at >= $1 AND o.created_at < $2 AND o.status = 'CONFIRMED'
        GROUP BY oi.variant_id, oi.sku_snapshot, oi.product_name_snapshot
        ORDER BY total_quantity DESC
        LIMIT 10
        """,
        date_from,
        date_to,
    )

    return {
        "orders_over_time": [dict(r) for r in orders_over_time],
        "order_status_distribution": {row["status"]: row["count"] for row in order_status_distribution},
        "payment_status_distribution": {row["status"]: row["count"] for row in payment_status_distribution},
        "best_selling_products": [dict(r) for r in best_selling],
    }


# --- Admin management --------------------------------------------------------


async def list_admins(conn: asyncpg.Connection) -> list[asyncpg.Record]:
    return await conn.fetch(
        "SELECT id, telegram_id, first_name, last_name, username, status, created_at "
        "FROM users WHERE role = 'ADMIN' AND deleted_at IS NULL ORDER BY created_at DESC"
    )


async def find_user_by_telegram_id(conn: asyncpg.Connection, *, telegram_id: int) -> asyncpg.Record | None:
    return await conn.fetchrow(
        "SELECT id, telegram_id, role, status FROM users WHERE telegram_id = $1 AND deleted_at IS NULL", telegram_id
    )


async def create_admin(
    conn: asyncpg.Connection, *, telegram_id: int, first_name: str | None, last_name: str | None, username: str | None
) -> asyncpg.Record:
    """Role is hardcoded 'ADMIN' here — never taken from a request body —
    so there is no code path by which a request payload could create an
    OWNER (ADR-11's partial unique index is the schema-level backstop; this
    is the application-level one). Reuses the exact same upsert-on-
    telegram_id shape as `identity.repository.find_or_create_user` (Phase
    03/04), so a person OWNER pre-registers here and who later opens the
    bot/Mini App for the first time gets recognized as the same row, not a
    duplicate — one place a user row's identity is ever keyed."""
    return await conn.fetchrow(
        """
        INSERT INTO users (telegram_id, role, status, first_name, last_name, username)
        VALUES ($1, 'ADMIN', 'ACTIVE', $2, $3, $4)
        ON CONFLICT (telegram_id) DO UPDATE SET role = 'ADMIN'
        WHERE users.role != 'OWNER'
        RETURNING id, telegram_id, role, status, first_name, last_name, username
        """,
        telegram_id,
        first_name,
        last_name,
        username,
    )


async def set_admin_status(conn: asyncpg.Connection, *, user_id: int, status: str) -> asyncpg.Record | None:
    """Guarded to role='ADMIN' only — this endpoint can never touch the
    OWNER row or a plain USER row, by construction, not by convention."""
    return await conn.fetchrow(
        "UPDATE users SET status = $2, updated_at = now() WHERE id = $1 AND role = 'ADMIN' AND deleted_at IS NULL "
        "RETURNING id, status",
        user_id,
        status,
    )


# --- Audit log listing --------------------------------------------------------

_SENSITIVE_KEY_MARKERS = ("password", "token", "secret", "credential")


def _redact(value: object) -> object:
    if isinstance(value, dict):
        return {
            k: ("[REDACTED]" if any(marker in k.lower() for marker in _SENSITIVE_KEY_MARKERS) else _redact(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact(v) for v in value]
    return value


@dataclass(frozen=True)
class AuditCursor:
    created_at: datetime
    id: int


def encode_audit_cursor(created_at, id_: int) -> str:
    payload = json.dumps({"c": created_at.isoformat(), "id": id_})
    return base64.urlsafe_b64encode(payload.encode()).decode()


def decode_audit_cursor(cursor: str) -> AuditCursor:
    payload = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
    # Parsed back into a real datetime — passing the ISO string as-is to
    # asyncpg for a timestamptz comparison raises DataError (asyncpg's
    # binary protocol requires an actual datetime object, not a string;
    # caught live while writing this phase's pagination test).
    return AuditCursor(created_at=datetime.fromisoformat(payload["c"]), id=payload["id"])


async def list_audit_logs(
    conn: asyncpg.Connection,
    *,
    entity_type: str | None = None,
    action: str | None = None,
    actor_id: int | None = None,
    cursor: str | None = None,
    limit: int = 50,
) -> list[dict]:
    conditions: list[str] = []
    params: list[object] = []

    def add(cond: str, value: object) -> None:
        params.append(value)
        conditions.append(cond.format(n=len(params)))

    if entity_type is not None:
        add("entity_type = ${n}", entity_type)
    if action is not None:
        add("action = ${n}", action)
    if actor_id is not None:
        add("actor_id = ${n}", actor_id)
    if cursor is not None:
        decoded = decode_audit_cursor(cursor)
        params.append(decoded.created_at)
        params.append(decoded.id)
        conditions.append(f"(created_at, id) < (${len(params) - 1}, ${len(params)})")

    params.append(limit)
    where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    rows = await conn.fetch(
        f"""
        SELECT id, actor_id, actor_role, action, entity_type, entity_id,
               old_data, new_data, ip, metadata, created_at
        FROM audit_logs
        {where_sql}
        ORDER BY created_at DESC, id DESC
        LIMIT ${len(params)}
        """,
        *params,
    )

    results = []
    for row in rows:
        record = dict(row)
        record["old_data"] = _redact(json.loads(record["old_data"])) if record["old_data"] else None
        record["new_data"] = _redact(json.loads(record["new_data"])) if record["new_data"] else None
        record["metadata"] = _redact(json.loads(record["metadata"])) if record["metadata"] else None
        results.append(record)
    return results


# --- Settings ------------------------------------------------------------------


async def get_all_settings(conn: asyncpg.Connection) -> list[asyncpg.Record]:
    return await conn.fetch("SELECT key, value, updated_at, updated_by FROM store_settings ORDER BY key")


async def upsert_setting(conn: asyncpg.Connection, *, key: str, value: str, actor_id: int) -> asyncpg.Record:
    return await conn.fetchrow(
        """
        INSERT INTO store_settings (key, value, updated_at, updated_by)
        VALUES ($1, $2::jsonb, now(), $3)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now(), updated_by = EXCLUDED.updated_by
        RETURNING key, value, updated_at, updated_by
        """,
        key,
        value,
        actor_id,
    )
