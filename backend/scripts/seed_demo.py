"""Demo catalogue for local development.

Nothing in the app is visible with an empty database, and every visual state
the design defines — discount badge, out of stock, low stock, a fitment list
long enough to be truncated — only appears if the data produces it. This
script creates exactly that data.

DEV ONLY. It refuses to run against a database whose name does not look
disposable unless COMFORT_SEED_FORCE=1 is set, so it cannot be pointed at
production by a mistyped DATABASE_URL.

Idempotent: every row is looked up before it is inserted, so running it
twice changes nothing. It never deletes anything.

    export DATABASE_URL="postgresql://comfort_app:<pw>@127.0.0.1:5432/comfort_dev"
    .venv/bin/python scripts/seed_demo.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import asyncpg

# Run as `python scripts/seed_demo.py` from backend/ — make `app` importable
# the same way conftest.py does for tests.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SAFE_NAME_HINTS = ("dev", "verify", "test", "local", "demo")

# --- catalogue ---------------------------------------------------------------
#
# 2026-09-30: business scope narrowed to SIDENA (seat covers) and SIDENA
# CHEXOLLARI (seat cover slipcovers) only — no other automotive accessory
# category. Every product below is a seat cover for a real UzAuto/Chevrolet-
# Uzbekistan lineup car model actually sold in Uzbekistan; no product is
# fitted to a model it does not actually fit, and no product image is
# created here (see the note below the PRODUCTS loop in `seed()`) — a
# mismatched car photo on a product is exactly the failure mode this brief
# forbids, so the frontend's neutral silhouette placeholder is used until a
# real, model-matched photo is uploaded through the admin panel.

PRODUCT_BRANDS = ["Chevrolet", "Daewoo"]

COLORS = [("Qora", "#111111"), ("Bej", "#D9C7A7"), ("Kulrang", "#6B7280"), ("Jigarrang", "#6B4423")]

# car brand -> [(model, [(generation, year_from, year_to)])]
VEHICLES: dict[str, list[tuple[str, list[tuple[str, int, int | None]]]]] = {
    "Daewoo": [
        ("Nexia 2", [("N150", 2008, 2016)]),
    ],
    "Chevrolet": [
        ("Nexia 3", [("R3", 2016, None)]),
        ("Cobalt", [("I", 2012, 2019), ("I restyling", 2020, None)]),
        ("Spark", [("M300", 2009, 2015), ("M400", 2015, None)]),
        ("Lacetti", [("J200", 2004, 2013)]),
        ("Malibu 2", [("XU8", 2016, None)]),
        ("Gentra", [("T300", 2015, None)]),
        ("Onix", [("Onix", 2020, None)]),
        ("Tracker", [("Gen 1", 2013, 2019), ("Gen 2", 2021, None)]),
    ],
}

# name, product brand, base price, variants [(colour, price delta, stock)],
# fitment [(car brand, model)]
PRODUCTS: list[dict] = [
    {"name": "Malibu 2 sidena", "brand": "Chevrolet", "price": 1_850_000,
     "variants": [("Qora", 0, 10), ("Bej", 80_000, 6)],
     "fits": [("Chevrolet", "Malibu 2")]},
    {"name": "Cobalt sidena", "brand": "Chevrolet", "price": 1_250_000,
     "variants": [("Qora", 0, 18), ("Kulrang", 40_000, 9)],
     "fits": [("Chevrolet", "Cobalt")]},
    {"name": "Nexia sidena", "brand": "Chevrolet", "price": 980_000,
     "variants": [("Qora", 0, 25), ("Bej", 50_000, 10)],
     # Ikkala avlod ham (Daewoo Nexia 2, Chevrolet Nexia 3) — moslik
     # ro'yxati kartada "yana N ta" ko'rsatishga yetarli.
     "fits": [("Chevrolet", "Nexia 3"), ("Daewoo", "Nexia 2")]},
    {"name": "Gentra sidena", "brand": "Chevrolet", "price": 1_050_000,
     "variants": [("Qora", 0, 14), ("Jigarrang", 45_000, 5)],
     "fits": [("Chevrolet", "Gentra")]},
    {"name": "Onix sidena", "brand": "Chevrolet", "price": 1_650_000,
     "variants": [("Qora", 0, 8), ("Bej", 70_000, 4)],
     "fits": [("Chevrolet", "Onix")]},
    {"name": "Tracker sidena", "brand": "Chevrolet", "price": 2_150_000,
     "variants": [("Qora", 0, 7), ("Kulrang", 60_000, 0)],   # ikkinchi rang tugagan
     "fits": [("Chevrolet", "Tracker")]},
    {"name": "Spark sidena", "brand": "Chevrolet", "price": 890_000,
     "variants": [("Qora", 0, 2)],   # kam qoldi
     "fits": [("Chevrolet", "Spark")]},
    {"name": "Lacetti sidena", "brand": "Chevrolet", "price": 1_150_000,
     "variants": [("Qora", 0, 0)],   # tugagan
     "fits": [("Chevrolet", "Lacetti")]},
    {"name": "Universal sidena chexoli, EVA", "brand": "Chevrolet", "price": 340_000,
     "variants": [("Qora", 0, 40), ("Kulrang", 20_000, 15)],
     # Ko'p modelga mos umumiy chexol — moslik ro'yxati kesilishini
     # ko'rsatadigan eng uzun ro'yxat.
     "fits": [("Chevrolet", "Nexia 3"), ("Chevrolet", "Cobalt"), ("Chevrolet", "Spark"),
              ("Chevrolet", "Malibu 2"), ("Chevrolet", "Gentra"), ("Chevrolet", "Onix"),
              ("Chevrolet", "Tracker"), ("Daewoo", "Nexia 2")]},
]

# Uch chegirma — old_price va −N% belgisi uchun.
DISCOUNTS = [
    ("Kuzgi chegirma 15%", "PERCENT", 15, 10, "PRODUCT", "Malibu 2 sidena"),
    ("Onix aksiyasi 10%", "PERCENT", 10, 10, "PRODUCT", "Onix sidena"),
    ("Chevrolet sidena chegirmasi 5%", "PERCENT", 5, 1, "BRAND", "Chevrolet"),
]


async def _one(conn, sql, *args):
    return await conn.fetchval(sql, *args)


async def _get_or_create(conn, table: str, name: str, insert_sql: str, *insert_args) -> int:
    existing = await _one(conn, f"SELECT id FROM {table} WHERE name = $1 AND deleted_at IS NULL", name)
    if existing:
        return existing
    return await _one(conn, insert_sql, *insert_args)


async def seed(conn) -> None:
    created = {"brands": 0, "vehicles": 0, "products": 0, "variants": 0, "fits": 0, "discounts": 0}

    brand_ids: dict[str, int] = {}
    for name in PRODUCT_BRANDS:
        before = await _one(conn, "SELECT id FROM brands WHERE name = $1 AND deleted_at IS NULL", name)
        brand_ids[name] = await _get_or_create(
            conn, "brands", name, "INSERT INTO brands (name) VALUES ($1) RETURNING id", name
        )
        if not before:
            created["brands"] += 1

    color_ids: dict[str, int] = {}
    for name, hex_code in COLORS:
        color_ids[name] = await _get_or_create(
            conn, "colors", name,
            "INSERT INTO colors (name, hex_code) VALUES ($1, $2) RETURNING id", name, hex_code,
        )

    # vehicles: brand -> model -> generation
    generation_ids: dict[tuple[str, str], list[int]] = {}
    for car_brand, models in VEHICLES.items():
        car_brand_id = await _get_or_create(
            conn, "car_brands", car_brand,
            "INSERT INTO car_brands (name) VALUES ($1) RETURNING id", car_brand,
        )
        for model_name, generations in models:
            model_id = await _one(
                conn,
                "SELECT id FROM car_models WHERE car_brand_id = $1 AND name = $2 AND deleted_at IS NULL",
                car_brand_id, model_name,
            )
            if not model_id:
                model_id = await _one(
                    conn,
                    "INSERT INTO car_models (car_brand_id, name) VALUES ($1, $2) RETURNING id",
                    car_brand_id, model_name,
                )
                created["vehicles"] += 1
            for gen_name, year_from, year_to in generations:
                gen_id = await _one(
                    conn,
                    "SELECT id FROM car_generations WHERE car_model_id = $1 AND name = $2 AND deleted_at IS NULL",
                    model_id, gen_name,
                )
                if not gen_id:
                    gen_id = await _one(
                        conn,
                        "INSERT INTO car_generations (car_model_id, name, year_from, year_to) "
                        "VALUES ($1, $2, $3, $4) RETURNING id",
                        model_id, gen_name, year_from, year_to,
                    )
                generation_ids.setdefault((car_brand, model_name), []).append(gen_id)

    product_ids: dict[str, int] = {}
    for spec in PRODUCTS:
        product_id = await _one(
            conn, "SELECT id FROM products WHERE name = $1 AND deleted_at IS NULL", spec["name"]
        )
        if not product_id:
            product_id = await _one(
                conn,
                "INSERT INTO products (name, description, brand_id, status) "
                "VALUES ($1, $2, $3, 'ACTIVE') RETURNING id",
                spec["name"], f"{spec['name']} — namoyish uchun demo mahsulot.", brand_ids[spec["brand"]],
            )
            created["products"] += 1
        product_ids[spec["name"]] = product_id

        for index, (color_name, delta, stock) in enumerate(spec["variants"]):
            sku = f"DEMO-{product_id}-{index}"
            exists = await _one(conn, "SELECT id FROM product_variants WHERE sku = $1", sku)
            if exists:
                continue
            price = spec["price"] + delta
            await conn.execute(
                "INSERT INTO product_variants "
                "(product_id, sku, color_id, price, required_initial_payment, stock_on_hand, status) "
                "VALUES ($1, $2, $3, $4, $5, $6, 'ACTIVE')",
                product_id, sku, color_ids[color_name], price, price // 3, stock,
            )
            created["variants"] += 1

        for car_brand, model_name in spec["fits"]:
            for gen_id in generation_ids.get((car_brand, model_name), []):
                already = await _one(
                    conn,
                    "SELECT id FROM product_compatibilities "
                    "WHERE product_id = $1 AND generation_id = $2 AND deleted_at IS NULL",
                    product_id, gen_id,
                )
                if already:
                    continue
                await conn.execute(
                    "INSERT INTO product_compatibilities (product_id, generation_id) VALUES ($1, $2)",
                    product_id, gen_id,
                )
                created["fits"] += 1

        # Demo ma'lumot RASM YARATMAYDI. Ilgari bu yerda har mahsulot uchun
        # bir tekis rangli to'rtburchak (ko'k/to'q sariq/yashil) yasalar va
        # `product_images` ga asosiy rasm sifatida yozilardi. Natijada
        # katalog "rasmi bor" ko'rinardi, aslida rasm yo'q edi — bu haqiqiy
        # holatni yashirdi va do'kon arzon ko'rinishga tushdi.
        #
        # Rasm yo'qligi endi frontendda ochiq ko'rsatiladi
        # (miniapp/src/components/product-media.ts — siluet + bosh harf).
        # Haqiqiy suratlar admin panelidan yuklanadi:
        # POST /admin/products/{id}/images.

    # ADR-8: `search_text` is written at product-write time by the admin
    # Service layer, which this script bypasses with raw INSERTs — so every
    # demo product had an empty `search_text` and GET /catalog/search
    # returned nothing at all in the dev environment. Rebuild through the
    # same shared function the admin routes use.
    from app.domains.catalog.repository import rebuild_search_text

    for product_id in product_ids.values():
        await rebuild_search_text(conn, product_id=product_id)

    # Discounts are not in the integration suite's TRUNCATE list while
    # `products` is truncated with RESTART IDENTITY, so after a test run the
    # demo's discounts survive but point at ids that now belong to different
    # rows — and the suite leaves its own discounts behind. Re-point and
    # re-activate ours, and switch off anything that is not part of the demo,
    # so the catalogue shows the four discounts this file describes and not
    # whatever a test happened to leave.
    demo_names = [name for name, *_ in DISCOUNTS]
    for name, kind, value, priority, target_type, target_name in DISCOUNTS:
        target_id = brand_ids[target_name] if target_type == "BRAND" else product_ids[target_name]
        discount_id = await _one(conn, "SELECT id FROM discounts WHERE name = $1", name)
        if discount_id is None:
            discount_id = await _one(
                conn,
                "INSERT INTO discounts (name, kind, value, priority, is_active) "
                "VALUES ($1, $2, $3, $4, true) RETURNING id",
                name, kind, value, priority,
            )
            created["discounts"] += 1
        else:
            await conn.execute("UPDATE discounts SET is_active = true WHERE id = $1", discount_id)

        existing_target = await _one(
            conn, "SELECT id FROM discount_targets WHERE discount_id = $1", discount_id
        )
        if existing_target is None:
            await conn.execute(
                "INSERT INTO discount_targets (discount_id, target_type, target_id) VALUES ($1, $2, $3)",
                discount_id, target_type, target_id,
            )
        else:
            await conn.execute(
                "UPDATE discount_targets SET target_type = $2, target_id = $3 WHERE id = $1",
                existing_target, target_type, target_id,
            )

    await conn.execute(
        "UPDATE discounts SET is_active = false WHERE name <> ALL($1::text[]) AND is_active", demo_names
    )

    print("Yaratildi:", ", ".join(f"{k}={v}" for k, v in created.items()))


async def main() -> int:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL o'rnatilmagan", file=sys.stderr)
        return 1

    db_name = dsn.rsplit("/", 1)[-1].split("?")[0]
    if not any(hint in db_name.lower() for hint in SAFE_NAME_HINTS) and os.environ.get("COMFORT_SEED_FORCE") != "1":
        print(
            f"'{db_name}' bazasi tashlab yuboriladigan (dev/test/demo) ko'rinmaydi.\n"
            "Bu skript faqat dev uchun. Rostdan xohlasangiz: COMFORT_SEED_FORCE=1",
            file=sys.stderr,
        )
        return 2

    conn = await asyncpg.connect(dsn)
    try:
        async with conn.transaction():
            await seed(conn)
    finally:
        await conn.close()

    print(f"Baza: {db_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
