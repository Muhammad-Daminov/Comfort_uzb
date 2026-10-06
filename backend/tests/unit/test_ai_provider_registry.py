"""Provider-selection and config-validation tests for app/ai/providers/
registry.py and app/config.py's AI_PROVIDER/GEMINI_API_KEY handling. No
network calls — only construction/selection logic.
"""
from __future__ import annotations

import pytest

from app.ai.providers.fallback import FallbackAIProvider
from app.ai.providers.gemini_provider import GeminiAIProvider
from app.ai.providers.registry import get_ai_provider
from app.ai.providers.stub import StubAIProvider
from app.config import Settings


def _settings(**overrides) -> Settings:
    base = dict(
        database_url="postgresql://x",
        bot_token="x",
        session_secret="x",
        signing_secret="x",
        uploads_root="/tmp",
        payment_provider="manual_receipt",
        hamyon_api_url=None,
        hamyon_api_key=None,
        hamyon_merchant_id=None,
        hamyon_webhook_secret=None,
        ai_provider=None,
        anthropic_api_key=None,
        gemini_api_key=None,
        gemini_model=None,
        stt_provider=None,
        openai_api_key=None,
        ai_voice_max_bytes=1_000_000,
    )
    base.update(overrides)
    return Settings(**base)


def test_no_ai_provider_configured_returns_stub():
    provider = get_ai_provider(_settings())
    assert isinstance(provider, StubAIProvider)


def test_gemini_provider_selected_when_configured():
    provider = get_ai_provider(_settings(ai_provider="gemini", gemini_api_key="fake-key"))
    assert isinstance(provider, FallbackAIProvider)
    assert provider.name == "gemini"


def test_gemini_provider_falls_back_to_stub_on_failure_wiring():
    provider = get_ai_provider(_settings(ai_provider="gemini", gemini_api_key="fake-key"))
    assert isinstance(provider._fallback, StubAIProvider)  # type: ignore[attr-defined]
    assert isinstance(provider._primary, GeminiAIProvider)  # type: ignore[attr-defined]


def test_gemini_model_is_configurable_through_settings():
    provider = get_ai_provider(_settings(ai_provider="gemini", gemini_api_key="fake-key", gemini_model="gemini-custom"))
    assert provider._primary._model == "gemini-custom"  # type: ignore[attr-defined]


def test_gemini_model_defaults_when_unset():
    from app.ai.providers.gemini_provider import _DEFAULT_MODEL

    provider = get_ai_provider(_settings(ai_provider="gemini", gemini_api_key="fake-key"))
    assert provider._primary._model == _DEFAULT_MODEL  # type: ignore[attr-defined]


def test_anthropic_provider_still_selected_when_configured():
    """Regression: adding Gemini must not disturb the existing Anthropic
    selection path."""
    from app.ai.providers.anthropic_provider import AnthropicAIProvider

    provider = get_ai_provider(_settings(ai_provider="anthropic", anthropic_api_key="fake-key"))
    assert isinstance(provider, FallbackAIProvider)
    assert isinstance(provider._primary, AnthropicAIProvider)  # type: ignore[attr-defined]
    assert provider.name == "anthropic"


def test_ai_provider_gemini_without_key_raises_at_settings_load(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "gemini")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    monkeypatch.setenv("BOT_TOKEN", "x")
    monkeypatch.setenv("SESSION_SECRET", "x")
    monkeypatch.setenv("SIGNING_SECRET", "x")

    with pytest.raises(RuntimeError, match="AI_PROVIDER=gemini requires GEMINI_API_KEY"):
        Settings.from_env()


def test_ai_provider_gemini_with_key_loads_successfully(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-value")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-custom")
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    monkeypatch.setenv("BOT_TOKEN", "x")
    monkeypatch.setenv("SESSION_SECRET", "x")
    monkeypatch.setenv("SIGNING_SECRET", "x")

    settings = Settings.from_env()
    assert settings.ai_provider == "gemini"
    assert settings.gemini_model == "gemini-custom"
