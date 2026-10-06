from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.config import Settings
from app.db.pool import get_conn
from app.domains.commerce.cart import service
from app.security.permissions import CurrentUser, get_current_user
from app.security.signing import signed_url_for_folder

router = APIRouter(prefix="/cart", tags=["cart"])


class AddItemRequest(BaseModel):
    variant_id: int
    quantity: int


class UpdateItemRequest(BaseModel):
    quantity: int


@router.get("")
async def get_cart(
    current_user: CurrentUser = Depends(get_current_user), conn: asyncpg.Connection = Depends(get_conn)
) -> dict:
    items = await service.get_cart(conn, user_id=current_user.id)
    return {"items": [_with_signed_image(i) for i in items]}


def _with_signed_image(item: dict) -> dict:
    """ADR-13: hech bir fayl imzosiz uzatilmaydi. Xom `storage_path` javobda
    qolmaydi — u ichki joylashuv, mijozga kerak emas va imzoni chetlab
    o'tishga urinish uchun ishora bo'ladi."""
    path = item.pop("primary_image_path", None)
    if not path:
        item["primary_image_url"] = None
        return item
    settings = Settings.from_env()
    item["primary_image_url"] = signed_url_for_folder(path, "products", settings.signing_secret)
    return item


@router.post("/items")
async def add_item(
    body: AddItemRequest,
    current_user: CurrentUser = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_conn),
) -> dict:
    try:
        item = await service.add_item(conn, user_id=current_user.id, variant_id=body.variant_id, quantity=body.quantity)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except asyncpg.exceptions.ForeignKeyViolationError as exc:
        # A `variant_id` that doesn't exist is bad client input, not a
        # server fault — 422, matching the admin catalog routes' existing
        # guard. Stock/price are deliberately NOT validated here (§7.3
        # puts that re-validation at checkout, docs/04_API_SPEC.md).
        raise HTTPException(status_code=422, detail="unknown variant") from exc
    return dict(item)


@router.patch("/items/{item_id}")
async def update_item(
    item_id: int,
    body: UpdateItemRequest,
    current_user: CurrentUser = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_conn),
) -> dict:
    try:
        item = await service.update_item(conn, user_id=current_user.id, cart_item_id=item_id, quantity=body.quantity)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if item is None:
        raise HTTPException(status_code=404, detail="cart item not found")
    return dict(item)


@router.delete("/items/{item_id}")
async def delete_item(
    item_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_conn),
) -> dict:
    deleted_id = await service.remove_item(conn, user_id=current_user.id, cart_item_id=item_id)
    if deleted_id is None:
        raise HTTPException(status_code=404, detail="cart item not found")
    return {"deleted": True}
