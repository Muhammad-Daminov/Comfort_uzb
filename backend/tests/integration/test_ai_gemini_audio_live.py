"""§P5.1 §22: a small, fixed-size live smoke test proving
`AudioInput -> GeminiAIProvider -> StructuredCommandResult` works against
the real Gemini API. No DB mutation; no resolver/drafts/executor
involvement (§23 — P5.1 must not allow Voice -> Gemini -> DB mutation).

Honesty note instead of a fabricated result: this environment has no
speech-synthesis or audio-encoding tool available (checked for `ffmpeg`,
`espeak`/`espeak-ng`, `pico2wave`, `opusenc`, and any Python TTS/audio
package — none installed, no network access assumed for fetching one) to
safely produce a real short Uzbek voice-command recording ("Malibu 2 dan
bitta qo'sh" or similar) as a test fixture. Sending meaningless
noise/silence instead would not actually prove "Gemini understood a voice
command" — it would only prove the HTTP plumbing accepts an inlineData
audio part, which the mocked tests in test_gemini_provider_audio.py
already prove without spending any real API quota. Per the brief's own
instruction ("Do NOT invent successful live test results"), this test is
therefore skipped with an explicit, honest reason rather than faked.

To actually run this test: record or otherwise obtain a short, real OGG/
Opus voice command and set `AI_VOICE_LIVE_FIXTURE` to its filesystem path
(and `GEMINI_API_KEY` to a real key) before running pytest.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.ai.audio import AudioInput
from app.ai.providers.gemini_provider import GeminiAIProvider

_API_KEY = os.environ.get("GEMINI_API_KEY")
_MODEL = os.environ.get("GEMINI_MODEL") or None
_FIXTURE_PATH = os.environ.get("AI_VOICE_LIVE_FIXTURE")

_skip_reason = None
if not _API_KEY:
    _skip_reason = "GEMINI_API_KEY not set — live Gemini audio test skipped"
elif not _FIXTURE_PATH:
    _skip_reason = (
        "AI_VOICE_LIVE_FIXTURE not set and no safe way to synthesize a real voice "
        "command in this environment (no TTS/audio-encoding tool available) — "
        "live Gemini AUDIO smoke test skipped honestly rather than faked with "
        "meaningless noise. See this file's module docstring."
    )
elif not Path(_FIXTURE_PATH).is_file():
    _skip_reason = f"AI_VOICE_LIVE_FIXTURE={_FIXTURE_PATH!r} does not exist"

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(_skip_reason is not None, reason=_skip_reason or "")]


async def test_live_voice_command_interpretation_via_gemini():
    data = Path(_FIXTURE_PATH).read_bytes()  # type: ignore[arg-type]
    audio = AudioInput.from_bytes(data, mime_type_hint="audio/ogg")

    kwargs = {"model": _MODEL} if _MODEL else {}
    provider = GeminiAIProvider(api_key=_API_KEY, **kwargs)  # type: ignore[arg-type]
    result = await provider.generate_structured_command(audio=audio)

    # Only structural assertions — never a DB mutation, never executed
    # against the resolver/drafts/executor pipeline (§23).
    assert result.command_type is None or isinstance(result.command_type, str)
    assert isinstance(result.payload, dict)
    assert not any(k.endswith("_id") for k in result.payload)
