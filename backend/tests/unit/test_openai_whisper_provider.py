"""§20 of the v2 rebuild brief: STT failures (timeout, HTTP error, malformed
response, empty transcription) must surface as an actionable
`ProviderNotConfigured`, never crash the caller. No real OPENAI_API_KEY is
used — httpx.AsyncClient is mocked, matching the brief's "do not require a
real API key for unit tests" instruction."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.ai.providers.base import ProviderNotConfigured
from app.ai.providers.openai_whisper import OpenAIWhisperSTTProvider

pytestmark = pytest.mark.asyncio


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


async def test_successful_transcription():
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json = MagicMock(return_value={"text": "Malibu 2 plus 1"})
    with patch("httpx.AsyncClient", return_value=_mock_client(response=response)):
        provider = OpenAIWhisperSTTProvider(api_key="test-key")
        text = await provider.transcribe(audio_bytes=b"fake-ogg-bytes", mime_type="audio/ogg")
    assert text == "Malibu 2 plus 1"


async def test_empty_transcription_raises_provider_not_configured():
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json = MagicMock(return_value={"text": ""})
    with patch("httpx.AsyncClient", return_value=_mock_client(response=response)):
        provider = OpenAIWhisperSTTProvider(api_key="test-key")
        with pytest.raises(ProviderNotConfigured, match="no transcript text"):
            await provider.transcribe(audio_bytes=b"x", mime_type="audio/ogg")


async def test_timeout_raises_provider_not_configured():
    with patch("httpx.AsyncClient", return_value=_mock_client(side_effect=httpx.TimeoutException("timed out"))):
        provider = OpenAIWhisperSTTProvider(api_key="test-key")
        with pytest.raises(ProviderNotConfigured, match="API call failed"):
            await provider.transcribe(audio_bytes=b"x", mime_type="audio/ogg")


async def test_http_error_status_raises_provider_not_configured():
    response = MagicMock()
    response.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError("401", request=MagicMock(), response=MagicMock(status_code=401))
    )
    with patch("httpx.AsyncClient", return_value=_mock_client(response=response)):
        provider = OpenAIWhisperSTTProvider(api_key="bad-key")
        with pytest.raises(ProviderNotConfigured, match="API call failed"):
            await provider.transcribe(audio_bytes=b"x", mime_type="audio/ogg")


async def test_malformed_json_response_raises_provider_not_configured():
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json = MagicMock(side_effect=ValueError("not JSON"))
    with patch("httpx.AsyncClient", return_value=_mock_client(response=response)):
        provider = OpenAIWhisperSTTProvider(api_key="test-key")
        with pytest.raises(ProviderNotConfigured, match="malformed response"):
            await provider.transcribe(audio_bytes=b"x", mime_type="audio/ogg")


async def test_unexpected_response_shape_raises_provider_not_configured():
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json = MagicMock(return_value=["not", "a", "dict"])
    with patch("httpx.AsyncClient", return_value=_mock_client(response=response)):
        provider = OpenAIWhisperSTTProvider(api_key="test-key")
        with pytest.raises(ProviderNotConfigured, match="no transcript text"):
            await provider.transcribe(audio_bytes=b"x", mime_type="audio/ogg")
