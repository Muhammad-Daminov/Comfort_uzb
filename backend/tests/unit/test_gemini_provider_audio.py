"""§P5.1: mocked HTTP tests proving AudioInput -> Gemini REST request for
GeminiAIProvider. Mirrors test_gemini_provider.py's mocking style; no real
GEMINI_API_KEY needed.
"""
from __future__ import annotations

import base64

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.ai.audio import AudioInput
from app.ai.providers.base import ProviderNotConfigured
from app.ai.providers.gemini_provider import GeminiAIProvider

pytestmark = pytest.mark.asyncio

_VALID_OGG = b"OggS" + b"\x00" * 64


def _audio() -> AudioInput:
    return AudioInput.from_bytes(_VALID_OGG, mime_type_hint="audio/ogg")


def _mock_client(response=None, side_effect=None):
    client = AsyncMock()
    if side_effect is not None:
        client.post = AsyncMock(side_effect=side_effect)
    else:
        client.post = AsyncMock(return_value=response)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


def _function_call_response(args: dict) -> MagicMock:
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json = MagicMock(
        return_value={
            "candidates": [
                {"content": {"parts": [{"functionCall": {"name": "emit_structured_command", "args": args}}]}}
            ]
        }
    )
    return response


async def _capture(response):
    captured = {}

    async def _capture_post(url, headers=None, json=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        return response

    client = AsyncMock()
    client.post = AsyncMock(side_effect=_capture_post)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx, captured


async def test_audio_only_request_sends_correct_inline_data_part():
    response = _function_call_response(
        {"command_type": "INCREASE_STOCK", "fields": {"product_query": "Malibu 2", "delta": 1}, "needs_clarification": False}
    )
    ctx, captured = await _capture(response)
    audio = _audio()

    with patch("httpx.AsyncClient", return_value=ctx):
        provider = GeminiAIProvider(api_key="test-key")
        result = await provider.generate_structured_command(audio=audio)

    parts = captured["json"]["contents"][0]["parts"]
    assert len(parts) == 1
    assert parts[0]["inlineData"]["mimeType"] == "audio/ogg"
    assert base64.b64decode(parts[0]["inlineData"]["data"]) == _VALID_OGG
    assert result.command_type == "INCREASE_STOCK"


async def test_text_and_audio_combined_sends_both_parts():
    response = _function_call_response({"command_type": "UNKNOWN", "fields": {}, "needs_clarification": False})
    ctx, captured = await _capture(response)
    audio = _audio()

    with patch("httpx.AsyncClient", return_value=ctx):
        provider = GeminiAIProvider(api_key="test-key")
        await provider.generate_structured_command(text="Shuni mahsulotga qo'sh", audio=audio)

    parts = captured["json"]["contents"][0]["parts"]
    assert {"text": "Shuni mahsulotga qo'sh"} in parts
    assert any("inlineData" in p for p in parts)
    assert len(parts) == 2


async def test_system_instruction_is_preserved_for_audio_requests():
    response = _function_call_response({"command_type": "UNKNOWN", "fields": {}, "needs_clarification": False})
    ctx, captured = await _capture(response)

    with patch("httpx.AsyncClient", return_value=ctx):
        provider = GeminiAIProvider(api_key="test-key")
        await provider.generate_structured_command(audio=_audio())

    from app.ai.providers.gemini_provider import _SYSTEM_PROMPT

    assert captured["json"]["system_instruction"]["parts"][0]["text"] == _SYSTEM_PROMPT


async def test_structured_output_schema_is_preserved_for_audio_requests():
    response = _function_call_response({"command_type": "UNKNOWN", "fields": {}, "needs_clarification": False})
    ctx, captured = await _capture(response)

    with patch("httpx.AsyncClient", return_value=ctx):
        provider = GeminiAIProvider(api_key="test-key")
        await provider.generate_structured_command(audio=_audio())

    assert captured["json"]["tools"][0]["function_declarations"][0]["name"] == "emit_structured_command"
    assert captured["json"]["tool_config"]["function_calling_config"]["mode"] == "ANY"


async def test_api_key_sent_only_via_header_never_in_body_for_audio_requests():
    response = _function_call_response({"command_type": "UNKNOWN", "fields": {}, "needs_clarification": False})
    ctx, captured = await _capture(response)

    with patch("httpx.AsyncClient", return_value=ctx):
        provider = GeminiAIProvider(api_key="super-secret-audio-key")
        await provider.generate_structured_command(audio=_audio())

    assert captured["headers"]["x-goog-api-key"] == "super-secret-audio-key"
    assert "super-secret-audio-key" not in str(captured["json"])


async def test_audio_produces_valid_structured_command_result():
    response = _function_call_response(
        {"command_type": "GET_STOCK", "fields": {"product_query": "Malibu 2"}, "needs_clarification": False}
    )
    with patch("httpx.AsyncClient", return_value=_mock_client(response=response)):
        provider = GeminiAIProvider(api_key="test-key")
        result = await provider.generate_structured_command(audio=_audio())

    assert result.command_type == "GET_STOCK"
    assert result.payload == {"product_query": "Malibu 2"}
    assert result.raw_text == ""  # no text was given — never fabricated


async def test_audio_ambiguity_is_flagged_not_guessed():
    response = _function_call_response(
        {
            "command_type": "UPDATE_PRODUCT",
            "fields": {"product_query": "Malibu"},
            "needs_clarification": True,
            "clarification_reason": "Bir nechta mahsulot 'Malibu' so'ziga mos keladi.",
        }
    )
    with patch("httpx.AsyncClient", return_value=_mock_client(response=response)):
        provider = GeminiAIProvider(api_key="test-key")
        result = await provider.generate_structured_command(audio=_audio())

    assert result.command_type is None
    assert result.clarification_required is True


async def test_no_text_and_no_audio_never_calls_the_api():
    client = AsyncMock()
    client.post = AsyncMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=ctx):
        provider = GeminiAIProvider(api_key="test-key")
        result = await provider.generate_structured_command()

    client.post.assert_not_awaited()
    assert result.command_type is None


