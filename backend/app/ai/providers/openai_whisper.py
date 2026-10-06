"""Real OpenAI Whisper (`/v1/audio/transcriptions`) adapter — implemented
against the publicly documented endpoint shape, NOT LIVE-VERIFIED in this
environment: no OPENAI_API_KEY was available during this implementation
pass (docs/13_V2_REBUILD_AUDIT.md §5). Verify against a real key before
production use.
"""
from __future__ import annotations

import httpx

from app.ai.providers.base import ProviderNotConfigured

_API_URL = "https://api.openai.com/v1/audio/transcriptions"
_DEFAULT_MODEL = "whisper-1"


class OpenAIWhisperSTTProvider:
    name = "openai_whisper"

    def __init__(self, api_key: str, model: str = _DEFAULT_MODEL) -> None:
        self._api_key = api_key
        self._model = model

    async def transcribe(self, *, audio_bytes: bytes, mime_type: str) -> str:
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    _API_URL,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    data={"model": self._model},
                    files={"file": ("voice.ogg", audio_bytes, mime_type)},
                )
            response.raise_for_status()
            body = response.json()
        except httpx.HTTPError as exc:
            raise ProviderNotConfigured(f"OpenAI Whisper API call failed: {exc}") from exc
        except ValueError as exc:  # response.json() on a non-JSON/malformed body
            raise ProviderNotConfigured(f"OpenAI Whisper returned a malformed response: {exc}") from exc

        text = body.get("text") if isinstance(body, dict) else None
        if not text:
            raise ProviderNotConfigured("OpenAI Whisper returned no transcript text")
        return text
