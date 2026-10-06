from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Depends, Query

from app.db.pool import get_conn
from app.domains.vehicle import repository

router = APIRouter(prefix="/vehicles", tags=["vehicles"])


@router.get("/brands")
async def brands(conn: asyncpg.Connection = Depends(get_conn)) -> dict:
    rows = await repository.list_car_brands(conn)
    return {"items": [dict(r) for r in rows]}


@router.get("/models")
async def models(car_brand_id: int = Query(...), conn: asyncpg.Connection = Depends(get_conn)) -> dict:
    rows = await repository.list_car_models(conn, car_brand_id=car_brand_id)
    return {"items": [dict(r) for r in rows]}


@router.get("/generations")
async def generations(car_model_id: int = Query(...), conn: asyncpg.Connection = Depends(get_conn)) -> dict:
    rows = await repository.list_car_generations(conn, car_model_id=car_model_id)
    return {"items": [dict(r) for r in rows]}
