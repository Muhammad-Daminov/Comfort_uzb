"""Executes a validated AI command against the real domain services — the
only place AI-derived values ever reach a database write, and only after
`commands.validate_command` has re-checked the payload and the caller's
permission has been re-checked (drafts/service.py does both before calling
this). Every mutation here is the exact same domain-service call a human
admin's manual endpoint makes; nothing here is a shortcut around them.
"""
from __future__ import annotations

from datetime import datetime, timezone
from secrets import token_hex
from typing import TYPE_CHECKING

import asyncpg

from app.domains.catalog import repository as catalog_repository
from app.domains.catalog import service as catalog_service
from app.domains.commerce.inventory import repository as inventory_repository
from app.domains.commerce.orders import repository as orders_repository
from app.domains.owner import repository as owner_repository
from app.security.permissions import CurrentUser

if TYPE_CHECKING:
    from aiogram import Bot


class ExecutionError(Exception):
    pass


def _generate_sku(name: str) -> str:
    slug = "".join(ch for ch in name.upper() if ch.isalnum())[:12] or "ITEM"
    return f"{slug}-{token_hex(3).upper()}"


async def _attach_telegram_image(
    conn: asyncpg.Connection, *, product_id: int, file_id: str, bot: "Bot", actor: CurrentUser
) -> None:
    """§16: the Telegram file reference is preserved on the draft and
    downloaded exactly once, here, at confirm time — never at draft time
    (the product/product_id it needs to attach to doesn't exist yet), and
    never re-uploaded/duplicated anywhere else."""
    from app.config import Settings
    from app.security.uploads import InvalidUpload, validate_and_process_image

    telegram_file = await bot.get_file(file_id)
    buffer = await bot.download_file(telegram_file.file_path)
    file_bytes = buffer.read()

    settings = Settings.from_env()
    try:
        processed = validate_and_process_image(file_bytes, settings.uploads_root, folder="products", entity_id=product_id)
    except InvalidUpload as exc:
        raise ExecutionError(f"invalid product image: {exc}") from exc

    await catalog_service.admin_add_image(
        conn, product_id=product_id, storage_path=processed.storage_path, width=processed.width,
        height=processed.height, actor_id=actor.id, actor_role=actor.role,
    )


async def _create_product(conn: asyncpg.Connection, payload, actor: CurrentUser, bot: "Bot | None" = None) -> dict:
    product = await catalog_service.admin_create_product(
        conn, name=payload.name, description=payload.description, brand_id=payload.brand_id,
        actor_id=actor.id, actor_role=actor.role,
    )
    variant = await catalog_service.admin_create_variant(
        conn, product_id=product["id"], sku=_generate_sku(payload.name), color_id=payload.color_id,
        price=payload.price, required_initial_payment=0, actor_id=actor.id, actor_role=actor.role,
    )
    if payload.initial_stock > 0:
        await inventory_repository.adjust_stock(
            conn, variant_id=variant["id"], quantity_change=payload.initial_stock,
            reason="AI product creation — initial stock", actor_id=actor.id,
        )
    if payload.cost_price is not None:
        # Only reachable if the schema accepted cost_price at all — the
        # draft-creation permission check (drafts/service.py) already
        # requires finance.view for any payload containing this field, so a
        # non-OWNER admin's command is rejected before this ever runs.
        await catalog_service.admin_set_variant_cost_price(
            conn, variant_id=variant["id"], cost_price=payload.cost_price, actor_id=actor.id, actor_role=actor.role,
        )
    if payload.telegram_image_file_id is not None and bot is not None:
        await _attach_telegram_image(
            conn, product_id=product["id"], file_id=payload.telegram_image_file_id, bot=bot, actor=actor,
        )
    return {"entity_type": "product", "entity_id": product["id"], "variant_id": variant["id"], "sku": variant["sku"]}


