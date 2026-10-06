from __future__ import annotations

from app.ai.providers.base import AIProvider, SpeechToTextProvider
from app.ai.providers.stub import StubAIProvider, StubSpeechToTextProvider
from app.config import Settings


def get_ai_provider(settings: Settings) -> AIProvider:
    if settings.ai_provider == "anthropic":
        from app.ai.providers.anthropic_provider import AnthropicAIProvider
        from app.ai.providers.fallback import FallbackAIProvider

        primary = AnthropicAIProvider(settings.anthropic_api_key)  # type: ignore[arg-type]
        # §P4.1 Part 8: a live-provider failure (timeout/rate-limit/
        # malformed response/outage) falls back to the deterministic
        # parser rather than taking the whole AI assistant down.
        return FallbackAIProvider(primary=primary, fallback=StubAIProvider())
    if settings.ai_provider == "gemini":
        from app.ai.providers.fallback import FallbackAIProvider
        from app.ai.providers.gemini_provider import GeminiAIProvider

        kwargs = {"model": settings.gemini_model} if settings.gemini_model else {}
        primary = GeminiAIProvider(settings.gemini_api_key, **kwargs)  # type: ignore[arg-type]
        return FallbackAIProvider(primary=primary, fallback=StubAIProvider())
    return StubAIProvider()


def get_stt_provider(settings: Settings) -> SpeechToTextProvider:
    if settings.stt_provider == "openai_whisper":
        from app.ai.providers.openai_whisper import OpenAIWhisperSTTProvider

        return OpenAIWhisperSTTProvider(settings.openai_api_key)  # type: ignore[arg-type]
    return StubSpeechToTextProvider()
