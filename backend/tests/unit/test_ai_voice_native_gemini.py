"""§P5.2: the native Gemini voice path in bot/handlers/ai.py —
`handle_admin_voice` branching to `_handle_admin_voice_native_gemini` when
`AI_PROVIDER=gemini`, and converging into `_handle_structured_result`, the
exact same resolver/draft/confirmation code the text and Whisper-voice
paths already use. Mocked bot/pool/conn/provider — no real Telegram,
Gemini, or DB. The pre-existing Whisper-based voice tests in
test_ai_bot_handlers.py are unaffected and still pass unchanged (verified
separately) — this file only covers the new AI_PROVIDER=gemini branch.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.ai.drafts import service as drafts_service
from app.ai.providers.base import ProviderNotConfigured, StructuredCommandResult
from app.ai.providers.fallback import FallbackAIProvider
from app.ai.providers.stub import StubAIProvider
from app.ai.voice import VoiceRetrievalError
from bot.handlers import ai as ai_handlers
from bot.locales import uz

pytestmark = pytest.mark.asyncio

_VALID_OGG = b"OggS" + b"\x00" * 64


@pytest.fixture(autouse=True)
def _required_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    monkeypatch.setenv("BOT_TOKEN", "x")
    monkeypatch.setenv("SESSION_SECRET", "x")
    monkeypatch.setenv("SIGNING_SECRET", "x")
    monkeypatch.setenv("AI_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")


class FakeUser:
    def __init__(self, user_id=777):
        self.id = user_id


class FakeChat:
    def __init__(self, chat_id=555):
        self.id = chat_id


class FakeMessage:
    def __init__(self, voice=None, from_user=None, chat=None):
        self.voice = voice
        self.from_user = from_user or FakeUser()
        self.chat = chat or FakeChat()
        self.answer = AsyncMock()


def _fake_pool(conn):
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool


def _fake_conn():
    return MagicMock()


def _voice(file_id="v1", mime_type="audio/ogg"):
    return MagicMock(file_id=file_id, mime_type=mime_type)


def _bot(audio_bytes=_VALID_OGG):
    bot = MagicMock()
    bot.get_file = AsyncMock(return_value=MagicMock(file_path="voice.ogg"))
    buffer = MagicMock()
    buffer.read.return_value = audio_bytes
    bot.download_file = AsyncMock(return_value=buffer)
    return bot


def _admin():
    return {"id": 1, "telegram_id": 777, "role": "ADMIN", "status": "ACTIVE"}


# ---------------------------------------------------------------------------
# Case A — valid voice command reaches the resolver/draft service
# ---------------------------------------------------------------------------


async def test_valid_native_voice_command_creates_a_draft(monkeypatch):
    monkeypatch.setattr(ai_handlers.identity_repository, "find_by_telegram_id", AsyncMock(return_value=_admin()))

    provider = MagicMock()
    provider.generate_structured_command = AsyncMock(
        return_value=StructuredCommandResult(command_type="INCREASE_STOCK", payload={"product_query": "Malibu 2", "delta": 1})
    )
    monkeypatch.setattr(ai_handlers, "get_ai_provider", lambda settings: provider)
    monkeypatch.setattr(ai_handlers.resolver, "resolve_command_references", AsyncMock(return_value={"variant_id": 42, "delta": 1}))
    handle_command = AsyncMock(return_value={
        "executed": False, "draft_id": 7, "confirmation_token": "tok", "preview": "INCREASE_STOCK\nvariant_id: 42",
    })
    monkeypatch.setattr(ai_handlers.drafts_service, "handle_command", handle_command)

    bot = _bot()
    message = FakeMessage(voice=_voice())
    await ai_handlers.handle_admin_voice(message, _fake_pool(_fake_conn()), bot=bot)

    # The provider receives the AudioInput, never text — proving the
    # native path, not a fallback to transcription.
    provider.generate_structured_command.assert_awaited_once()
    _, kwargs = provider.generate_structured_command.call_args
    assert kwargs.get("audio") is not None
    assert kwargs.get("text") is None

    handle_command.assert_awaited_once()
    _, hc_kwargs = handle_command.call_args
    assert hc_kwargs["command_type"] == "INCREASE_STOCK"
    assert hc_kwargs["source"] == "VOICE"

    # No execution yet — only a preview + confirmation keyboard.
    message.answer.assert_awaited_once()
    args, kwargs = message.answer.call_args
    assert "INCREASE_STOCK" in args[0]
    assert kwargs["reply_markup"] is not None


# ---------------------------------------------------------------------------
# Case D — unrecognized voice: no draft, no DB mutation attempt
# ---------------------------------------------------------------------------


async def test_unrecognized_native_voice_replies_not_understood_and_creates_no_draft(monkeypatch):
    monkeypatch.setattr(ai_handlers.identity_repository, "find_by_telegram_id", AsyncMock(return_value=_admin()))

    provider = MagicMock()
    provider.generate_structured_command = AsyncMock(return_value=StructuredCommandResult(command_type=None, payload={}))
    monkeypatch.setattr(ai_handlers, "get_ai_provider", lambda settings: provider)
    handle_command = AsyncMock()
    monkeypatch.setattr(ai_handlers.drafts_service, "handle_command", handle_command)

    message = FakeMessage(voice=_voice())
    await ai_handlers.handle_admin_voice(message, _fake_pool(_fake_conn()), bot=_bot())

    handle_command.assert_not_called()
    message.answer.assert_awaited_once_with(uz.AI_NOT_UNDERSTOOD)


async def test_native_voice_clarification_required_is_surfaced(monkeypatch):
    monkeypatch.setattr(ai_handlers.identity_repository, "find_by_telegram_id", AsyncMock(return_value=_admin()))

    provider = MagicMock()
    provider.generate_structured_command = AsyncMock(
        return_value=StructuredCommandResult(
            command_type=None, payload={}, clarification_required=True,
            clarification_message="Qaysi mahsulotni nazarda tutyapsiz?",
        )
    )
    monkeypatch.setattr(ai_handlers, "get_ai_provider", lambda settings: provider)

    message = FakeMessage(voice=_voice())
    await ai_handlers.handle_admin_voice(message, _fake_pool(_fake_conn()), bot=_bot())

    message.answer.assert_awaited_once_with(uz.AI_CLARIFICATION_NEEDED.format(message="Qaysi mahsulotni nazarda tutyapsiz?"))


# ---------------------------------------------------------------------------
# Case F — prompt injection in spoken content never becomes an unauthorized
# command (the provider itself is responsible for rejecting it — proven at
# the provider level in test_gemini_provider_audio.py; here we only prove
# the handler treats a "rejected/unknown" provider result exactly like any
# other unparseable input, never specially).
# ---------------------------------------------------------------------------


async def test_prompt_injection_result_never_reaches_draft_service(monkeypatch):
    monkeypatch.setattr(ai_handlers.identity_repository, "find_by_telegram_id", AsyncMock(return_value=_admin()))

    provider = MagicMock()
    # Simulates what app/ai/providers/gemini_provider.py already guarantees
    # for injection attempts: command_type=None, never a fabricated command.
    provider.generate_structured_command = AsyncMock(
        return_value=StructuredCommandResult(command_type=None, payload={}, raw_text="")
    )
    monkeypatch.setattr(ai_handlers, "get_ai_provider", lambda settings: provider)
    handle_command = AsyncMock()
    monkeypatch.setattr(ai_handlers.drafts_service, "handle_command", handle_command)

    message = FakeMessage(voice=_voice())
    await ai_handlers.handle_admin_voice(message, _fake_pool(_fake_conn()), bot=_bot())

    handle_command.assert_not_called()


# ---------------------------------------------------------------------------
# Invalid/oversized audio — rejected before any AI call
# ---------------------------------------------------------------------------


async def test_invalid_audio_replies_safe_message_and_never_calls_provider(monkeypatch):
    monkeypatch.setattr(ai_handlers.identity_repository, "find_by_telegram_id", AsyncMock(return_value=_admin()))

    provider = MagicMock()
    provider.generate_structured_command = AsyncMock()
    monkeypatch.setattr(ai_handlers, "get_ai_provider", lambda settings: provider)

    bot = _bot(audio_bytes=b"not-audio-at-all")  # fails the magic-byte check
    message = FakeMessage(voice=_voice())
    await ai_handlers.handle_admin_voice(message, _fake_pool(_fake_conn()), bot=bot)

    provider.generate_structured_command.assert_not_awaited()
    message.answer.assert_awaited_once_with(uz.AI_VOICE_INVALID)


async def test_oversized_audio_rejected_before_provider_call(monkeypatch):
    monkeypatch.setattr(ai_handlers.identity_repository, "find_by_telegram_id", AsyncMock(return_value=_admin()))
    monkeypatch.setattr(ai_handlers.Settings, "from_env", classmethod(lambda cls: _settings_with(ai_voice_max_bytes=10)))

    provider = MagicMock()
    provider.generate_structured_command = AsyncMock()
    monkeypatch.setattr(ai_handlers, "get_ai_provider", lambda settings: provider)

    bot = _bot(audio_bytes=_VALID_OGG)  # larger than the 10-byte limit configured above
    message = FakeMessage(voice=_voice())
    await ai_handlers.handle_admin_voice(message, _fake_pool(_fake_conn()), bot=bot)

    provider.generate_structured_command.assert_not_awaited()
    message.answer.assert_awaited_once_with(uz.AI_VOICE_INVALID)


async def test_telegram_download_failure_replies_safe_message(monkeypatch):
    monkeypatch.setattr(ai_handlers.identity_repository, "find_by_telegram_id", AsyncMock(return_value=_admin()))

    bot = MagicMock()
    bot.get_file = AsyncMock(side_effect=ConnectionError("network down"))
    message = FakeMessage(voice=_voice())
    await ai_handlers.handle_admin_voice(message, _fake_pool(_fake_conn()), bot=bot)

    message.answer.assert_awaited_once_with(uz.AI_VOICE_INVALID)


# ---------------------------------------------------------------------------
# AI provider failure (missing key / timeout / 429 / 5xx / malformed) — all
# surfaced the same existing safe way, never a raw exception
# ---------------------------------------------------------------------------


async def test_provider_failure_replies_generic_error(monkeypatch):
    monkeypatch.setattr(ai_handlers.identity_repository, "find_by_telegram_id", AsyncMock(return_value=_admin()))

    provider = MagicMock()
    provider.generate_structured_command = AsyncMock(side_effect=ProviderNotConfigured("Gemini API call failed: Timeout"))
    monkeypatch.setattr(ai_handlers, "get_ai_provider", lambda settings: provider)

    message = FakeMessage(voice=_voice())
    await ai_handlers.handle_admin_voice(message, _fake_pool(_fake_conn()), bot=_bot())

    message.answer.assert_awaited_once_with(uz.AI_PROVIDER_FAILED)


# ---------------------------------------------------------------------------
# Fallback: real FallbackAIProvider(primary fails) -> StubAIProvider must
# still converge safely, never fabricating a command from unavailable audio
# ---------------------------------------------------------------------------


async def test_real_fallback_provider_never_fabricates_a_command_from_audio(monkeypatch):
    monkeypatch.setattr(ai_handlers.identity_repository, "find_by_telegram_id", AsyncMock(return_value=_admin()))

    failing_primary = MagicMock()
    failing_primary.name = "gemini"
    failing_primary.generate_structured_command = AsyncMock(side_effect=ProviderNotConfigured("429"))
    provider = FallbackAIProvider(primary=failing_primary, fallback=StubAIProvider())
    monkeypatch.setattr(ai_handlers, "get_ai_provider", lambda settings: provider)
    handle_command = AsyncMock()
    monkeypatch.setattr(ai_handlers.drafts_service, "handle_command", handle_command)

    message = FakeMessage(voice=_voice())
    await ai_handlers.handle_admin_voice(message, _fake_pool(_fake_conn()), bot=_bot())

    handle_command.assert_not_called()
    message.answer.assert_awaited_once_with(uz.AI_NOT_UNDERSTOOD)


# ---------------------------------------------------------------------------
# RBAC: the shared `_admin_or_owner` router filter (already exhaustively
# tested in test_ai_bot_handlers.py) is what actually prevents a USER's
# voice message from ever reaching `handle_admin_voice`. This test proves
# the native-audio branch does not introduce a second, weaker gate: when
# `_load_actor` resolves to None inside `_handle_structured_result` (the
# same defense-in-depth re-check every other modality already has), no
# draft is created either.
# ---------------------------------------------------------------------------


async def test_actor_resolution_failure_inside_handler_creates_no_draft(monkeypatch):
    monkeypatch.setattr(ai_handlers.identity_repository, "find_by_telegram_id", AsyncMock(return_value=None))

    provider = MagicMock()
    provider.generate_structured_command = AsyncMock(
        return_value=StructuredCommandResult(command_type="INCREASE_STOCK", payload={"product_query": "Malibu 2", "delta": 1})
    )
    monkeypatch.setattr(ai_handlers, "get_ai_provider", lambda settings: provider)
    handle_command = AsyncMock()
    monkeypatch.setattr(ai_handlers.drafts_service, "handle_command", handle_command)

    message = FakeMessage(voice=_voice())
    await ai_handlers.handle_admin_voice(message, _fake_pool(_fake_conn()), bot=_bot())

    handle_command.assert_not_called()
    message.answer.assert_not_called()


def _settings_with(**overrides):
    from app.config import Settings

    base = dict(
        database_url="postgresql://x", bot_token="x", session_secret="x", signing_secret="x",
        uploads_root="/tmp", payment_provider="manual_receipt",
        hamyon_api_url=None, hamyon_api_key=None, hamyon_merchant_id=None, hamyon_webhook_secret=None,
        ai_provider="gemini", anthropic_api_key=None, gemini_api_key="test-key", gemini_model=None,
        stt_provider=None, openai_api_key=None, ai_voice_max_bytes=1_000_000,
    )
    base.update(overrides)
    return Settings(**base)
