"""§P5.2: the complete native-audio voice path driven through the real
production pipeline against a live DB — AudioInput -> GeminiAIProvider
(httpx mocked only at the Gemini HTTP boundary) -> resolver ->
drafts_service -> executor -> DB. This is the voice counterpart to
test_ai_gemini_end_to_end.py (text) and test_ai_anthropic_end_to_end.py —
proving voice converges into the *exact same* unmodified pipeline, not a
parallel one. Covers brief §12 Cases A-G.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ai.audio import AudioInput
from app.ai.commands import UpdateProductPayload
from app.ai.drafts import service as drafts_service
from app.ai.providers.gemini_provider import GeminiAIProvider
from app.ai.resolver import resolve_command_references
from app.security.permissions import CurrentUser
from tests.integration import factories

pytestmark = pytest.mark.asyncio

_VALID_OGG = b"OggS" + b"\x00" * 64


def _actor(user_id: int, role: str) -> CurrentUser:
    return CurrentUser(id=user_id, telegram_id=user_id, role=role, status="ACTIVE")


def _audio() -> AudioInput:
    return AudioInput.from_bytes(_VALID_OGG, mime_type_hint="audio/ogg")


def _mock_client(args: dict):
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json = MagicMock(
        return_value={
            "candidates": [
                {"content": {"parts": [{"functionCall": {"name": "emit_structured_command", "args": args}}]}}
            ]
        }
    )
    client = AsyncMock()
    client.post = AsyncMock(return_value=response)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


async def _make_product(conn, *, name: str, stock: int = 3):
    brand_id = await factories.make_brand(conn, name=f"{name} Brand")
    product_id = await factories.make_product(conn, brand_id=brand_id, name=name)
    variant_id = await factories.make_variant(
        conn, product_id=product_id, sku=f"{name.upper().replace(' ', '')}-SKU", price=500_000, stock_on_hand=stock
    )
    return product_id, variant_id


async def _interpret(args: dict, *, text=None):
    with patch("httpx.AsyncClient", return_value=_mock_client(args)):
        return await GeminiAIProvider(api_key="test-key").generate_structured_command(text=text, audio=_audio())


# ---------------------------------------------------------------------------
# Case A — valid voice command -> draft created, no mutation yet
# ---------------------------------------------------------------------------


async def test_case_a_valid_voice_command_creates_draft_without_mutation(conn, clean_slate):
    admin_id = await factories.make_user(conn, role="ADMIN")
    product_id, _variant_id = await _make_product(conn, name="Voice Malibu A")

    args = {
        "command_type": "UPDATE_PRODUCT",
        "fields": {"product_query": "Voice Malibu A", "name": "Voice Malibu A Premium"},
        "needs_clarification": False,
    }
    result = await _interpret(args)
    payload = await resolve_command_references(conn, result.command_type, result.payload)
    outcome = await drafts_service.handle_command(
        conn, actor=_actor(admin_id, "ADMIN"), command_type=result.command_type, raw_payload=payload, source="VOICE",
    )

    assert outcome["executed"] is False
    assert "draft_id" in outcome
    row = await conn.fetchrow("SELECT name FROM products WHERE id = $1", product_id)
    assert row["name"] == "Voice Malibu A"  # unchanged


# ---------------------------------------------------------------------------
# Case B — confirm -> mutation happens exactly once
# ---------------------------------------------------------------------------


async def test_case_b_confirmation_executes_the_mutation_exactly_once(conn, clean_slate):
    admin_id = await factories.make_user(conn, role="ADMIN")
    product_id, _variant_id = await _make_product(conn, name="Voice Malibu B")

    args = {
        "command_type": "UPDATE_PRODUCT",
        "fields": {"product_query": "Voice Malibu B", "name": "Voice Malibu B Premium"},
        "needs_clarification": False,
    }
    result = await _interpret(args)
    payload = await resolve_command_references(conn, result.command_type, result.payload)
    outcome = await drafts_service.handle_command(
        conn, actor=_actor(admin_id, "ADMIN"), command_type=result.command_type, raw_payload=payload, source="VOICE",
    )

    confirmed = await drafts_service.confirm(
        conn, draft_id=outcome["draft_id"], confirmation_token=outcome["confirmation_token"], actor=_actor(admin_id, "ADMIN"),
    )
    assert confirmed["result"]["entity_id"] == product_id

    row = await conn.fetchrow("SELECT name FROM products WHERE id = $1", product_id)
    assert row["name"] == "Voice Malibu B Premium"


# ---------------------------------------------------------------------------
# Case C — cancellation -> no mutation, no duplicate action
# ---------------------------------------------------------------------------


async def test_case_c_cancellation_leaves_no_mutation_and_cannot_be_confirmed_later(conn, clean_slate):
    admin_id = await factories.make_user(conn, role="ADMIN")
    product_id, _variant_id = await _make_product(conn, name="Voice Malibu C")

    args = {
        "command_type": "UPDATE_PRODUCT",
        "fields": {"product_query": "Voice Malibu C", "name": "Voice Malibu C Premium"},
        "needs_clarification": False,
    }
    result = await _interpret(args)
    payload = await resolve_command_references(conn, result.command_type, result.payload)
    outcome = await drafts_service.handle_command(
        conn, actor=_actor(admin_id, "ADMIN"), command_type=result.command_type, raw_payload=payload, source="VOICE",
    )

    await drafts_service.cancel(conn, draft_id=outcome["draft_id"], actor=_actor(admin_id, "ADMIN"))

    row = await conn.fetchrow("SELECT name FROM products WHERE id = $1", product_id)
    assert row["name"] == "Voice Malibu C"

    with pytest.raises(drafts_service.DraftNotPending):
        await drafts_service.confirm(
            conn, draft_id=outcome["draft_id"], confirmation_token=outcome["confirmation_token"], actor=_actor(admin_id, "ADMIN"),
        )
    row_after = await conn.fetchrow("SELECT name FROM products WHERE id = $1", product_id)
    assert row_after["name"] == "Voice Malibu C"


# ---------------------------------------------------------------------------
# Case D — unrecognized voice -> no draft, no mutation
# ---------------------------------------------------------------------------


async def test_case_d_unrecognized_voice_creates_no_draft(conn, clean_slate):
    args = {"command_type": "UNKNOWN", "fields": {}, "needs_clarification": False}
    result = await _interpret(args)

    assert result.command_type is None
    # Nothing to resolve/draft — the bot handler's own logic (tested in
    # test_ai_voice_native_gemini.py) stops here and never calls the
    # resolver or drafts_service for a None command_type.


# ---------------------------------------------------------------------------
# Case E — unauthorized (USER) voice command -> rejected, no mutation
# ---------------------------------------------------------------------------


async def test_case_e_user_role_cannot_execute_voice_command(conn, clean_slate):
    user_id = await factories.make_user(conn, role="USER")
    product_id, _variant_id = await _make_product(conn, name="Voice Malibu E")

    args = {
        "command_type": "UPDATE_PRODUCT",
        "fields": {"product_query": "Voice Malibu E", "name": "Hacked"},
        "needs_clarification": False,
    }
    result = await _interpret(args)
    payload = await resolve_command_references(conn, result.command_type, result.payload)

    with pytest.raises(drafts_service.Forbidden):
        await drafts_service.handle_command(
            conn, actor=_actor(user_id, "USER"), command_type=result.command_type, raw_payload=payload, source="VOICE",
        )

    row = await conn.fetchrow("SELECT name FROM products WHERE id = $1", product_id)
    assert row["name"] == "Voice Malibu E"


# ---------------------------------------------------------------------------
# Case F — prompt injection in spoken content -> no unauthorized command,
# no mutation
# ---------------------------------------------------------------------------


async def test_case_f_prompt_injection_never_reaches_draft_creation(conn, clean_slate):
    args = {
        "command_type": "UPDATE_PRODUCT",
        "fields": {},
        "needs_clarification": True,
        "clarification_reason": "Bu so'rov mavjud buyruqlarga mos kelmaydi.",
    }
    result = await _interpret(args)

    assert result.command_type is None
    assert result.clarification_required is True
    # Same guarantee as Case D: a None command_type never reaches the
    # resolver or drafts_service.


async def test_case_f_cost_price_injection_via_voice_is_dropped_before_db(conn, clean_slate):
    """A misbehaving/attacked model response smuggling a field
    UPDATE_PRODUCT doesn't define — proven here through the voice/audio
    path specifically (already proven for text in
    test_ai_gemini_end_to_end.py), confirming the same pydantic
    extra-field-ignoring boundary applies regardless of input modality."""
    admin_id = await factories.make_user(conn, role="ADMIN")
    product_id, variant_id = await _make_product(conn, name="Voice Malibu F2")

    args = {
        "command_type": "UPDATE_PRODUCT",
        "fields": {"product_query": "Voice Malibu F2", "name": "Voice Malibu F2 V2", "cost_price": 1},
        "needs_clarification": False,
    }
    result = await _interpret(args)
    payload = await resolve_command_references(conn, result.command_type, result.payload)
    assert "cost_price" not in UpdateProductPayload.model_fields

    outcome = await drafts_service.handle_command(
        conn, actor=_actor(admin_id, "ADMIN"), command_type=result.command_type, raw_payload=payload, source="VOICE",
    )
    await drafts_service.confirm(
        conn, draft_id=outcome["draft_id"], confirmation_token=outcome["confirmation_token"], actor=_actor(admin_id, "ADMIN"),
    )

    variant_row = await conn.fetchrow("SELECT cost_price FROM product_variants WHERE id = $1", variant_id)
    assert variant_row["cost_price"] is None


# ---------------------------------------------------------------------------
# Case G — duplicate confirmation -> executes at most once
# ---------------------------------------------------------------------------


async def test_case_g_duplicate_confirmation_executes_at_most_once(conn, clean_slate):
    admin_id = await factories.make_user(conn, role="ADMIN")
    product_id, variant_id = await _make_product(conn, name="Voice Malibu G", stock=5)

    args = {
        "command_type": "INCREASE_STOCK",
        "fields": {"product_query": "Voice Malibu G", "delta": 1},
        "needs_clarification": False,
    }
    result = await _interpret(args)
    payload = await resolve_command_references(conn, result.command_type, result.payload)
    outcome = await drafts_service.handle_command(
        conn, actor=_actor(admin_id, "ADMIN"), command_type=result.command_type, raw_payload=payload, source="VOICE",
    )

    await drafts_service.confirm(
        conn, draft_id=outcome["draft_id"], confirmation_token=outcome["confirmation_token"], actor=_actor(admin_id, "ADMIN"),
    )
    with pytest.raises(drafts_service.DraftNotPending):
        await drafts_service.confirm(
            conn, draft_id=outcome["draft_id"], confirmation_token=outcome["confirmation_token"], actor=_actor(admin_id, "ADMIN"),
        )

    variant_row = await conn.fetchrow("SELECT stock_on_hand FROM product_variants WHERE id = $1", variant_id)
    assert variant_row["stock_on_hand"] == 6  # +1 applied exactly once, not twice


async def test_provider_has_no_database_connection_parameter_for_audio_calls() -> None:
    """Structural guarantee, mirroring the text-path equivalent: the
    provider's public interface cannot be handed a DB connection."""
    import inspect

    sig = inspect.signature(GeminiAIProvider.generate_structured_command)
    assert "conn" not in sig.parameters
    assert "connection" not in sig.parameters
    assert "pool" not in sig.parameters