async def _update_stock(conn: asyncpg.Connection, payload, actor: CurrentUser) -> dict:
    reason = "AI stock increase" if payload.delta > 0 else "AI stock decrease"
    movement = await inventory_repository.adjust_stock(
        conn, variant_id=payload.variant_id, quantity_change=payload.delta, reason=reason, actor_id=actor.id,
    )
    return {"entity_type": "product_variant", "entity_id": payload.variant_id, "quantity_after": movement["quantity_after"]}


async def _update_price(conn: asyncpg.Connection, payload, actor: CurrentUser) -> dict:
    variant = await catalog_service.admin_update_variant(
        conn, variant_id=payload.variant_id, sku=None, color_id=None, price=payload.price,
        required_initial_payment=None, actor_id=actor.id, actor_role=actor.role,
    )
    return {"entity_type": "product_variant", "entity_id": variant["id"], "price": variant["price"]}


async def _update_product(conn: asyncpg.Connection, payload, actor: CurrentUser) -> dict:
    """§P2-2: product-level fields (name/description/product_type/brand)
    always go through the existing admin_update_product service — the same
    function and business rules the manual PATCH /admin/products endpoint
    uses. Variant-level fields (material/color) are never applied to an
    ambiguous target: with more than one variant, `sku` must name exactly
    which one, or this raises rather than guessing."""
    result: dict = {"entity_type": "product", "entity_id": payload.product_id}

    if any(v is not None for v in (payload.name, payload.description, payload.product_type, payload.brand_id)):
        product = await catalog_service.admin_update_product(
            conn, product_id=payload.product_id, name=payload.name, description=payload.description,
            brand_id=payload.brand_id, product_type=payload.product_type,
            actor_id=actor.id, actor_role=actor.role,
        )
        result["product"] = {"name": product["name"], "product_type": product["product_type"]}

    if payload.material is not None or payload.color_id is not None:
        variants = await catalog_repository.get_variants_for_product(conn, product_id=payload.product_id)
        if not variants:
            raise ExecutionError(f"product {payload.product_id} has no variants to apply material/color to")
        if len(variants) == 1:
            target_variant = variants[0]
        elif payload.sku:
            matches = [v for v in variants if v["sku"] == payload.sku]
            if not matches:
                raise ExecutionError(f"no variant with sku {payload.sku!r} on product {payload.product_id}")
            target_variant = matches[0]
        else:
            raise ExecutionError(
                f"product {payload.product_id} has {len(variants)} variants — specify sku to target one for material/color"
            )
        variant = await catalog_service.admin_update_variant(
            conn, variant_id=target_variant["id"], sku=None, color_id=payload.color_id, price=None,
            required_initial_payment=None, material=payload.material,
            actor_id=actor.id, actor_role=actor.role,
        )
        result["variant_id"] = variant["id"]
        result["material"] = variant["material"]
        result["color_id"] = variant["color_id"]

    return result


async def _archive_product(conn: asyncpg.Connection, payload, actor: CurrentUser) -> dict:
    product = await catalog_service.admin_set_product_status(
        conn, product_id=payload.product_id, status="ARCHIVED", actor_id=actor.id, actor_role=actor.role,
    )
    return {"entity_type": "product", "entity_id": product["id"], "status": product["status"]}


async def _get_product(conn: asyncpg.Connection, payload, actor: CurrentUser) -> dict:
    rows = await conn.fetch(
        """
        SELECT p.id AS product_id, p.name, v.id AS variant_id, v.sku, v.price,
               v.stock_on_hand - v.stock_reserved AS available
        FROM products p JOIN product_variants v ON v.product_id = p.id
        WHERE p.deleted_at IS NULL AND v.deleted_at IS NULL AND p.name ILIKE $1
        ORDER BY p.name LIMIT 10
        """,
        f"%{payload.query}%",
    )
    return {"matches": [dict(r) for r in rows]}


