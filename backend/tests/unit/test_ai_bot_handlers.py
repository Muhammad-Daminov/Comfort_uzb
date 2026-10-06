"""Unit tests for the AI admin-assistant bot handlers (bot/handlers/ai.py).
Mocked pool/conn/bot, no real DB or Telegram connection — the underlying
drafts/service.py + resolver.py logic is covered end-to-end against a real
DB by tests/integration/test_ai_drafts_workflow.py. These tests verify the
presentation-layer branching: role gating, error-message mapping, and
callback handling (duplicate confirm, wrong owner, expiry)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.ai.drafts import service as drafts_service
from app.ai.providers.base import ProviderNotConfigured, StructuredCommandResult
from bot.handlers import ai as ai_handlers
from bot.locales import uz

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _required_env(monkeypatch):
    # Settings.from_env() is called inside the handlers under test (to
    # select the AI/STT provider) — these tests don't exercise Settings
    # itself, so the minimal required set is enough.
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    monkeypatch.setenv("BOT_TOKEN", "x")
    monkeypatch.setenv("SESSION_SECRET", "x")
    monkeypatch.setenv("SIGNING_SECRET", "x")


class FakeUser:
    def __init__(self, user_id=777):
        self.id = user_id


class FakeChat:
    def __init__(self, chat_id=555):
        self.id = chat_id


class FakeMessage:
    def __init__(self, text=None, from_user=None, caption=None, photo=None, voice=None, chat=None):
        self.text = text
        self.from_user = from_user or FakeUser()
        self.caption = caption
        self.photo = photo
        self.voice = voice
        self.chat = chat or FakeChat()
        self.answer = AsyncMock()


class FakeCallback:
    def __init__(self, data, from_user=None):
        self.data = data
        self.from_user = from_user or FakeUser()
        self.message = MagicMock()
        self.message.edit_text = AsyncMock()
        self.message.edit_reply_markup = AsyncMock()
        self.answer = AsyncMock()


def _fake_pool(conn):
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool


def _fake_conn():
    return MagicMock()


async def test_admin_or_owner_filter_accepts_admin(monkeypatch):
    monkeypatch.setattr(
        ai_handlers.identity_repository, "find_by_telegram_id",
        AsyncMock(return_value={"id": 1, "telegram_id": 777, "role": "ADMIN", "status": "ACTIVE"}),
    )
    message = FakeMessage()
    assert await ai_handlers._admin_or_owner(message, _fake_pool(_fake_conn())) is True


async def test_admin_or_owner_filter_rejects_user(monkeypatch):
    monkeypatch.setattr(
        ai_handlers.identity_repository, "find_by_telegram_id",
        AsyncMock(return_value={"id": 1, "telegram_id": 777, "role": "USER", "status": "ACTIVE"}),
    )
    message = FakeMessage()
    assert await ai_handlers._admin_or_owner(message, _fake_pool(_fake_conn())) is False


async def test_admin_or_owner_filter_rejects_unknown_sender(monkeypatch):
    monkeypatch.setattr(ai_handlers.identity_repository, "find_by_telegram_id", AsyncMock(return_value=None))
    message = FakeMessage()
    assert await ai_handlers._admin_or_owner(message, _fake_pool(_fake_conn())) is False


async def test_text_command_starting_with_slash_is_ignored(monkeypatch):
    handle_command = AsyncMock()
    monkeypatch.setattr(ai_handlers.drafts_service, "handle_command", handle_command)
    message = FakeMessage(text="/start")
    await ai_handlers.handle_admin_text(message, _fake_pool(_fake_conn()), bot=MagicMock())
    handle_command.assert_not_called()
    message.answer.assert_not_called()


async def test_unrecognized_text_replies_not_understood(monkeypatch):
    monkeypatch.setattr(
        ai_handlers.identity_repository, "find_by_telegram_id",
        AsyncMock(return_value={"id": 1, "telegram_id": 777, "role": "ADMIN", "status": "ACTIVE"}),
    )
    provider = MagicMock()
    provider.generate_structured_command = AsyncMock(
        return_value=StructuredCommandResult(command_type=None, payload={}, raw_text="bugun ob-havo qanday")
    )
    monkeypatch.setattr(ai_handlers, "get_ai_provider", lambda settings: provider)

    message = FakeMessage(text="bugun ob-havo qanday")
    await ai_handlers.handle_admin_text(message, _fake_pool(_fake_conn()), bot=MagicMock())

    message.answer.assert_awaited_once_with(uz.AI_NOT_UNDERSTOOD)


async def test_ai_provider_failure_replies_generic_error(monkeypatch):
    monkeypatch.setattr(
        ai_handlers.identity_repository, "find_by_telegram_id",
        AsyncMock(return_value={"id": 1, "telegram_id": 777, "role": "ADMIN", "status": "ACTIVE"}),
    )
    provider = MagicMock()
    provider.generate_structured_command = AsyncMock(side_effect=ProviderNotConfigured("no key"))
    monkeypatch.setattr(ai_handlers, "get_ai_provider", lambda settings: provider)

    message = FakeMessage(text="Malibu 2 + 1")
    await ai_handlers.handle_admin_text(message, _fake_pool(_fake_conn()), bot=MagicMock())

    message.answer.assert_awaited_once_with(uz.AI_PROVIDER_FAILED)


async def test_mutation_command_sends_preview_with_confirmation_keyboard(monkeypatch):
    monkeypatch.setattr(
        ai_handlers.identity_repository, "find_by_telegram_id",
        AsyncMock(return_value={"id": 1, "telegram_id": 777, "role": "ADMIN", "status": "ACTIVE"}),
    )
    provider = MagicMock()
    provider.generate_structured_command = AsyncMock(
        return_value=StructuredCommandResult(
            command_type="INCREASE_STOCK", payload={"product_query": "Malibu 2", "delta": 1}, raw_text="Malibu 2 + 1",
        )
    )
    monkeypatch.setattr(ai_handlers, "get_ai_provider", lambda settings: provider)
    monkeypatch.setattr(
        ai_handlers.resolver, "resolve_command_references",
        AsyncMock(return_value={"variant_id": 42, "delta": 1}),
    )
    monkeypatch.setattr(
        ai_handlers.drafts_service, "handle_command",
        AsyncMock(return_value={
            "executed": False, "draft_id": 9, "confirmation_token": "tok", "preview": "INCREASE_STOCK\nvariant_id: 42",
        }),
    )

    message = FakeMessage(text="Malibu 2 + 1")
    await ai_handlers.handle_admin_text(message, _fake_pool(_fake_conn()), bot=MagicMock())

    message.answer.assert_awaited_once()
    args, kwargs = message.answer.call_args
    assert "INCREASE_STOCK" in args[0]
    assert kwargs["reply_markup"] is not None


async def test_read_only_command_sends_result_without_keyboard(monkeypatch):
    monkeypatch.setattr(
        ai_handlers.identity_repository, "find_by_telegram_id",
        AsyncMock(return_value={"id": 1, "telegram_id": 777, "role": "OWNER", "status": "ACTIVE"}),
    )
    provider = MagicMock()
    provider.generate_structured_command = AsyncMock(
        return_value=StructuredCommandResult(command_type="GET_STOCK", payload={"variant_id": 42}, raw_text="Malibu 2 qoldig'i"),
    )
    monkeypatch.setattr(ai_handlers, "get_ai_provider", lambda settings: provider)
    monkeypatch.setattr(ai_handlers.resolver, "resolve_command_references", AsyncMock(return_value={"variant_id": 42}))
    monkeypatch.setattr(
        ai_handlers.drafts_service, "handle_command",
        AsyncMock(return_value={"executed": True, "read_only": True, "result": {"available": 7}}),
    )

    message = FakeMessage(text="Malibu 2 qoldig'i")
    await ai_handlers.handle_admin_text(message, _fake_pool(_fake_conn()), bot=MagicMock())

    message.answer.assert_awaited_once()
    (sent_text,), kwargs = message.answer.call_args
    assert "available: 7" in sent_text
    assert "reply_markup" not in kwargs


async def test_unauthorized_ai_command_replies_and_does_not_raise(monkeypatch):
    monkeypatch.setattr(
        ai_handlers.identity_repository, "find_by_telegram_id",
        AsyncMock(return_value={"id": 1, "telegram_id": 777, "role": "ADMIN", "status": "ACTIVE"}),
    )
    provider = MagicMock()
    provider.generate_structured_command = AsyncMock(
        return_value=StructuredCommandResult(command_type="GET_REVENUE", payload={"date_from": "2026-01-01", "date_to": "2026-01-02"}),
    )
    monkeypatch.setattr(ai_handlers, "get_ai_provider", lambda settings: provider)
    monkeypatch.setattr(ai_handlers.resolver, "resolve_command_references", AsyncMock(side_effect=lambda conn, ct, p: p))
    monkeypatch.setattr(
        ai_handlers.drafts_service, "handle_command",
        AsyncMock(side_effect=drafts_service.Forbidden("role ADMIN lacks permission finance.view")),
    )

    message = FakeMessage(text="Bu oy qancha daromad?")
    await ai_handlers.handle_admin_text(message, _fake_pool(_fake_conn()), bot=MagicMock())

    message.answer.assert_awaited_once_with(uz.AI_UNAUTHORIZED)


async def test_photo_without_caption_opens_a_pending_media_context(monkeypatch):
    monkeypatch.setattr(
        ai_handlers.identity_repository, "find_by_telegram_id",
        AsyncMock(return_value={"id": 1, "telegram_id": 777, "role": "ADMIN", "status": "ACTIVE"}),
    )
    create_or_replace = AsyncMock(return_value={"id": 1, "telegram_file_id": "file123"})
    monkeypatch.setattr(ai_handlers.pending_media, "create_or_replace", create_or_replace)

    message = FakeMessage(photo=[MagicMock(file_id="file123")])
    await ai_handlers.handle_admin_photo(message, _fake_pool(_fake_conn()), bot=MagicMock())

    create_or_replace.assert_awaited_once()
    _, kwargs = create_or_replace.call_args
    assert kwargs == {"admin_id": 1, "chat_id": 555, "telegram_file_id": "file123"}
    message.answer.assert_awaited_once_with(uz.AI_PHOTO_AWAITING_DESCRIPTION)


async def test_voice_after_photo_correlates_into_create_product_draft(monkeypatch):
    monkeypatch.setattr(
        ai_handlers.identity_repository, "find_by_telegram_id",
        AsyncMock(return_value={"id": 1, "telegram_id": 777, "role": "ADMIN", "status": "ACTIVE"}),
    )
    bot = MagicMock()
    bot.get_file = AsyncMock(return_value=MagicMock(file_path="voice.ogg"))
    buffer = MagicMock()
    buffer.read.return_value = b"fake-audio-bytes"
    bot.download_file = AsyncMock(return_value=buffer)
    stt = MagicMock()
    stt.transcribe = AsyncMock(return_value="Malibu 2, qora, koja, 500 dollar, 1 dona")
    monkeypatch.setattr(ai_handlers, "get_stt_provider", lambda settings: stt)

    provider = MagicMock()
    provider.generate_structured_command = AsyncMock(
        return_value=StructuredCommandResult(
            command_type="CREATE_PRODUCT",
            payload={"name": "Malibu 2", "description": "qora, koja", "price": 500, "initial_stock": 1, "brand_id": 3},
        )
    )
    monkeypatch.setattr(ai_handlers, "get_ai_provider", lambda settings: provider)
    monkeypatch.setattr(ai_handlers.resolver, "resolve_command_references", AsyncMock(side_effect=lambda conn, ct, p: p))
    monkeypatch.setattr(
        ai_handlers.pending_media, "consume",
        AsyncMock(return_value={"id": 1, "telegram_file_id": "photo-file-1"}),
    )
    handle_command = AsyncMock(return_value={
        "executed": False, "draft_id": 1, "confirmation_token": "tok", "preview": "CREATE_PRODUCT",
    })
    monkeypatch.setattr(ai_handlers.drafts_service, "handle_command", handle_command)

    message = FakeMessage(voice=MagicMock(file_id="v1", mime_type="audio/ogg"))
    await ai_handlers.handle_admin_voice(message, _fake_pool(_fake_conn()), bot=bot)

    handle_command.assert_awaited_once()
    _, kwargs = handle_command.call_args
    assert kwargs["raw_payload"]["telegram_image_file_id"] == "photo-file-1"


async def test_unrelated_voice_after_photo_does_not_consume_it(monkeypatch):
    """A stock command after a bare photo is unrelated — the pending photo
    must stay available for a later, correct description, not get consumed
    by an unrelated command."""
    monkeypatch.setattr(
        ai_handlers.identity_repository, "find_by_telegram_id",
        AsyncMock(return_value={"id": 1, "telegram_id": 777, "role": "ADMIN", "status": "ACTIVE"}),
    )
    provider = MagicMock()
    provider.generate_structured_command = AsyncMock(
        return_value=StructuredCommandResult(command_type="INCREASE_STOCK", payload={"product_query": "Malibu 2", "delta": 1}),
    )
    monkeypatch.setattr(ai_handlers, "get_ai_provider", lambda settings: provider)
    monkeypatch.setattr(ai_handlers.resolver, "resolve_command_references", AsyncMock(return_value={"variant_id": 1, "delta": 1}))
    consume = AsyncMock()
    monkeypatch.setattr(ai_handlers.pending_media, "consume", consume)
    monkeypatch.setattr(
        ai_handlers.drafts_service, "handle_command",
        AsyncMock(return_value={"executed": False, "draft_id": 1, "confirmation_token": "tok", "preview": "x"}),
    )

    message = FakeMessage(text="Malibu 2 + 1")
    await ai_handlers.handle_admin_text(message, _fake_pool(_fake_conn()), bot=MagicMock())

    consume.assert_not_called()


async def test_voice_without_stt_configured_replies_actionable_message(monkeypatch):
    bot = MagicMock()
    bot.get_file = AsyncMock(return_value=MagicMock(file_path="voice.ogg"))
    buffer = MagicMock()
    buffer.read.return_value = b"fake-audio-bytes"
    bot.download_file = AsyncMock(return_value=buffer)

    stt = MagicMock()
    stt.transcribe = AsyncMock(side_effect=ProviderNotConfigured("no STT_PROVIDER"))
    monkeypatch.setattr(ai_handlers, "get_stt_provider", lambda settings: stt)

    message = FakeMessage(voice=MagicMock(file_id="v1", mime_type="audio/ogg"))
    await ai_handlers.handle_admin_voice(message, _fake_pool(_fake_conn()), bot=bot)

    message.answer.assert_awaited_once_with(uz.AI_STT_NOT_CONFIGURED)


async def test_successful_voice_transcription_reuses_text_pipeline_and_creates_draft(monkeypatch):
    """§Priority 2: voice must reuse exactly the same text-command pipeline
    — no duplicated business logic. Verified here by asserting the same
    drafts_service.handle_command call a text command would make."""
    bot = MagicMock()
    bot.get_file = AsyncMock(return_value=MagicMock(file_path="voice.ogg"))
    buffer = MagicMock()
    buffer.read.return_value = b"fake-audio-bytes"
    bot.download_file = AsyncMock(return_value=buffer)

    stt = MagicMock()
    stt.transcribe = AsyncMock(return_value="Malibu 2 + 1")
    monkeypatch.setattr(ai_handlers, "get_stt_provider", lambda settings: stt)

    monkeypatch.setattr(
        ai_handlers.identity_repository, "find_by_telegram_id",
        AsyncMock(return_value={"id": 1, "telegram_id": 777, "role": "ADMIN", "status": "ACTIVE"}),
    )
    provider = MagicMock()
    provider.generate_structured_command = AsyncMock(
        return_value=StructuredCommandResult(
            command_type="INCREASE_STOCK", payload={"product_query": "Malibu 2", "delta": 1}, raw_text="Malibu 2 + 1",
        )
    )
    monkeypatch.setattr(ai_handlers, "get_ai_provider", lambda settings: provider)
    monkeypatch.setattr(
        ai_handlers.resolver, "resolve_command_references", AsyncMock(return_value={"variant_id": 42, "delta": 1}),
    )
    handle_command = AsyncMock(return_value={
        "executed": False, "draft_id": 5, "confirmation_token": "tok", "preview": "INCREASE_STOCK\nvariant_id: 42",
    })
    monkeypatch.setattr(ai_handlers.drafts_service, "handle_command", handle_command)

    message = FakeMessage(voice=MagicMock(file_id="v1", mime_type="audio/ogg"))
    await ai_handlers.handle_admin_voice(message, _fake_pool(_fake_conn()), bot=bot)

    handle_command.assert_awaited_once()
    _, kwargs = handle_command.call_args
    assert kwargs["command_type"] == "INCREASE_STOCK"
    assert kwargs["source"] == "VOICE"
    message.answer.assert_awaited_once()
    _, sent_kwargs = message.answer.call_args
    assert sent_kwargs["reply_markup"] is not None


async def test_confirm_callback_success_edits_message(monkeypatch):
    monkeypatch.setattr(
        ai_handlers.identity_repository, "find_by_telegram_id",
        AsyncMock(return_value={"id": 1, "telegram_id": 777, "role": "ADMIN", "status": "ACTIVE"}),
    )
    monkeypatch.setattr(
        ai_handlers.drafts_repository, "get_draft",
        AsyncMock(return_value={"id": 9, "confirmation_token": "tok"}),
    )
    monkeypatch.setattr(
        ai_handlers.drafts_service, "confirm",
        AsyncMock(return_value={"draft_id": 9, "command_type": "INCREASE_STOCK", "result": {"quantity_after": 2}}),
    )

    callback = FakeCallback(data="ai_confirm:9")
    await ai_handlers.handle_ai_confirm(callback, _fake_pool(_fake_conn()), bot=MagicMock())

    callback.message.edit_text.assert_awaited_once()
    callback.answer.assert_awaited_once()


async def test_confirm_callback_duplicate_tap_shows_already_handled(monkeypatch):
    monkeypatch.setattr(
        ai_handlers.identity_repository, "find_by_telegram_id",
        AsyncMock(return_value={"id": 1, "telegram_id": 777, "role": "ADMIN", "status": "ACTIVE"}),
    )
    monkeypatch.setattr(
        ai_handlers.drafts_repository, "get_draft",
        AsyncMock(return_value={"id": 9, "confirmation_token": "tok"}),
    )
    monkeypatch.setattr(
        ai_handlers.drafts_service, "confirm",
        AsyncMock(side_effect=drafts_service.DraftNotPending("already CONFIRMED")),
    )

    callback = FakeCallback(data="ai_confirm:9")
    await ai_handlers.handle_ai_confirm(callback, _fake_pool(_fake_conn()), bot=MagicMock())

    callback.answer.assert_awaited_once_with(uz.AI_ALREADY_HANDLED, show_alert=True)
    callback.message.edit_reply_markup.assert_awaited_once_with(reply_markup=None)


async def test_confirm_callback_wrong_owner_is_forbidden(monkeypatch):
    monkeypatch.setattr(
        ai_handlers.identity_repository, "find_by_telegram_id",
        AsyncMock(return_value={"id": 2, "telegram_id": 888, "role": "ADMIN", "status": "ACTIVE"}),
    )
    monkeypatch.setattr(
        ai_handlers.drafts_repository, "get_draft",
        AsyncMock(return_value={"id": 9, "confirmation_token": "tok"}),
    )
    monkeypatch.setattr(
        ai_handlers.drafts_service, "confirm",
        AsyncMock(side_effect=drafts_service.DraftNotOwnedByCaller("not yours")),
    )

    callback = FakeCallback(data="ai_confirm:9", from_user=FakeUser(user_id=888))
    await ai_handlers.handle_ai_confirm(callback, _fake_pool(_fake_conn()), bot=MagicMock())

    callback.answer.assert_awaited_once_with(uz.AI_NOT_YOUR_DRAFT, show_alert=True)


async def test_cancel_callback_edits_message(monkeypatch):
    monkeypatch.setattr(
        ai_handlers.identity_repository, "find_by_telegram_id",
        AsyncMock(return_value={"id": 1, "telegram_id": 777, "role": "ADMIN", "status": "ACTIVE"}),
    )
    monkeypatch.setattr(ai_handlers.drafts_service, "cancel", AsyncMock(return_value={"status": "CANCELLED"}))

    callback = FakeCallback(data="ai_cancel:9")
    await ai_handlers.handle_ai_cancel(callback, _fake_pool(_fake_conn()))

    callback.message.edit_text.assert_awaited_once_with(uz.AI_CANCELLED)
