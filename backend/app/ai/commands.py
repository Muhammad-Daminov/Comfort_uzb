"""§18 of the v2 rebuild brief: a controlled tool/command system. Every
command has a strict schema (pydantic), a required permission (reuses the
exact same `permissions` keys the manual admin endpoints check — this is
what makes "AI cannot grant itself permissions" true by construction: the
AI-issued command hits the identical `has_permission` check a human-driven
request would), and a `read_only` flag that decides whether it executes
immediately (§19: reads execute after authorization) or requires the
draft/preview/confirmation workflow (mutations).

Nothing here talks to a model or to the database — it is pure schema.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class CreateProductPayload(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    brand_id: int
    color_id: int | None = None
    price: int = Field(gt=0)
    initial_stock: int = Field(ge=0)
    cost_price: int | None = Field(default=None, ge=0)
    # §16 of the brief: preserve the Telegram file reference, don't download
    # at draft time. Resolved to actual image bytes only at confirm time
    # (app/ai/executor.py::_create_product), and only via the bot handler
    # that has a live Bot instance — never guessed/re-derived.
    telegram_image_file_id: str | None = None


class UpdateStockPayload(BaseModel):
    variant_id: int
    delta: int  # positive for INCREASE_STOCK, negative for DECREASE_STOCK — validated per command_type


class UpdatePricePayload(BaseModel):
    variant_id: int
    price: int = Field(gt=0)


class ArchiveProductPayload(BaseModel):
    product_id: int


class UpdateProductPayload(BaseModel):
    """§P2-2. Deliberately excludes price/stock/cost_price — those go
    through UPDATE_PRICE/INCREASE_STOCK/DECREASE_STOCK and the dedicated
    finance.view-gated cost-price endpoint respectively, never this
    generic command (checked again in drafts/service.py before execution,
    not just by omission here)."""

    product_id: int
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    product_type: Literal["SIDENA", "SIDENA_COVER"] | None = None
    brand_id: int | None = None
    # Variant-level (material/color): only meaningful when the product has
    # exactly one variant, or `sku` disambiguates which one — resolved in
    # app/ai/executor.py, never guessed.
    material: str | None = Field(default=None, min_length=1)
    color_id: int | None = None
    sku: str | None = None


class GetProductPayload(BaseModel):
    query: str = Field(min_length=1, max_length=200)


class GetStockPayload(BaseModel):
    variant_id: int


class GetOrderPayload(BaseModel):
    order_number: str


class DateRangePayload(BaseModel):
    date_from: str  # ISO date, validated/parsed by the executor
    date_to: str


class CommandSpec(BaseModel):
    permission: str
    read_only: bool
    payload_model: type[BaseModel]

    model_config = {"arbitrary_types_allowed": True}


COMMAND_SPECS: dict[str, CommandSpec] = {
    "CREATE_PRODUCT": CommandSpec(permission="products.create", read_only=False, payload_model=CreateProductPayload),
    "INCREASE_STOCK": CommandSpec(permission="inventory.manage", read_only=False, payload_model=UpdateStockPayload),
    "DECREASE_STOCK": CommandSpec(permission="inventory.manage", read_only=False, payload_model=UpdateStockPayload),
    "UPDATE_PRICE": CommandSpec(permission="products.update", read_only=False, payload_model=UpdatePricePayload),
    "ARCHIVE_PRODUCT": CommandSpec(permission="products.archive", read_only=False, payload_model=ArchiveProductPayload),
    "UPDATE_PRODUCT": CommandSpec(permission="products.update", read_only=False, payload_model=UpdateProductPayload),
    "GET_PRODUCT": CommandSpec(permission="catalog.view", read_only=True, payload_model=GetProductPayload),
    "GET_STOCK": CommandSpec(permission="catalog.view", read_only=True, payload_model=GetStockPayload),
    "GET_ORDER": CommandSpec(permission="orders.view.all", read_only=True, payload_model=GetOrderPayload),
    "GET_SALES_STATISTICS": CommandSpec(permission="analytics.view", read_only=True, payload_model=DateRangePayload),
    "GET_REVENUE": CommandSpec(permission="finance.view", read_only=True, payload_model=DateRangePayload),
    "GET_PROFIT": CommandSpec(permission="finance.view", read_only=True, payload_model=DateRangePayload),
    # §12/§13 of the v2 brief: cost price is financial data — same
    # finance.view gate as the manual cost-price endpoint and CREATE_PRODUCT's
    # optional cost_price field (drafts/service.py).
    "GET_COST_PRICE": CommandSpec(permission="finance.view", read_only=True, payload_model=GetStockPayload),
}


class UnknownCommand(Exception):
    pass


class InvalidPayload(Exception):
    pass


def validate_command(command_type: str, payload: dict) -> BaseModel:
    """Re-validated on every use (draft creation AND confirmation) — the
    payload stored on the draft is the only payload confirmation ever
    executes against (§24: a confirmation cannot later be reused/altered
    for different values)."""
    spec = COMMAND_SPECS.get(command_type)
    if spec is None:
        raise UnknownCommand(f"unknown AI command type: {command_type!r}")
    try:
        model = spec.payload_model.model_validate(payload)
    except Exception as exc:  # pydantic.ValidationError
        raise InvalidPayload(str(exc)) from exc

    if command_type == "INCREASE_STOCK" and model.delta <= 0:
        raise InvalidPayload("INCREASE_STOCK requires a positive delta")
    if command_type == "DECREASE_STOCK" and model.delta >= 0:
        raise InvalidPayload("DECREASE_STOCK requires a negative delta")
    if command_type == "UPDATE_PRODUCT" and all(
        getattr(model, f) is None for f in ("name", "description", "product_type", "brand_id", "material", "color_id")
    ):
        raise InvalidPayload("UPDATE_PRODUCT requires at least one field to change")

    return model
