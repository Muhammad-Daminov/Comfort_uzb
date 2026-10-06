from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query

from app.config import Settings
from app.db.pool import get_conn
from app.domains.catalog import repository, service
from app.security.signing import signed_url_for_folder

router = APIRouter(prefix="/catalog", tags=["catalog"])


@router.get("/products")
async def list_products(
    car_brand_id: int | None = None,
    car_model_id: int | None = None,
    brand_id: int | None = None,
    color_id: int | None = None,
    price_min: int | None = None,
    price_max: int | None = None,
    in_stock_only: bool = False,
    sort: str = Query(default="newest"),
    cursor: str | None = None,
    limit: int = Query(default=20, le=100, gt=0),
    conn: asyncpg.Connection = Depends(get_conn),
) -> dict:
    try:
        rows = await service.list_products(
            conn,
            car_brand_id=car_brand_id,
            car_model_id=car_model_id,
            brand_id=brand_id,
            color_id=color_id,
            price_min=price_min,
            price_max=price_max,
            in_stock_only=in_stock_only,
            sort=sort,
            cursor=cursor,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    sort_field = {"newest": "created_at", "price_asc": "min_price", "price_desc": "min_price", "popular": "popularity"}[sort]
    next_cursor = None
    # A page shorter than `limit` is the last one: emitting a cursor for it
    # made the Mini App show "Ko'proq ko'rsatish" after the final page and
    # fetch an empty page on tap.
    if rows and len(rows) == limit:
        last = rows[-1]
        # The cursor must carry the value the SQL actually sorted on. The
        # service replaces `min_price` with the discounted price for display
        # and keeps the original under `base_min_price`; encoding the
        # discounted one here would make the next page skip or repeat rows.
        cursor_value = last["base_min_price"] if sort_field == "min_price" else last[sort_field]
        next_cursor = repository.encode_cursor(cursor_value, last["id"])

    return {"items": _card_items(rows), "next_cursor": next_cursor}


def _card_items(rows: list[dict]) -> list[dict]:
    """ADR-13: no file is ever served unsigned, so a card's thumbnail is
    signed here exactly like the detail endpoint's images — same helper,
    same `products` folder TTL. The raw storage_path never leaves the
    server. Shared by the listing and search endpoints (same card shape)."""
    settings = Settings.from_env()
    items = []
    for row in rows:
        item = dict(row)
        # Internal only — it exists so the listing cursor can sort on the
        # pre-discount value; the client has no use for it.
        item.pop("base_min_price", None)
        item.pop("rank", None)
        path = item.pop("primary_image_path", None)
        item["primary_image_url"] = (
            signed_url_for_folder(path, "products", settings.signing_secret) if path else None
        )
        items.append(item)
    return items


@router.get("/products/{product_id}")
async def get_product(product_id: int, conn: asyncpg.Connection = Depends(get_conn)) -> dict:
    detail = await service.get_product_detail(conn, product_id=product_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="product not found")

    # Phase 05 gap: images carried only a raw storage_path, but ADR-13 is
    # explicit that no file is ever served unsigned. Signing here (not
    # storing a signed URL) keeps the TTL fresh on every fetch — the Mini
    # App re-requests the product on expiry rather than caching a stale URL.
    settings = Settings.from_env()
    for image in detail["images"]:
        image["signed_url"] = signed_url_for_folder(image["storage_path"], "products", settings.signing_secret)

    return detail


@router.get("/search")
async def search(
    q: str = Query(..., min_length=1), conn: asyncpg.Connection = Depends(get_conn)
) -> dict:
    rows = await service.search_products(conn, query=q)
    return {"items": _card_items(rows)}


@router.get("/filters")
async def filters(conn: asyncpg.Connection = Depends(get_conn)) -> dict:
    data = await service.list_filters(conn)
    return {k: [dict(r) for r in v] for k, v in data.items()}
