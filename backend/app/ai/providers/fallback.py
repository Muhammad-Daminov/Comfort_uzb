"""§P4.1 Part 8: deterministic fallback when the live provider fails
(timeout, rate limit, malformed response, transport error). The stub
parser (`StubAIProvider`) already implements the exact same `AIProvider`
protocol the live provider does, so wrapping rather than reimplementing is
the smallest change that satisfies "never execute a partially parsed
command, and never hard-fail the whole assistant because one HTTP call to
a third party timed out."

This wrapper never raises `ProviderNotConfigured` itself — if the primary
provider fails, it transparently falls back to the deterministic parser,
which can itself only ever return `command_type=None` for text it cannot
parse (never a partial/guessed command). Every existing call site
(app/ai/router.py, bot/handlers/ai.py) already treats `command_type=None`
as "ask the admin to clarify" — no caller-side change was needed for this.
"""
from __future__ import annotations

import logging

from app.ai.providers.base import AIProvider, ProviderNotConfigured, StructuredCommandResult

logger = logging.getLogger(__name__)


class FallbackAIProvider:
    """Wraps a primary provider with a deterministic fallback. `name`
    reflects the primary — audit/log lines should still say "anthropic",
    since the fallback is an implementation detail of resilience, not a
    provider switch the admin asked for."""

    def __init__(self, primary: AIProvider, fallback: AIProvider) -> None:
        self._primary = primary
        self._fallback = fallback
        self.name = primary.name

    async def generate_structured_command(
        self, *, text: str | None = None, audio=None, image_refs: list[str] | None = None
    ) -> StructuredCommandResult:
        try:
            return await self._primary.generate_structured_command(text=text, audio=audio, image_refs=image_refs)
        except ProviderNotConfigured:
            logger.warning("AI provider %r unavailable — falling back to deterministic parser", self._primary.name)
            # §P5.1 §18: the deterministic fallback cannot interpret audio
            # either — StubAIProvider.generate_structured_command already
            # treats an audio-only call exactly like unparseable text
            # (command_type=None), never fabricating a command from audio
            # it cannot understand. Passed through here unchanged, not
            # special-cased.
            return await self._fallback.generate_structured_command(text=text, audio=audio, image_refs=image_refs)

    async def generate_response(self, *, prompt: str, context: dict) -> str:
        try:
            return await self._primary.generate_response(prompt=prompt, context=context)
        except ProviderNotConfigured:
            logger.warning("AI provider %r unavailable — falling back to deterministic parser", self._primary.name)
            return await self._fallback.generate_response(prompt=prompt, context=context)
