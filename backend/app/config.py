"""Env-driven settings. No hardcoded secrets, no defaults for anything
security-sensitive (§12.1 "Secret management") — missing required env vars
fail loudly at startup, not silently at first use.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from app.ai.audio import DEFAULT_MAX_VOICE_BYTES


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} environment variable is required but not set")
    return value


@dataclass(frozen=True)
class Settings:
    database_url: str
    bot_token: str
    session_secret: str
    signing_secret: str
    uploads_root: str
    payment_provider: str
    hamyon_api_url: str | None
    hamyon_api_key: str | None
    hamyon_merchant_id: str | None
    hamyon_webhook_secret: str | None
    ai_provider: str | None
    anthropic_api_key: str | None
    gemini_api_key: str | None
    gemini_model: str | None
    stt_provider: str | None
    openai_api_key: str | None
    ai_voice_max_bytes: int

    @classmethod
    def from_env(cls) -> "Settings":
        payment_provider = os.environ.get("PAYMENT_PROVIDER", "manual_receipt")
        hamyon_api_url = os.environ.get("HAMYON_API_URL") or None
        hamyon_api_key = os.environ.get("HAMYON_API_KEY") or None
        hamyon_merchant_id = os.environ.get("HAMYON_MERCHANT_ID") or None
        hamyon_webhook_secret = os.environ.get("HAMYON_WEBHOOK_SECRET") or None
        if payment_provider == "hamyon" and not all(
            [hamyon_api_url, hamyon_api_key, hamyon_merchant_id, hamyon_webhook_secret]
        ):
            # docs/13_V2_REBUILD_AUDIT.md §2: no Hamyon API is documented in
            # this codebase, so PAYMENT_PROVIDER=hamyon fails loudly at
            # startup rather than running an unverified/guessed integration
            # against real money.
            raise RuntimeError(
                "PAYMENT_PROVIDER=hamyon requires HAMYON_API_URL, HAMYON_API_KEY, "
                "HAMYON_MERCHANT_ID, HAMYON_WEBHOOK_SECRET — see docs/13_V2_REBUILD_AUDIT.md §2"
            )

        ai_provider = os.environ.get("AI_PROVIDER") or None
        anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY") or None
        if ai_provider == "anthropic" and not anthropic_api_key:
            raise RuntimeError("AI_PROVIDER=anthropic requires ANTHROPIC_API_KEY")

        gemini_api_key = os.environ.get("GEMINI_API_KEY") or None
        gemini_model = os.environ.get("GEMINI_MODEL") or None
        if ai_provider == "gemini" and not gemini_api_key:
            raise RuntimeError("AI_PROVIDER=gemini requires GEMINI_API_KEY")

        stt_provider = os.environ.get("STT_PROVIDER") or None
        openai_api_key = os.environ.get("OPENAI_API_KEY") or None
        if stt_provider == "openai_whisper" and not openai_api_key:
            raise RuntimeError("STT_PROVIDER=openai_whisper requires OPENAI_API_KEY")

        ai_voice_max_bytes_raw = os.environ.get("AI_VOICE_MAX_BYTES") or None
        ai_voice_max_bytes = int(ai_voice_max_bytes_raw) if ai_voice_max_bytes_raw else DEFAULT_MAX_VOICE_BYTES

        return cls(
            database_url=_required("DATABASE_URL"),
            bot_token=_required("BOT_TOKEN"),
            session_secret=_required("SESSION_SECRET"),
            signing_secret=_required("SIGNING_SECRET"),
            uploads_root=os.environ.get("UPLOADS_ROOT", "/var/comfort/uploads"),
            payment_provider=payment_provider,
            hamyon_api_url=hamyon_api_url,
            hamyon_api_key=hamyon_api_key,
            hamyon_merchant_id=hamyon_merchant_id,
            hamyon_webhook_secret=hamyon_webhook_secret,
            ai_provider=ai_provider,
            anthropic_api_key=anthropic_api_key,
            gemini_api_key=gemini_api_key,
            gemini_model=gemini_model,
            stt_provider=stt_provider,
            openai_api_key=openai_api_key,
            ai_voice_max_bytes=ai_voice_max_bytes,
        )