async def _get_stock(conn: asyncpg.Connection, payload, actor: CurrentUser) -> dict:
    variant = await catalog_repository.get_variant(conn, variant_id=payload.variant_id)
    if variant is None:
        raise ExecutionError(f"variant {payload.variant_id} not found")
    return {
        "variant_id": variant["id"],
        "product_name": variant["product_name"],
        "stock_on_hand": variant["stock_on_hand"],
        "stock_reserved": variant["stock_reserved"],
        "available": variant["stock_on_hand"] - variant["stock_reserved"],
    }


async def _get_cost_price(conn: asyncpg.Connection, payload, actor: CurrentUser) -> dict:
    variant = await catalog_repository.get_variant(conn, variant_id=payload.variant_id)
    if variant is None:
        raise ExecutionError(f"variant {payload.variant_id} not found")
    if variant["cost_price"] is None:
        # §13 of the brief: "do not claim profit if cost information does
        # not exist" — applies equally to a direct cost-price query.
        return {"variant_id": variant["id"], "product_name": variant["product_name"], "cost_price": None,
                "note": "cost_price not recorded for this variant"}
    return {"variant_id": variant["id"], "product_name": variant["product_name"], "cost_price": variant["cost_price"]}


async def _get_order(conn: asyncpg.Connection, payload, actor: CurrentUser) -> dict:
    order = await orders_repository.get_order_by_number(conn, order_number=payload.order_number)
    if order is None:
        raise ExecutionError(f"order {payload.order_number} not found")
    return dict(order)


def _parse_range(payload) -> tuple[datetime, datetime]:
    date_from = datetime.fromisoformat(payload.date_from).replace(tzinfo=timezone.utc)
    date_to = datetime.fromisoformat(payload.date_to).replace(tzinfo=timezone.utc)
    return date_from, date_to


async def _get_sales_statistics(conn: asyncpg.Connection, payload, actor: CurrentUser) -> dict:
    date_from, date_to = _parse_range(payload)
    return await owner_repository.get_analytics(conn, date_from=date_from, date_to=date_to)


async def _get_revenue(conn: asyncpg.Connection, payload, actor: CurrentUser) -> dict:
    date_from, date_to = _parse_range(payload)
    summary = await owner_repository.get_finance_summary(conn, date_from=date_from, date_to=date_to)
    return {
        "revenue": summary["revenue"],
        "refunded": summary["refunded"],
        "net_revenue": summary["net_revenue"],
        "order_count": summary["order_count"],
    }


async def _get_profit(conn: asyncpg.Connection, payload, actor: CurrentUser) -> dict:
    date_from, date_to = _parse_range(payload)
    summary = await owner_repository.get_finance_summary(conn, date_from=date_from, date_to=date_to)
    return {
        "gross_sales_confirmed": summary["gross_sales_confirmed"],
        "cogs_known": summary["cogs_known"],
        "gross_profit_known": summary["gross_profit_known"],
        "cogs_complete": summary["cogs_complete"],
        "items_missing_cost_price": summary["items_missing_cost_price"],
    }


_EXECUTORS = {
    "CREATE_PRODUCT": _create_product,
    "INCREASE_STOCK": _update_stock,
    "DECREASE_STOCK": _update_stock,
    "UPDATE_PRICE": _update_price,
    "ARCHIVE_PRODUCT": _archive_product,
    "UPDATE_PRODUCT": _update_product,
    "GET_PRODUCT": _get_product,
    "GET_STOCK": _get_stock,
    "GET_ORDER": _get_order,
    "GET_SALES_STATISTICS": _get_sales_statistics,
    "GET_REVENUE": _get_revenue,
    "GET_PROFIT": _get_profit,
    "GET_COST_PRICE": _get_cost_price,
}


async def execute(
    conn: asyncpg.Connection, *, command_type: str, payload, actor: CurrentUser, bot: "Bot | None" = None
) -> dict:
    executor = _EXECUTORS.get(command_type)
    if executor is None:
        raise ExecutionError(f"no executor registered for {command_type!r}")
    if command_type == "CREATE_PRODUCT":
        return await executor(conn, payload, actor, bot=bot)
    return await executor(conn, payload, actor)
