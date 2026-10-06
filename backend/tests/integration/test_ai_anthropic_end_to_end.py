"""§P4.1: the real Anthropic provider's output driven through the actual
production pipeline against a live DB — resolver -> drafts_service ->
executor -> domain service -> DB. httpx is mocked only at the Anthropic
HTTP boundary (no real ANTHROPIC_API_KEY needed); everything after that
line is the real code path, identical to what a genuine API response would
trigger. This is the integration-level counterpart to
tests/unit/test_anthropic_provider.py (interpretation only) and
tests/integration/test_ai_drafts_workflow.py (same pipeline, stub
provider) — proving the two compose correctly together.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ai import resolver
from app.ai.commands import UpdateProductPayload
from app.ai.drafts import service as drafts_service
from app.ai.providers.anthropic_provider import AnthropicAIProvider
from app.ai.resolver import resolve_command_references
from app.security.permissions import CurrentUser
from tests.integration import factories

pytestmark = pytest.mark.asyncio


def _actor(user_id: int, role: str) -> CurrentUser:
    return CurrentUser(id=user_id, telegram_id=user_id, role=role, status="ACTIVE")


def _mock_client(tool_input: dict):
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json = MagicMock(
        return_value={"content": [{"type": "tool_use", "name": "emit_structured_command", "input": tool_input}]}
    )
    client = AsyncMock()
    client.post = AsyncMock(return_value=response)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


async def _make_product(conn, *, name: str):
    brand_id = await factories.make_brand(conn, name=f"{name} Brand")
    product_id = await factories.make_product(conn, brand_id=brand_id, name=name)
    variant_id = await factories.make_variant(
        conn, product_id=product_id, sku=f"{name.upper().replace(' ', '')}-SKU", price=500_000, stock_on_hand=3
    )
    return product_id, variant_id


async def test_real_provider_response_creates_draft_not_immediate_mutation(conn, clean_slate):
    admin_id = await factories.make_user(conn, role="ADMIN")
    product_id, _variant_id = await _make_product(conn, name="Anthropic Malibu One")

    tool_input = {
        "command_type": "UPDATE_PRODUCT",
        "fields": {"product_query": "Anthropic Malibu One", "name": "Anthropic Malibu One Premium"},
        "needs_clarification": False,
    }
    with patch("httpx.AsyncClient", return_value=_mock_client(tool_input)):
        result = await AnthropicAIProvider(api_key="test-key").generate_structured_command(
            text="Anthropic Malibu One nomini Anthropic Malibu One Premium qil"
        )

    payload = await resolve_command_references(conn, result.command_type, result.payload)
    outcome = await drafts_service.handle_command(
        conn, actor=_actor(admin_id, "ADMIN"), command_type=result.command_type, raw_payload=payload, source="TEXT",
    )

    assert outcome["executed"] is False
    assert "draft_id" in outcome
    # Nothing written yet — the draft alone must never mutate the product.
    row = await conn.fetchrow("SELECT name FROM products WHERE id = $1", product_id)
    assert row["name"] == "Anthropic Malibu One"


async def test_confirm_after_real_provider_draft_executes_the_real_domain_service(conn, clean_slate):
    admin_id = await factories.make_user(conn, role="ADMIN")
    product_id, _variant_id = await _make_product(conn, name="Anthropic Malibu Two")

    tool_input = {
        "command_type": "UPDATE_PRODUCT",
        "fields": {"product_query": "Anthropic Malibu Two", "name": "Anthropic Malibu Two Premium"},
        "needs_clarification": False,
    }
    with patch("httpx.AsyncClient", return_value=_mock_client(tool_input)):
        result = await AnthropicAIProvider(api_key="test-key").generate_structured_command(
            text="Anthropic Malibu Two nomini Anthropic Malibu Two Premium qil"
        )
    payload = await resolve_command_references(conn, result.command_type, result.payload)
    outcome = await drafts_service.handle_command(
        conn, actor=_actor(admin_id, "ADMIN"), command_type=result.command_type, raw_payload=payload, source="TEXT",
    )

    confirmed = await drafts_service.confirm(
        conn, draft_id=outcome["draft_id"], confirmation_token=outcome["confirmation_token"], actor=_actor(admin_id, "ADMIN"),
    )
    assert confirmed["result"]["entity_id"] == product_id

    row = await conn.fetchrow("SELECT name FROM products WHERE id = $1", product_id)
    assert row["name"] == "Anthropic Malibu Two Premium"


async def test_user_role_cannot_issue_command_from_real_provider_response(conn, clean_slate):
    user_id = await factories.make_user(conn, role="USER")
    await _make_product(conn, name="Anthropic Malibu Three")

    tool_input = {
        "command_type": "UPDATE_PRODUCT",
        "fields": {"product_query": "Anthropic Malibu Three", "name": "Hacked"},
        "needs_clarification": False,
    }
    with patch("httpx.AsyncClient", return_value=_mock_client(tool_input)):
        result = await AnthropicAIProvider(api_key="test-key").generate_structured_command(text="irrelevant")
    payload = await resolve_command_references(conn, result.command_type, result.payload)

    with pytest.raises(drafts_service.Forbidden):
        await drafts_service.handle_command(
            conn, actor=_actor(user_id, "USER"), command_type=result.command_type, raw_payload=payload, source="TEXT",
        )


async def test_owner_can_confirm_a_real_provider_draft(conn, clean_slate):
    owner_row = await conn.fetchrow("SELECT id FROM users WHERE role = 'OWNER' AND deleted_at IS NULL")
    owner_id = owner_row["id"]
    product_id, _variant_id = await _make_product(conn, name="Anthropic Malibu Four")

    tool_input = {
        "command_type": "UPDATE_PRODUCT",
        "fields": {"product_query": "Anthropic Malibu Four", "material": "koja"},
        "needs_clarification": False,
    }
    with patch("httpx.AsyncClient", return_value=_mock_client(tool_input)):
        result = await AnthropicAIProvider(api_key="test-key").generate_structured_command(text="irrelevant")
    payload = await resolve_command_references(conn, result.command_type, result.payload)
    outcome = await drafts_service.handle_command(
        conn, actor=_actor(owner_id, "OWNER"), command_type=result.command_type, raw_payload=payload, source="TEXT",
    )
    confirmed = await drafts_service.confirm(
        conn, draft_id=outcome["draft_id"], confirmation_token=outcome["confirmation_token"], actor=_actor(owner_id, "OWNER"),
    )
    assert confirmed["result"]["material"] == "koja"


async def test_replay_protection_still_holds_for_real_provider_drafts(conn, clean_slate):
    admin_id = await factories.make_user(conn, role="ADMIN")
    await _make_product(conn, name="Anthropic Malibu Five")

    tool_input = {
        "command_type": "UPDATE_PRODUCT",
        "fields": {"product_query": "Anthropic Malibu Five", "name": "Anthropic Malibu Five Renamed"},
        "needs_clarification": False,
    }
    with patch("httpx.AsyncClient", return_value=_mock_client(tool_input)):
        result = await AnthropicAIProvider(api_key="test-key").generate_structured_command(text="irrelevant")
    payload = await resolve_command_references(conn, result.command_type, result.payload)
    outcome = await drafts_service.handle_command(
        conn, actor=_actor(admin_id, "ADMIN"), command_type=result.command_type, raw_payload=payload, source="TEXT",
    )

    await drafts_service.confirm(
        conn, draft_id=outcome["draft_id"], confirmation_token=outcome["confirmation_token"], actor=_actor(admin_id, "ADMIN"),
    )
    with pytest.raises(drafts_service.DraftNotPending):
        await drafts_service.confirm(
            conn, draft_id=outcome["draft_id"], confirmation_token=outcome["confirmation_token"], actor=_actor(admin_id, "ADMIN"),
        )


async def test_model_trying_to_set_cost_price_through_update_product_is_dropped_before_db(conn, clean_slate):
    """§10/§11: even if the model misbehaves and includes a field
    UPDATE_PRODUCT's schema does not define, pydantic's default
    extra-field-ignoring behavior drops it before it ever reaches the
    executor or the database — proven here through the real provider's
    parsing path, not just at the commands.py unit level (already covered
    by test_ai_commands.py from P2-2)."""
    admin_id = await factories.make_user(conn, role="ADMIN")
    product_id, variant_id = await _make_product(conn, name="Anthropic Malibu Six")

    tool_input = {
        "command_type": "UPDATE_PRODUCT",
        # A misbehaving/attacked model response — cost_price is not part of
        # UpdateProductPayload at all.
        "fields": {"product_query": "Anthropic Malibu Six", "name": "Anthropic Malibu Six V2", "cost_price": 1},
        "needs_clarification": False,
    }
    with patch("httpx.AsyncClient", return_value=_mock_client(tool_input)):
        result = await AnthropicAIProvider(api_key="test-key").generate_structured_command(text="set cost price to 1")
    payload = await resolve_command_references(conn, result.command_type, result.payload)
    assert "cost_price" not in UpdateProductPayload.model_fields

    outcome = await drafts_service.handle_command(
        conn, actor=_actor(admin_id, "ADMIN"), command_type=result.command_type, raw_payload=payload, source="TEXT",
    )
    await drafts_service.confirm(
        conn, draft_id=outcome["draft_id"], confirmation_token=outcome["confirmation_token"], actor=_actor(admin_id, "ADMIN"),
    )

    variant_row = await conn.fetchrow("SELECT cost_price FROM product_variants WHERE id = $1", variant_id)
    assert variant_row["cost_price"] is None


async def test_ambiguous_wording_flagged_by_model_never_reaches_draft_creation(conn, clean_slate):
    admin_id = await factories.make_user(conn, role="ADMIN")

    tool_input = {
        "command_type": "UPDATE_PRODUCT",
        "fields": {"product_query": "BMW", "color_query": "qora"},
        "needs_clarification": True,
        "clarification_reason": "Bir nechta mahsulot mos keladi.",
    }
    with patch("httpx.AsyncClient", return_value=_mock_client(tool_input)):
        result = await AnthropicAIProvider(api_key="test-key").generate_structured_command(text="BMW qora")

    assert result.command_type is None
    assert result.clarification_required is True
    # Never even attempts resolver/draft creation — nothing to resolve
    # against a real product without a command_type.


async def test_provider_has_no_database_connection_parameter() -> None:
    """Structural guarantee (§1/§2 of the brief): the provider's public
    interface cannot be handed a DB connection — it physically cannot query
    or mutate anything itself."""
    import inspect

    sig = inspect.signature(AnthropicAIProvider.generate_structured_command)
    assert "conn" not in sig.parameters
    assert "connection" not in sig.parameters
    assert "pool" not in sig.parameters
