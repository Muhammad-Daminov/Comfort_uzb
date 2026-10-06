"""§18/§23 of the v2 rebuild brief: strict schema validation for AI
commands, and the stub provider's deterministic text parser. No DB
required — these are pure-function/schema tests."""
from __future__ import annotations

import pytest

from app.ai.commands import InvalidPayload, UnknownCommand, validate_command
from app.ai.providers.stub import StubAIProvider


def test_increase_stock_requires_positive_delta():
    validate_command("INCREASE_STOCK", {"variant_id": 1, "delta": 1})
    with pytest.raises(InvalidPayload):
        validate_command("INCREASE_STOCK", {"variant_id": 1, "delta": -1})


def test_decrease_stock_requires_negative_delta():
    validate_command("DECREASE_STOCK", {"variant_id": 1, "delta": -1})
    with pytest.raises(InvalidPayload):
        validate_command("DECREASE_STOCK", {"variant_id": 1, "delta": 1})


def test_unknown_command_rejected():
    with pytest.raises(UnknownCommand):
        validate_command("DELETE_EVERYTHING", {})


def test_create_product_requires_positive_price():
    with pytest.raises(InvalidPayload):
        validate_command(
            "CREATE_PRODUCT",
            {"name": "Malibu 2", "brand_id": 1, "price": 0, "initial_stock": 1},
        )


def test_create_product_cost_price_optional():
    model = validate_command(
        "CREATE_PRODUCT",
        {"name": "Malibu 2", "brand_id": 1, "price": 500000, "initial_stock": 1},
    )
    assert model.cost_price is None


@pytest.mark.asyncio
async def test_stub_provider_parses_stock_increase():
    result = await StubAIProvider().generate_structured_command(text="Malibu 2 + 1")
    assert result.command_type == "INCREASE_STOCK"
    assert result.payload == {"product_query": "Malibu 2", "delta": 1}


@pytest.mark.asyncio
async def test_stub_provider_parses_stock_decrease():
    result = await StubAIProvider().generate_structured_command(text="Malibu 2 - 1")
    assert result.command_type == "DECREASE_STOCK"
    assert result.payload == {"product_query": "Malibu 2", "delta": -1}


@pytest.mark.asyncio
async def test_stub_provider_returns_none_for_unrecognized_text():
    result = await StubAIProvider().generate_structured_command(text="Bugun ob-havo qanday?")
    assert result.command_type is None


@pytest.mark.asyncio
async def test_stub_provider_parses_archive():
    result = await StubAIProvider().generate_structured_command(text="Malibu 2 ni arxivla")
    assert result.command_type == "ARCHIVE_PRODUCT"
    assert result.payload == {"product_query": "Malibu 2"}


@pytest.mark.asyncio
async def test_stub_provider_parses_price_change():
    result = await StubAIProvider().generate_structured_command(text="Malibu 2 narxini 550 dollarga o'zgartir")
    assert result.command_type == "UPDATE_PRICE"
    assert result.payload == {"product_query": "Malibu 2", "price": 550}


@pytest.mark.asyncio
async def test_stub_provider_parses_get_stock_question():
    result = await StubAIProvider().generate_structured_command(text="Malibu 2 dan nechta qoldi?")
    assert result.command_type == "GET_STOCK"
    assert result.payload == {"product_query": "Malibu 2"}


@pytest.mark.asyncio
async def test_stub_provider_parses_get_cost_price_question():
    result = await StubAIProvider().generate_structured_command(text="Malibu 2 ning tannarxi qancha?")
    assert result.command_type == "GET_COST_PRICE"
    assert result.payload == {"product_query": "Malibu 2"}


@pytest.mark.asyncio
async def test_stub_provider_parses_todays_order_count_question():
    result = await StubAIProvider().generate_structured_command(text="Bugun nechta buyurtma bo'ldi?")
    assert result.command_type == "GET_SALES_STATISTICS"
    assert set(result.payload.keys()) == {"date_from", "date_to"}


@pytest.mark.asyncio
async def test_stub_provider_parses_best_selling_question():
    result = await StubAIProvider().generate_structured_command(text="Qaysi mahsulotdan nechta sotildi?")
    assert result.command_type == "GET_SALES_STATISTICS"


@pytest.mark.asyncio
async def test_stub_provider_parses_revenue_question():
    result = await StubAIProvider().generate_structured_command(text="Bugungi tushum qancha?")
    assert result.command_type == "GET_REVENUE"


@pytest.mark.asyncio
async def test_stub_provider_parses_profit_question():
    result = await StubAIProvider().generate_structured_command(text="Foyda qancha bo'ldi?")
    assert result.command_type == "GET_PROFIT"


