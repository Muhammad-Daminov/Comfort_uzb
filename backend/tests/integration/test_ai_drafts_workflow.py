"""§14-25/§38 of the v2 rebuild brief, exercised against a real DB: the
mandatory AI architecture (structured command -> backend validation ->
draft/preview -> admin confirmation -> domain service -> DB), never a
direct AI-to-database write. Uses the stub AI provider's deterministic
text parser (no live model call) plus the real resolver/executor/drafts
service — this is the actual production code path, only the "understand
free text" step is swapped for a deterministic stand-in.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.ai import resolver
from app.ai.drafts import repository as drafts_repository
from app.ai.drafts import service as drafts_service
from app.ai.providers.stub import StubAIProvider
from app.ai.resolver import resolve_command_references
from app.security.permissions import CurrentUser
from tests.integration import factories

pytestmark = pytest.mark.asyncio


def _actor(user_id: int, role: str) -> CurrentUser:
    return CurrentUser(id=user_id, telegram_id=user_id, role=role, status="ACTIVE")


async def _make_stocked_product(conn, *, name: str, stock: int = 1):
    brand_id = await factories.make_brand(conn, name=f"{name} Brand")
    product_id = await factories.make_product(conn, brand_id=brand_id, name=name)
    variant_id = await factories.make_variant(
        conn, product_id=product_id, sku=f"{name.upper().replace(' ', '')}-SKU", price=500_000, stock_on_hand=stock
    )
    return product_id, variant_id


async def _draft_for_stock_command(conn, admin_id: int, text: str):
    result = await StubAIProvider().generate_structured_command(text=text)
    payload = await resolve_command_references(conn, result.command_type, result.payload)
    outcome = await drafts_service.handle_command(
        conn, actor=_actor(admin_id, "ADMIN"), command_type=result.command_type, raw_payload=payload, source="TEXT",
    )
    return outcome


async def test_text_stock_increase_creates_draft_not_immediate_mutation(conn, clean_slate):
    admin_id = await factories.make_user(conn, role="ADMIN")
    _product_id, variant_id = await _make_stocked_product(conn, name="Malibu Draft One", stock=1)

    outcome = await _draft_for_stock_command(conn, admin_id, "Malibu Draft One + 1")
    assert outcome["executed"] is False
    assert "draft_id" in outcome

    # Nothing written yet — the draft alone must never mutate stock.
    row = await conn.fetchrow("SELECT stock_on_hand FROM product_variants WHERE id = $1", variant_id)
    assert row["stock_on_hand"] == 1


async def test_confirm_applies_exact_frozen_payload(conn, clean_slate):
    admin_id = await factories.make_user(conn, role="ADMIN")
    _product_id, variant_id = await _make_stocked_product(conn, name="Malibu Draft Two", stock=1)

    outcome = await _draft_for_stock_command(conn, admin_id, "Malibu Draft Two + 1")
    result = await drafts_service.confirm(
        conn, draft_id=outcome["draft_id"], confirmation_token=outcome["confirmation_token"], actor=_actor(admin_id, "ADMIN"),
    )
    assert result["result"]["quantity_after"] == 2

    row = await conn.fetchrow("SELECT stock_on_hand FROM product_variants WHERE id = $1", variant_id)
    assert row["stock_on_hand"] == 2


async def test_confirmation_cannot_be_reused(conn, clean_slate):
    admin_id = await factories.make_user(conn, role="ADMIN")
    await _make_stocked_product(conn, name="Malibu Draft Three", stock=1)

    outcome = await _draft_for_stock_command(conn, admin_id, "Malibu Draft Three + 1")
    await drafts_service.confirm(
        conn, draft_id=outcome["draft_id"], confirmation_token=outcome["confirmation_token"], actor=_actor(admin_id, "ADMIN"),
    )
    with pytest.raises(drafts_service.DraftNotPending):
        await drafts_service.confirm(
            conn, draft_id=outcome["draft_id"], confirmation_token=outcome["confirmation_token"], actor=_actor(admin_id, "ADMIN"),
        )


async def test_expired_draft_cannot_be_confirmed(conn, clean_slate):
    admin_id = await factories.make_user(conn, role="ADMIN")
    await _make_stocked_product(conn, name="Malibu Draft Four", stock=1)

    outcome = await _draft_for_stock_command(conn, admin_id, "Malibu Draft Four + 1")
    await conn.execute(
        "UPDATE ai_command_drafts SET expires_at = $2 WHERE id = $1",
        outcome["draft_id"], datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    with pytest.raises(drafts_service.DraftExpired):
        await drafts_service.confirm(
            conn, draft_id=outcome["draft_id"], confirmation_token=outcome["confirmation_token"], actor=_actor(admin_id, "ADMIN"),
        )
    expired = await drafts_repository.get_draft(conn, draft_id=outcome["draft_id"])
    assert expired["status"] == "FAILED"


async def test_wrong_token_is_rejected(conn, clean_slate):
    admin_id = await factories.make_user(conn, role="ADMIN")
    await _make_stocked_product(conn, name="Malibu Draft Five", stock=1)

    outcome = await _draft_for_stock_command(conn, admin_id, "Malibu Draft Five + 1")
    with pytest.raises(drafts_service.Forbidden):
        await drafts_service.confirm(
            conn, draft_id=outcome["draft_id"], confirmation_token="wrong-token-entirely", actor=_actor(admin_id, "ADMIN"),
        )


async def test_another_admin_cannot_confirm_someone_elses_draft(conn, clean_slate):
    admin_id = await factories.make_user(conn, role="ADMIN")
    other_admin_id = await factories.make_user(conn, role="ADMIN")
    await _make_stocked_product(conn, name="Malibu Draft Six", stock=1)

    outcome = await _draft_for_stock_command(conn, admin_id, "Malibu Draft Six + 1")
    with pytest.raises(drafts_service.DraftNotOwnedByCaller):
        await drafts_service.confirm(
            conn, draft_id=outcome["draft_id"], confirmation_token=outcome["confirmation_token"], actor=_actor(other_admin_id, "ADMIN"),
        )


async def test_user_role_cannot_issue_ai_commands(conn, clean_slate):
    user_id = await factories.make_user(conn, role="USER")
    await _make_stocked_product(conn, name="Malibu Draft Seven", stock=1)

    with pytest.raises(drafts_service.Forbidden):
        await drafts_service.handle_command(
            conn, actor=_actor(user_id, "USER"), command_type="INCREASE_STOCK",
            raw_payload={"variant_id": 1, "delta": 1}, source="TEXT",
        )


async def test_ambiguous_product_reference_is_reported_not_guessed(conn, clean_slate):
    brand_id = await factories.make_brand(conn, name="Ambiguous Brand")
    product_id = await factories.make_product(conn, brand_id=brand_id, name="Malibu Ambiguous")
    await factories.make_variant(conn, product_id=product_id, sku="AMBIG-1", price=100_000, stock_on_hand=1)
    product_id_2 = await factories.make_product(conn, brand_id=brand_id, name="Malibu Ambiguous XL")
    await factories.make_variant(conn, product_id=product_id_2, sku="AMBIG-2", price=100_000, stock_on_hand=1)

    with pytest.raises(resolver.AmbiguousReference):
        await resolver.resolve_variant_by_name(conn, query="Malibu Ambiguous")


async def test_unrecognized_product_reference_is_not_found(conn, clean_slate):
    with pytest.raises(resolver.ProductNotFound):
        await resolver.resolve_variant_by_name(conn, query="Nonexistent Product XYZ")


async def test_get_stock_is_read_only_and_needs_no_confirmation(conn, clean_slate):
    admin_id = await factories.make_user(conn, role="ADMIN")
    _product_id, variant_id = await _make_stocked_product(conn, name="Malibu ReadOnly", stock=7)

    outcome = await drafts_service.handle_command(
        conn, actor=_actor(admin_id, "ADMIN"), command_type="GET_STOCK",
        raw_payload={"variant_id": variant_id}, source="TEXT",
    )
    assert outcome["executed"] is True
    assert outcome["result"]["available"] == 7


async def test_admin_without_finance_view_cannot_set_cost_price_via_ai(conn, clean_slate):
    admin_id = await factories.make_user(conn, role="ADMIN")
    brand_id = await factories.make_brand(conn, name="NoFinanceBrand")

    with pytest.raises(drafts_service.Forbidden):
        await drafts_service.handle_command(
            conn, actor=_actor(admin_id, "ADMIN"), command_type="CREATE_PRODUCT",
            raw_payload={
                "name": "Cost Gated Product", "brand_id": brand_id, "price": 100_000,
                "initial_stock": 1, "cost_price": 50_000,
            },
            source="TEXT",
        )


async def test_owner_can_create_product_with_cost_price_and_it_requires_confirmation(conn, clean_slate):
    owner = await conn.fetchrow("SELECT id FROM users WHERE role = 'OWNER' LIMIT 1")
    brand_id = await factories.make_brand(conn, name="OwnerCostBrand")

    outcome = await drafts_service.handle_command(
        conn, actor=_actor(owner["id"], "OWNER"), command_type="CREATE_PRODUCT",
        raw_payload={
            "name": "Owner Cost Product", "brand_id": brand_id, "price": 100_000,
            "initial_stock": 2, "cost_price": 40_000,
        },
        source="TEXT",
    )
    assert outcome["executed"] is False  # mutation -> draft, not immediate

    confirmed = await drafts_service.confirm(
        conn, draft_id=outcome["draft_id"], confirmation_token=outcome["confirmation_token"], actor=_actor(owner["id"], "OWNER"),
    )
    product = await conn.fetchrow("SELECT id, name FROM products WHERE id = $1", confirmed["result"]["entity_id"])
    assert product["name"] == "Owner Cost Product"
    variant = await conn.fetchrow(
        "SELECT cost_price, stock_on_hand FROM product_variants WHERE id = $1", confirmed["result"]["variant_id"]
    )
    assert variant["cost_price"] == 40_000
    assert variant["stock_on_hand"] == 2


async def test_concurrent_duplicate_confirm_only_one_succeeds(pool, clean_slate):
    async with pool.acquire() as setup_conn:
        admin_id = await factories.make_user(setup_conn, role="ADMIN")
        await _make_stocked_product(setup_conn, name="Malibu Concurrent", stock=1)
        outcome = await _draft_for_stock_command(setup_conn, admin_id, "Malibu Concurrent + 1")

    async def attempt():
        async with pool.acquire() as conn:
            try:
                await drafts_service.confirm(
                    conn, draft_id=outcome["draft_id"], confirmation_token=outcome["confirmation_token"],
                    actor=_actor(admin_id, "ADMIN"),
                )
                return "success"
            except drafts_service.DraftNotPending:
                return "already_pending_error"

    results = await asyncio.gather(attempt(), attempt())
    assert results.count("success") == 1
    assert results.count("already_pending_error") == 1


# --- §P2-2 UPDATE_PRODUCT ------------------------------------------------


async def _draft_for_update_product_command(conn, admin_id: int, text: str, role: str = "ADMIN"):
    result = await StubAIProvider().generate_structured_command(text=text)
    payload = await resolve_command_references(conn, result.command_type, result.payload)
    outcome = await drafts_service.handle_command(
        conn, actor=_actor(admin_id, role), command_type=result.command_type, raw_payload=payload, source="TEXT",
    )
    return outcome


async def test_update_product_name_valid_end_to_end(conn, clean_slate):
    admin_id = await factories.make_user(conn, role="ADMIN")
    product_id, _variant_id = await _make_stocked_product(conn, name="Malibu UP One", stock=1)

    outcome = await _draft_for_update_product_command(conn, admin_id, "Malibu UP One nomini Malibu UP One Premium qil")
    assert outcome["executed"] is False  # mutation -> draft, never immediate

    confirmed = await drafts_service.confirm(
        conn, draft_id=outcome["draft_id"], confirmation_token=outcome["confirmation_token"], actor=_actor(admin_id, "ADMIN"),
    )
    assert confirmed["result"]["product"]["name"] == "Malibu UP One Premium"

    row = await conn.fetchrow("SELECT name FROM products WHERE id = $1", product_id)
    assert row["name"] == "Malibu UP One Premium"


async def test_update_product_material_applies_to_single_variant(conn, clean_slate):
    admin_id = await factories.make_user(conn, role="ADMIN")
    _product_id, variant_id = await _make_stocked_product(conn, name="Malibu UP Material", stock=1)

    outcome = await _draft_for_update_product_command(conn, admin_id, "Malibu UP Material materialini koja qil")
    await drafts_service.confirm(
        conn, draft_id=outcome["draft_id"], confirmation_token=outcome["confirmation_token"], actor=_actor(admin_id, "ADMIN"),
    )

    row = await conn.fetchrow("SELECT material FROM product_variants WHERE id = $1", variant_id)
    assert row["material"] == "koja"


async def test_update_product_type_valid(conn, clean_slate):
    admin_id = await factories.make_user(conn, role="ADMIN")
    product_id, _variant_id = await _make_stocked_product(conn, name="Malibu UP Type", stock=1)

    outcome = await _draft_for_update_product_command(conn, admin_id, "Malibu UP Type turini sidena chexoli qil")
    await drafts_service.confirm(
        conn, draft_id=outcome["draft_id"], confirmation_token=outcome["confirmation_token"], actor=_actor(admin_id, "ADMIN"),
    )

    row = await conn.fetchrow("SELECT product_type FROM products WHERE id = $1", product_id)
    assert row["product_type"] == "SIDENA_COVER"


async def test_update_product_invalid_product_type_rejected_at_draft_creation(conn, clean_slate):
    admin_id = await factories.make_user(conn, role="ADMIN")
    await _make_stocked_product(conn, name="Malibu UP BadType", stock=1)

    from app.ai.commands import InvalidPayload

    with pytest.raises(InvalidPayload):
        await drafts_service.handle_command(
            conn, actor=_actor(admin_id, "ADMIN"), command_type="UPDATE_PRODUCT",
            raw_payload={"product_id": 999999, "product_type": "GILAMCHA"}, source="TEXT",
        )


async def test_update_product_missing_product_reports_not_found(conn, clean_slate):
    admin_id = await factories.make_user(conn, role="ADMIN")

    with pytest.raises(resolver.ProductNotFound):
        await resolver.resolve_product_by_name(conn, query="Product That Does Not Exist Anywhere")


async def test_update_product_unauthorized_user_rejected(conn, clean_slate):
    user_id = await factories.make_user(conn, role="USER")
    await _make_stocked_product(conn, name="Malibu UP Unauth", stock=1)

    with pytest.raises(drafts_service.Forbidden):
        await drafts_service.handle_command(
            conn, actor=_actor(user_id, "USER"), command_type="UPDATE_PRODUCT",
            raw_payload={"product_id": 1, "name": "Hijacked"}, source="TEXT",
        )


async def test_update_product_admin_allowed(conn, clean_slate):
    admin_id = await factories.make_user(conn, role="ADMIN")
    product_id, _variant_id = await _make_stocked_product(conn, name="Malibu UP Admin", stock=1)

    outcome = await drafts_service.handle_command(
        conn, actor=_actor(admin_id, "ADMIN"), command_type="UPDATE_PRODUCT",
        raw_payload={"product_id": product_id, "description": "Admin edited this"}, source="TEXT",
    )
    assert outcome["executed"] is False  # draft created, not rejected


async def test_update_product_owner_allowed(conn, clean_slate):
    owner = await conn.fetchrow("SELECT id FROM users WHERE role = 'OWNER' LIMIT 1")
    product_id, _variant_id = await _make_stocked_product(conn, name="Malibu UP Owner", stock=1)

    outcome = await drafts_service.handle_command(
        conn, actor=_actor(owner["id"], "OWNER"), command_type="UPDATE_PRODUCT",
        raw_payload={"product_id": product_id, "description": "Owner edited this"}, source="TEXT",
    )
    assert outcome["executed"] is False


async def test_update_product_cost_price_not_accepted_by_schema(conn, clean_slate):
    """§P2-2: cost price can never move through this command — the schema
    itself has no such field (test_ai_commands.py asserts this statically);
    here a payload that tries to sneak one in is simply ignored by pydantic
    (extra fields dropped), not silently applied."""
    admin_id = await factories.make_user(conn, role="ADMIN")
    product_id, variant_id = await _make_stocked_product(conn, name="Malibu UP CostPrice", stock=1)

    outcome = await drafts_service.handle_command(
        conn, actor=_actor(admin_id, "ADMIN"), command_type="UPDATE_PRODUCT",
        raw_payload={"product_id": product_id, "name": "Renamed", "cost_price": 999_999}, source="TEXT",
    )
    await drafts_service.confirm(
        conn, draft_id=outcome["draft_id"], confirmation_token=outcome["confirmation_token"], actor=_actor(admin_id, "ADMIN"),
    )
    row = await conn.fetchrow("SELECT cost_price FROM product_variants WHERE id = $1", variant_id)
    assert row["cost_price"] is None  # never set through UPDATE_PRODUCT


async def test_update_product_confirmation_required_not_immediate(conn, clean_slate):
    admin_id = await factories.make_user(conn, role="ADMIN")
    product_id, _variant_id = await _make_stocked_product(conn, name="Malibu UP Confirm", stock=1)

    outcome = await drafts_service.handle_command(
        conn, actor=_actor(admin_id, "ADMIN"), command_type="UPDATE_PRODUCT",
        raw_payload={"product_id": product_id, "name": "Should Not Apply Yet"}, source="TEXT",
    )
    assert outcome["executed"] is False

    row = await conn.fetchrow("SELECT name FROM products WHERE id = $1", product_id)
    assert row["name"] == "Malibu UP Confirm"  # unchanged until confirmed


async def test_update_product_replay_rejected(conn, clean_slate):
    admin_id = await factories.make_user(conn, role="ADMIN")
    product_id, _variant_id = await _make_stocked_product(conn, name="Malibu UP Replay", stock=1)

    outcome = await drafts_service.handle_command(
        conn, actor=_actor(admin_id, "ADMIN"), command_type="UPDATE_PRODUCT",
        raw_payload={"product_id": product_id, "name": "Replay Once"}, source="TEXT",
    )
    await drafts_service.confirm(
        conn, draft_id=outcome["draft_id"], confirmation_token=outcome["confirmation_token"], actor=_actor(admin_id, "ADMIN"),
    )
    with pytest.raises(drafts_service.DraftNotPending):
        await drafts_service.confirm(
            conn, draft_id=outcome["draft_id"], confirmation_token=outcome["confirmation_token"], actor=_actor(admin_id, "ADMIN"),
        )


async def test_update_product_concurrent_confirmation_safe(pool, clean_slate):
    async with pool.acquire() as setup_conn:
        admin_id = await factories.make_user(setup_conn, role="ADMIN")
        product_id, _variant_id = await _make_stocked_product(setup_conn, name="Malibu UP Race", stock=1)
        outcome = await drafts_service.handle_command(
            setup_conn, actor=_actor(admin_id, "ADMIN"), command_type="UPDATE_PRODUCT",
            raw_payload={"product_id": product_id, "name": "Raced Name"}, source="TEXT",
        )

    async def attempt():
        async with pool.acquire() as conn:
            try:
                await drafts_service.confirm(
                    conn, draft_id=outcome["draft_id"], confirmation_token=outcome["confirmation_token"],
                    actor=_actor(admin_id, "ADMIN"),
                )
                return "success"
            except drafts_service.DraftNotPending:
                return "already_pending"

    results = await asyncio.gather(attempt(), attempt())
    assert results.count("success") == 1
    assert results.count("already_pending") == 1
