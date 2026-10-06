from __future__ import annotations

import asyncpg


async def list_car_brands(conn: asyncpg.Connection) -> list[asyncpg.Record]:
    return await conn.fetch("SELECT id, name FROM car_brands WHERE deleted_at IS NULL ORDER BY name")


async def list_car_models(conn: asyncpg.Connection, *, car_brand_id: int) -> list[asyncpg.Record]:
    return await conn.fetch(
        "SELECT id, car_brand_id, name FROM car_models WHERE car_brand_id = $1 AND deleted_at IS NULL ORDER BY name",
        car_brand_id,
    )


async def list_car_generations(conn: asyncpg.Connection, *, car_model_id: int) -> list[asyncpg.Record]:
    return await conn.fetch(
        "SELECT id, car_model_id, name, year_from, year_to FROM car_generations "
        "WHERE car_model_id = $1 AND deleted_at IS NULL ORDER BY year_from NULLS FIRST",
        car_model_id,
    )