@pytest.mark.asyncio
async def test_stub_provider_parses_create_product_from_brief_example():
    result = await StubAIProvider().generate_structured_command(
        text="malibu 2, 2 ta old sidenasi, qora, koja, 500 dollar, 1 dona"
    )
    assert result.command_type == "CREATE_PRODUCT"
    assert result.payload["name"] == "malibu 2"
    assert result.payload["price"] == 500
    assert result.payload["initial_stock"] == 1
    assert "old sidenasi" in result.payload["description"]
    assert "brand_id" not in result.payload  # never guessed — §23


def test_create_product_via_ai_without_brand_fails_validation_not_guessing():
    from app.ai.commands import InvalidPayload

    with pytest.raises(InvalidPayload):
        validate_command(
            "CREATE_PRODUCT",
            {"name": "Malibu 2", "price": 500_000, "initial_stock": 1},
        )


def test_get_cost_price_command_requires_finance_view():
    from app.ai.commands import COMMAND_SPECS

    assert COMMAND_SPECS["GET_COST_PRICE"].permission == "finance.view"
    assert COMMAND_SPECS["GET_COST_PRICE"].read_only is True


# --- §P2-2 UPDATE_PRODUCT ------------------------------------------------


def test_update_product_command_requires_products_update_permission():
    from app.ai.commands import COMMAND_SPECS

    assert COMMAND_SPECS["UPDATE_PRODUCT"].permission == "products.update"
    assert COMMAND_SPECS["UPDATE_PRODUCT"].read_only is False


def test_update_product_schema_has_no_price_stock_or_cost_price_field():
    from app.ai.commands import UpdateProductPayload

    fields = UpdateProductPayload.model_fields
    for forbidden in ("price", "stock", "stock_on_hand", "cost_price"):
        assert forbidden not in fields, f"UPDATE_PRODUCT must never accept {forbidden!r}"


def test_update_product_requires_at_least_one_field():
    with pytest.raises(InvalidPayload):
        validate_command("UPDATE_PRODUCT", {"product_id": 1})


def test_update_product_valid_name_change():
    model = validate_command("UPDATE_PRODUCT", {"product_id": 1, "name": "Malibu 2 Premium"})
    assert model.name == "Malibu 2 Premium"


def test_update_product_invalid_product_type_rejected():
    with pytest.raises(InvalidPayload):
        validate_command("UPDATE_PRODUCT", {"product_id": 1, "product_type": "GILAMCHA"})


def test_update_product_valid_product_type_accepted():
    model = validate_command("UPDATE_PRODUCT", {"product_id": 1, "product_type": "SIDENA_COVER"})
    assert model.product_type == "SIDENA_COVER"


def test_update_product_empty_material_rejected():
    with pytest.raises(InvalidPayload):
        validate_command("UPDATE_PRODUCT", {"product_id": 1, "material": ""})


@pytest.mark.asyncio
async def test_stub_provider_parses_update_name():
    result = await StubAIProvider().generate_structured_command(text="Malibu 2 nomini Malibu 2 Premium qil")
    assert result.command_type == "UPDATE_PRODUCT"
    assert result.payload == {"product_query": "Malibu 2", "name": "Malibu 2 Premium"}


@pytest.mark.asyncio
async def test_stub_provider_parses_update_description():
    result = await StubAIProvider().generate_structured_command(text="Malibu 2 tavsifini premium koja sidena qil")
    assert result.command_type == "UPDATE_PRODUCT"
    assert result.payload == {"product_query": "Malibu 2", "description": "premium koja sidena"}


@pytest.mark.asyncio
async def test_stub_provider_parses_update_color():
    result = await StubAIProvider().generate_structured_command(text="Malibu 2 rangini qora qil")
    assert result.command_type == "UPDATE_PRODUCT"
    assert result.payload == {"product_query": "Malibu 2", "color_query": "qora"}


@pytest.mark.asyncio
async def test_stub_provider_parses_update_material():
    result = await StubAIProvider().generate_structured_command(text="Malibu 2 materialini koja qil")
    assert result.command_type == "UPDATE_PRODUCT"
    assert result.payload == {"product_query": "Malibu 2", "material": "koja"}


@pytest.mark.asyncio
async def test_stub_provider_parses_update_type_sidena():
    result = await StubAIProvider().generate_structured_command(text="Malibu 2 turini sidena qil")
    assert result.command_type == "UPDATE_PRODUCT"
    assert result.payload == {"product_query": "Malibu 2", "product_type": "SIDENA"}


@pytest.mark.asyncio
async def test_stub_provider_parses_update_type_sidena_cover():
    result = await StubAIProvider().generate_structured_command(text="Malibu 2 turini sidena chexoli qil")
    assert result.command_type == "UPDATE_PRODUCT"
    assert result.payload == {"product_query": "Malibu 2", "product_type": "SIDENA_COVER"}
