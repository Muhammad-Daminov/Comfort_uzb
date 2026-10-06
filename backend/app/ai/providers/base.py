"""§22 of the v2 rebuild brief: provider abstraction so the application is
never hard-coded to one AI/STT vendor. Nothing outside app/ai/providers/
imports a concrete provider class directly — everything goes through
registry.get_ai_provider()/get_stt_provider().
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from app.ai.audio import AudioInput


class ProviderNotConfigured(Exception):
    """Raised when a provider has no live credentials/verified behavior.
    Never caught-and-faked by a caller — it must surface as an actionable
    'unverified — no live provider connected' response to the admin."""


@dataclass(frozen=True)
class StructuredCommandResult:
    command_type: str | None  # None if the provider could not extract a command
    payload: dict = field(default_factory=dict)
    confidence: float = 0.0
    raw_text: str = ""
    # §P4.1: a provider that recognizes the admin is trying to do *something*
    # mutating but cannot safely pin down which product/variant/value is
    # meant sets this instead of guessing — the caller must treat this
    # exactly like `command_type=None` (ask the admin to clarify), never
    # attempt to execute `payload` as-is. Defaults keep every existing
    # provider (stub, STT) and every existing call site unchanged.
    clarification_required: bool = False
    clarification_message: str | None = None


class AIProvider(Protocol):
    name: str

    # §P5.1: `audio` is the new, optional extension point for native
    # voice-command understanding (Telegram voice -> AudioInput -> here),
    # added alongside the pre-existing `image_refs` rather than inventing
    # a parallel "VoiceAIProvider" abstraction — the pipeline downstream
    # of this call (resolver/commands/drafts/executor) is agnostic to
    # which combination of text/audio/image_refs produced the returned
    # `StructuredCommandResult`. `text` became optional in the same change
    # (an audio-only call has no text) — every pre-existing caller still
    # passes `text=...` explicitly, so this is additive, not breaking.
    async def generate_structured_command(
        self, *, text: str | None = None, audio: AudioInput | None = None, image_refs: list[str] | None = None
    ) -> StructuredCommandResult:
        ...

    async def generate_response(self, *, prompt: str, context: dict) -> str:
        ...


class SpeechToTextProvider(Protocol):
    name: str

    async def transcribe(self, *, audio_bytes: bytes, mime_type: str) -> str:
        ...