async def test_malformed_response_rejected_safely_for_audio_requests():
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json = MagicMock(side_effect=ValueError("not JSON"))
    with patch("httpx.AsyncClient", return_value=_mock_client(response=response)):
        provider = GeminiAIProvider(api_key="test-key")
        with pytest.raises(ProviderNotConfigured, match="malformed response"):
            await provider.generate_structured_command(audio=_audio())


async def test_rate_limit_handled_correctly_for_audio_requests():
    response = MagicMock()
    response.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError("429", request=MagicMock(), response=MagicMock(status_code=429))
    )
    with patch("httpx.AsyncClient", return_value=_mock_client(response=response)):
        provider = GeminiAIProvider(api_key="test-key")
        with pytest.raises(ProviderNotConfigured, match="API call failed"):
            await provider.generate_structured_command(audio=_audio())


async def test_server_error_handled_correctly_for_audio_requests():
    response = MagicMock()
    response.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError("503", request=MagicMock(), response=MagicMock(status_code=503))
    )
    with patch("httpx.AsyncClient", return_value=_mock_client(response=response)):
        provider = GeminiAIProvider(api_key="test-key")
        with pytest.raises(ProviderNotConfigured, match="API call failed"):
            await provider.generate_structured_command(audio=_audio())


async def test_timeout_handled_correctly_for_audio_requests():
    with patch("httpx.AsyncClient", return_value=_mock_client(side_effect=httpx.TimeoutException("timed out"))):
        provider = GeminiAIProvider(api_key="test-key")
        with pytest.raises(ProviderNotConfigured, match="API call failed"):
            await provider.generate_structured_command(audio=_audio())


async def test_audio_bytes_never_appear_in_log_calls(caplog):
    """Raw audio bytes must never be passed to the logger — only the
    request itself (to Google directly) carries them."""
    response = _function_call_response({"command_type": "UNKNOWN", "fields": {}, "needs_clarification": False})
    with patch("httpx.AsyncClient", return_value=_mock_client(response=response)):
        provider = GeminiAIProvider(api_key="test-key")
        await provider.generate_structured_command(audio=_audio())

    for record in caplog.records:
        assert "OggS" not in record.getMessage()
