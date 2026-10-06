"""§8 of the v2 rebuild brief: PaymentProvider must be selectable via config
and must never run an unverified Hamyon integration. Covers the config-level
guard (app/config.py) and the registry (providers/registry.py)."""
from __future__ import annotations

import pytest

from app.config import Settings
from app.domains.payments.providers.base import ProviderNotConfigured
from app.domains.payments.providers.hamyon import HamyonPaymentProvider
from app.domains.payments.providers.manual_receipt import ManualReceiptPaymentProvider
from app.domains.payments.providers.registry import get_payment_provider


def _settings(**overrides) -> Settings:
    base = dict(
        database_url="postgresql://x", bot_token="x", session_secret="x", signing_secret="x",
        uploads_root="/tmp", payment_provider="manual_receipt",
        hamyon_api_url=None, hamyon_api_key=None, hamyon_merchant_id=None, hamyon_webhook_secret=None,
        ai_provider=None, anthropic_api_key=None, gemini_api_key=None, gemini_model=None,
        stt_provider=None, openai_api_key=None, ai_voice_max_bytes=1_000_000,
    )
    base.update(overrides)
    return Settings(**base)


def test_default_provider_is_manual_receipt(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    monkeypatch.setenv("BOT_TOKEN", "x")
    monkeypatch.setenv("SESSION_SECRET", "x")
    monkeypatch.setenv("SIGNING_SECRET", "x")
    monkeypatch.delenv("PAYMENT_PROVIDER", raising=False)
    settings = Settings.from_env()
    assert settings.payment_provider == "manual_receipt"
    provider = get_payment_provider(settings)
    assert isinstance(provider, ManualReceiptPaymentProvider)


def test_hamyon_without_env_vars_fails_startup(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    monkeypatch.setenv("BOT_TOKEN", "x")
    monkeypatch.setenv("SESSION_SECRET", "x")
    monkeypatch.setenv("SIGNING_SECRET", "x")
    monkeypatch.setenv("PAYMENT_PROVIDER", "hamyon")
    for key in ("HAMYON_API_URL", "HAMYON_API_KEY", "HAMYON_MERCHANT_ID", "HAMYON_WEBHOOK_SECRET"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(RuntimeError, match="HAMYON_API_URL"):
        Settings.from_env()


@pytest.mark.asyncio
async def test_hamyon_provider_every_method_raises_not_configured():
    settings = _settings(
        payment_provider="hamyon", hamyon_api_url="https://x", hamyon_api_key="k",
        hamyon_merchant_id="m", hamyon_webhook_secret="s",
    )
    provider = HamyonPaymentProvider(settings)
    with pytest.raises(ProviderNotConfigured):
        await provider.create_payment(order_id=1, amount=100, currency="UZS")
    with pytest.raises(ProviderNotConfigured):
        await provider.get_status(provider_payment_id="x")
    with pytest.raises(ProviderNotConfigured):
        await provider.verify_callback(headers={}, raw_body=b"{}")
    with pytest.raises(ProviderNotConfigured):
        await provider.refund(provider_payment_id="x", amount=100)


def test_unknown_provider_rejected():
    with pytest.raises(ValueError):
        get_payment_provider(_settings(payment_provider="totally_made_up"))
