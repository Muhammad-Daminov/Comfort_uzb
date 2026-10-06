from __future__ import annotations

from datetime import datetime

import asyncpg

from app.domains.pricing import repository
from app.domains.pricing.resolver import ResolvedPrice, resolve_price
from app.security.audit import record_audit

DISCOUNT_KINDS = {"PERCENT", "FIXED"}
DISCOUNT_TARGET_TYPES = {"VARIANT", "PRODUCT", "BRAND", "CAR_MODEL", "ALL"}


async def current_price_for_variant(
    conn: asyncpg.Connection, *, variant_id: int, product_id: int, brand_id: int, base_price: int
) -> ResolvedPrice:
    car_model_ids = await repository.get_compatible_car_model_ids(conn, product_id=product_id)
    candidates = await repository.get_applicable_discounts(
        conn, variant_id=variant_id, product_id=product_id, brand_id=brand_id, car_model_ids=car_model_ids
    )
    return resolve_price(base_price, candidates)


# --- Admin (owner-only): discount management (§P2-4) ------------------------
# Every function assumes the caller is already authorized — Router layer
# checks `discounts.manage` (migration 0020) before calling any of these,
# same pattern as catalog/service.py's admin_* functions.


class InvalidDiscount(Exception):
    pass


def _validate_kind_value(kind: str, value: int) -> None:
    if kind not in DISCOUNT_KINDS:
        raise InvalidDiscount(f"invalid kind: {kind!r}")
    if value < 0:
        raise InvalidDiscount("value must be >= 0")
    if kind == "PERCENT" and value > 100:
        raise InvalidDiscount("PERCENT value must be <= 100")


def _validate_target(target_type: str, target_id: int | None) -> None:
    if target_type not in DISCOUNT_TARGET_TYPES:
        raise InvalidDiscount(f"invalid target_type: {target_type!r}")
    if target_type == "ALL" and target_id is not None:
        raise InvalidDiscount("target_id must be null when target_type is ALL")
    if target_type != "ALL" and target_id is None:
        raise InvalidDiscount(f"target_id is required for target_type {target_type!r}")


async def _discount_with_targets(conn: asyncpg.Connection, discount: asyncpg.Record) -> dict:
    targets = await repository.list_targets_for_discounts(conn, discount_ids=[discount["id"]])
    return {**dict(discount), "targets": [dict(t) for t in targets]}


async def admin_list_discounts(conn: asyncpg.Connection) -> list[dict]:
    discounts = await repository.list_discounts(conn)
    if not discounts:
        return []
    targets = await repository.list_targets_for_discounts(conn, discount_ids=[d["id"] for d in discounts])
    targets_by_discount: dict[int, list[dict]] = {}
    for row in targets:
        targets_by_discount.setdefault(row["discount_id"], []).append(dict(row))
    return [{**dict(d), "targets": targets_by_discount.get(d["id"], [])} for d in discounts]


async def admin_create_discount(
    conn: asyncpg.Connection,
    *,
    name: str,
    kind: str,
    value: int,
    starts_at: datetime | None,
    ends_at: datetime | None,
    priority: int,
    targets: list[tuple[str, int | None]],
    actor_id: int,
    actor_role: str,
) -> dict:
    _validate_kind_value(kind, value)
    if ends_at is not None and starts_at is not None and ends_at < starts_at:
        raise InvalidDiscount("ends_at must not be before starts_at")
    for target_type, target_id in targets:
        _validate_target(target_type, target_id)

    async with conn.transaction():
        discount = await repository.create_discount(
            conn, name=name, kind=kind, value=value, starts_at=starts_at, ends_at=ends_at, priority=priority,
        )
        for target_type, target_id in targets:
            await repository.add_discount_target(
                conn, discount_id=discount["id"], target_type=target_type, target_id=target_id
            )
        await record_audit(
            conn, actor_id=actor_id, actor_role=actor_role, action="discount.create",
            entity_type="discount", entity_id=discount["id"],
            new_data={"name": name, "kind": kind, "value": value, "targets": targets},
        )
        return await _discount_with_targets(conn, discount)


async def admin_update_discount(
    conn: asyncpg.Connection,
    *,
    discount_id: int,
    name: str | None,
    kind: str | None,
    value: int | None,
    starts_at: datetime | None,
    ends_at: datetime | None,
    priority: int | None,
    set_starts_at: bool,
    set_ends_at: bool,
    actor_id: int,
    actor_role: str,
) -> dict:
    existing = await repository.get_discount(conn, discount_id=discount_id)
    if existing is None:
        raise LookupError(f"discount {discount_id} not found")

    effective_kind = kind if kind is not None else existing["kind"]
    effective_value = value if value is not None else existing["value"]
    _validate_kind_value(effective_kind, effective_value)

    effective_starts = starts_at if set_starts_at else existing["starts_at"]
    effective_ends = ends_at if set_ends_at else existing["ends_at"]
    if effective_ends is not None and effective_starts is not None and effective_ends < effective_starts:
        raise InvalidDiscount("ends_at must not be before starts_at")

    async with conn.transaction():
        discount = await repository.update_discount(
            conn, discount_id=discount_id, name=name, kind=kind, value=value,
            starts_at=starts_at, ends_at=ends_at, priority=priority,
            set_starts_at=set_starts_at, set_ends_at=set_ends_at,
        )
        await record_audit(
            conn, actor_id=actor_id, actor_role=actor_role, action="discount.update",
            entity_type="discount", entity_id=discount_id,
            new_data={"name": name, "kind": kind, "value": value, "priority": priority},
        )
        return await _discount_with_targets(conn, discount)


async def admin_set_discount_active(
    conn: asyncpg.Connection, *, discount_id: int, is_active: bool, actor_id: int, actor_role: str
) -> dict:
    async with conn.transaction():
        discount = await repository.set_discount_active(conn, discount_id=discount_id, is_active=is_active)
        if discount is None:
            raise LookupError(f"discount {discount_id} not found")
        await record_audit(
            conn, actor_id=actor_id, actor_role=actor_role,
            action="discount.activate" if is_active else "discount.deactivate",
            entity_type="discount", entity_id=discount_id, new_data={"is_active": is_active},
        )
        return await _discount_with_targets(conn, discount)


async def admin_add_discount_target(
    conn: asyncpg.Connection,
    *,
    discount_id: int,
    target_type: str,
    target_id: int | None,
    actor_id: int,
    actor_role: str,
) -> dict:
    _validate_target(target_type, target_id)
    async with conn.transaction():
        existing = await repository.get_discount(conn, discount_id=discount_id)
        if existing is None:
            raise LookupError(f"discount {discount_id} not found")
        target = await repository.add_discount_target(
            conn, discount_id=discount_id, target_type=target_type, target_id=target_id
        )
        await record_audit(
            conn, actor_id=actor_id, actor_role=actor_role, action="discount.target_add",
            entity_type="discount", entity_id=discount_id,
            new_data={"target_type": target_type, "target_id": target_id},
        )
        return dict(target)


async def admin_remove_discount_target(
    conn: asyncpg.Connection, *, discount_id: int, row_id: int, actor_id: int, actor_role: str
) -> None:
    async with conn.transaction():
        removed = await repository.remove_discount_target(conn, discount_id=discount_id, row_id=row_id)
        if not removed:
            raise LookupError(f"target {row_id} not found for discount {discount_id}")
        await record_audit(
            conn, actor_id=actor_id, actor_role=actor_role, action="discount.target_remove",
            entity_type="discount", entity_id=discount_id, new_data={"row_id": row_id},
        )
