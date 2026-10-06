"""§14-25/§38 of the v2 rebuild brief — the Telegram-facing half of the AI
admin assistant. Every path here funnels into the same
`app.ai.drafts.service` functions the HTTP `/admin/ai/*` routes use
(app/ai/router.py) — this module is presentation only (Telegram
messages/keyboards/callbacks), never a second place business logic lives.

    Telegram -> admin auth (role lookup, this module)
             -> AI provider (app.ai.providers)
             -> structured command (app.ai.commands)
             -> backend validation + draft (app.ai.drafts.service)
             -> preview + inline keyboard (this module)
             -> [Tasdiqlash]/[Tahrirlash]/[Bekor qilish] callback
             -> app.ai.drafts.service.confirm/cancel
             -> domain service -> database

The AI never mutates the database directly — every mutation goes through
`drafts_service.confirm`, which re-validates permission and payload before
calling the executor.
"""
from __future__ import annotations

import logging

import asyncpg
from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, Message

from app.ai import pending_media, resolver
from app.ai import voice as ai_voice
from app.ai.commands import InvalidPayload, UnknownCommand
from app.ai.drafts import repository as drafts_repository
from app.ai.drafts import service as drafts_service
from app.ai.providers.base import ProviderNotConfigured, StructuredCommandResult
from app.ai.providers.registry import get_ai_provider, get_stt_provider
from app.config import Settings
from app.domains.identity import repository as identity_repository
from app.security.permissions import CurrentUser
from bot import keyboards
from bot.locales import uz

logger = logging.getLogger(__name__)

router = Router(name="ai_assistant")


async def _load_actor(conn: asyncpg.Connection, telegram_id: int) -> CurrentUser | None:
    row = await identity_repository.find_by_telegram_id(conn, telegram_id=telegram_id)
    if row is None or row["status"] != "ACTIVE" or row["role"] not in ("ADMIN", "OWNER"):
        return None
    return CurrentUser(id=row["id"], telegram_id=row["telegram_id"], role=row["role"], status=row["status"])


async def _admin_or_owner(message: Message, pool: asyncpg.Pool) -> bool:
    """Router-level filter (§7: AI is ADMIN/OWNER only, never USER). A
    non-admin sender simply falls through to the next handler (e.g. the
    ordinary USER onboarding flow in bot/handlers/start.py) — no response
    is sent from here, so this filter must never be the reason a regular
    user's message goes unanswered."""
    if message.from_user is None:
        return False
    async with pool.acquire() as conn:
        actor = await _load_actor(conn, message.from_user.id)
    return actor is not None


def _format_matches(matches: list[dict]) -> str:
    lines = []
    for m in matches:
        label = m.get("product_name") or m.get("name") or "?"
        extra = f" (SKU {m['sku']})" if "sku" in m else ""
        lines.append(f"• {label}{extra}")
    return "\n".join(lines)


def _format_read_only_result(command_type: str, result: dict) -> str:
    lines = [f"🤖 {command_type}:"]
    for key, value in result.items():
        if key == "matches" and isinstance(value, list):
            lines.append(_format_matches(value))
        else:
            lines.append(f"{key}: {value}")
    return "\n".join(lines)


async def _process_ai_text(
    message: Message, pool: asyncpg.Pool, bot: Bot, text: str, *, source: str, image_file_id: str | None = None
) -> None:
    settings = Settings.from_env()
    ai_provider = get_ai_provider(settings)

    try:
        result = await ai_provider.generate_structured_command(text=text)
    except Exception:  # ProviderNotConfigured (misconfigured/live API failure) or anything else
        logger.exception("AI provider call failed")
        await message.answer(uz.AI_PROVIDER_FAILED)
        return

    await _handle_structured_result(message, pool, bot, result, source=source, image_file_id=image_file_id)


async def _handle_structured_result(
    message: Message,
    pool: asyncpg.Pool,
    bot: Bot,
    result: StructuredCommandResult,
    *,
    source: str,
    image_file_id: str | None = None,
) -> None:
    """§P5.2: the single convergence point for every input modality
    (text, Whisper-transcribed voice, and — new in this phase — native
    Gemini audio) once a provider has already produced a
    `StructuredCommandResult`. Everything from here on (resolver, draft
    service, confirmation keyboard) is the exact same code path a typed
    admin command already used before this phase existed — there is no
    separate voice business-execution branch anywhere below this point.
    """
    if result.command_type is None:
        if result.clarification_required and result.clarification_message:
            await message.answer(uz.AI_CLARIFICATION_NEEDED.format(message=result.clarification_message))
        else:
            await message.answer(uz.AI_NOT_UNDERSTOOD)
        return

    async with pool.acquire() as conn:
        actor = await _load_actor(conn, message.from_user.id)  # type: ignore[union-attr]
        if actor is None:
            return

        # Priority 3: IMAGE + VOICE/TEXT correlation. A caption-attached
        # image (image_file_id already set by the caller) takes priority;
        # otherwise, this text/voice message may be completing an earlier
        # bare photo sent by the *same* admin in the *same* chat within the
        # correlation window — claimed atomically so two messages can never
        # both correlate against the same photo (app/ai/pending_media.py).
        correlated_image_file_id = image_file_id
        if correlated_image_file_id is None and result.command_type == "CREATE_PRODUCT":
            pending = await pending_media.consume(conn, admin_id=actor.id, chat_id=message.chat.id)
            if pending is not None:
                correlated_image_file_id = pending["telegram_file_id"]

        payload = dict(result.payload)
        if correlated_image_file_id is not None and result.command_type == "CREATE_PRODUCT":
            payload["telegram_image_file_id"] = correlated_image_file_id

        try:
            resolved_payload = await resolver.resolve_command_references(conn, result.command_type, payload)
        except resolver.ProductNotFound as exc:
            await message.answer(uz.AI_PRODUCT_NOT_FOUND.format(query=str(exc)))
            return
        except resolver.AmbiguousReference as exc:
            await message.answer(uz.AI_AMBIGUOUS_PRODUCT.format(options=_format_matches(exc.matches)))
            return

        try:
            outcome = await drafts_service.handle_command(
                conn, actor=actor, command_type=result.command_type, raw_payload=resolved_payload, source=source,
            )
        except drafts_service.Forbidden:
            await message.answer(uz.AI_UNAUTHORIZED)
            return
        except (InvalidPayload, UnknownCommand) as exc:
            # brand_id is never guessed for CREATE_PRODUCT (§15/§23 — no
            # invented business data); the stub parser's comma-separated
            # heuristic doesn't extract a brand, so this is the expected,
            # actionable outcome when the admin's message didn't name one.
            if result.command_type == "CREATE_PRODUCT" and "brand_id" in str(exc):
                await message.answer(uz.AI_BRAND_REQUIRED)
            else:
                await message.answer(uz.AI_EXECUTION_FAILED.format(error=str(exc)))
            return

    if outcome["executed"]:
        await message.answer(_format_read_only_result(result.command_type, outcome["result"]))
    else:
        await message.answer(
            f"🤖 {outcome['preview']}",
            reply_markup=keyboards.ai_confirmation_keyboard(outcome["draft_id"]),
        )


@router.message(F.voice, _admin_or_owner)
async def handle_admin_voice(message: Message, pool: asyncpg.Pool, bot: Bot) -> None:
    settings = Settings.from_env()

    if settings.ai_provider == "gemini":
        # §P5.2: native Gemini audio understanding — the configured AI
        # provider interprets the raw audio directly (no separate
        # transcription step/vendor). Still converges into
        # `_handle_structured_result`, the exact same resolver/draft/
        # confirmation/executor pipeline every other input modality uses.
        # Whisper-based transcription (below) remains the path for every
        # other AI_PROVIDER configuration (stub/anthropic/unset) — Whisper
        # is a transcription service, not a text-command interpreter, so
        # it has no bearing on which provider is handling commands.
        await _handle_admin_voice_native_gemini(message, pool, bot, settings)
        return

    stt = get_stt_provider(settings)
    try:
        telegram_file = await bot.get_file(message.voice.file_id)  # type: ignore[union-attr]
        buffer = await bot.download_file(telegram_file.file_path)
        transcript = await stt.transcribe(
            audio_bytes=buffer.read(), mime_type=message.voice.mime_type or "audio/ogg"  # type: ignore[union-attr]
        )
    except ProviderNotConfigured:
        await message.answer(uz.AI_STT_NOT_CONFIGURED)
        return
    except Exception:
        logger.exception("voice transcription failed")
        await message.answer(uz.AI_TRANSCRIPTION_FAILED)
        return

    await _process_ai_text(message, pool, bot, transcript, source="VOICE")


async def _handle_admin_voice_native_gemini(message: Message, pool: asyncpg.Pool, bot: Bot, settings: Settings) -> None:
    logger.info("voice received (native-audio provider path)")
    try:
        audio = await ai_voice.retrieve_voice_audio(
            bot, message.voice, max_bytes=settings.ai_voice_max_bytes  # type: ignore[union-attr]
        )
    except ai_voice.VoiceRetrievalError as exc:
        # Never log/show the raw audio or the raw exception — only that
        # retrieval/validation failed (§14/§15: no raw audio, no internal
        # exception detail, in logs or in the admin-facing message).
        logger.info("voice retrieval failed: %s", type(exc).__name__)
        await message.answer(uz.AI_VOICE_INVALID)
        return

    ai_provider = get_ai_provider(settings)
    try:
        result = await ai_provider.generate_structured_command(audio=audio)
    except Exception:  # ProviderNotConfigured (timeout/429/5xx/malformed/missing key) or anything else
        logger.exception("AI provider call failed (voice)")
        await message.answer(uz.AI_PROVIDER_FAILED)
        return

    logger.info("voice interpreted: command_recognized=%s", result.command_type is not None)
    await _handle_structured_result(message, pool, bot, result, source="VOICE")


@router.message(F.photo, _admin_or_owner)
async def handle_admin_photo(message: Message, pool: asyncpg.Pool, bot: Bot) -> None:
    file_id = message.photo[-1].file_id  # type: ignore[index]

    if message.caption:
        # IMAGE + TEXT in one message — processed immediately, no
        # correlation window needed.
        await _process_ai_text(message, pool, bot, message.caption, source="IMAGE", image_file_id=file_id)
        return

    # IMAGE + VOICE (Priority 3): Telegram cannot attach a photo and a
    # voice note to a single message, so a bare photo opens a short-lived
    # pending-media context instead of being rejected outright. The next
    # VOICE/TEXT message from this same admin, in this same chat, within
    # CORRELATION_WINDOW, is combined with it (see _process_ai_text above).
    # A second bare photo replaces this one rather than stacking.
    async with pool.acquire() as conn:
        actor = await _load_actor(conn, message.from_user.id)  # type: ignore[union-attr]
        if actor is None:
            return
        await pending_media.create_or_replace(conn, admin_id=actor.id, chat_id=message.chat.id, telegram_file_id=file_id)

    await message.answer(uz.AI_PHOTO_AWAITING_DESCRIPTION)


_SYSTEM_COMMAND_PREFIX = "/"


@router.message(F.text, _admin_or_owner)
async def handle_admin_text(message: Message, pool: asyncpg.Pool, bot: Bot) -> None:
    text = message.text or ""
    if text.startswith(_SYSTEM_COMMAND_PREFIX):
        return  # let bot commands (e.g. /start) be handled elsewhere
    await _process_ai_text(message, pool, bot, text, source="TEXT")


@router.callback_query(F.data.startswith("ai_confirm:"))
async def handle_ai_confirm(callback: CallbackQuery, pool: asyncpg.Pool, bot: Bot) -> None:
    if callback.from_user is None or callback.data is None:
        return
    draft_id = int(callback.data.split(":", 1)[1])

    async with pool.acquire() as conn:
        actor = await _load_actor(conn, callback.from_user.id)
        if actor is None:
            await callback.answer(uz.AI_UNAUTHORIZED, show_alert=True)
            return

        draft = await drafts_repository.get_draft(conn, draft_id=draft_id)
        if draft is None:
            await callback.answer(uz.AI_DRAFT_NOT_FOUND, show_alert=True)
            return

        try:
            result = await drafts_service.confirm(
                conn, draft_id=draft_id, confirmation_token=draft["confirmation_token"], actor=actor, bot=bot,
            )
        except drafts_service.DraftNotOwnedByCaller:
            await callback.answer(uz.AI_NOT_YOUR_DRAFT, show_alert=True)
            return
        except drafts_service.DraftExpired:
            await callback.answer(uz.AI_DRAFT_EXPIRED, show_alert=True)
            if callback.message is not None:
                await callback.message.edit_reply_markup(reply_markup=None)
            return
        except drafts_service.DraftNotPending:
            # Covers the double-tap / duplicate-callback case: the second
            # tap sees status != PENDING and is rejected cleanly, not
            # executed twice.
            await callback.answer(uz.AI_ALREADY_HANDLED, show_alert=True)
            if callback.message is not None:
                await callback.message.edit_reply_markup(reply_markup=None)
            return
        except drafts_service.Forbidden:
            await callback.answer(uz.AI_PERMISSION_REVOKED, show_alert=True)
            return
        except Exception as exc:  # noqa: BLE001 — surfaced to the admin, not a crash
            logger.exception("AI draft confirm failed")
            await callback.answer(uz.AI_EXECUTION_FAILED.format(error=str(exc)), show_alert=True)
            if callback.message is not None:
                await callback.message.edit_reply_markup(reply_markup=None)
            return

    if callback.message is not None:
        await callback.message.edit_text(_format_read_only_result(result["command_type"], result["result"]))
    await callback.answer()


@router.callback_query(F.data.startswith("ai_cancel:"))
async def handle_ai_cancel(callback: CallbackQuery, pool: asyncpg.Pool) -> None:
    if callback.from_user is None or callback.data is None:
        return
    draft_id = int(callback.data.split(":", 1)[1])

    async with pool.acquire() as conn:
        actor = await _load_actor(conn, callback.from_user.id)
        if actor is None:
            await callback.answer(uz.AI_UNAUTHORIZED, show_alert=True)
            return
        try:
            await drafts_service.cancel(conn, draft_id=draft_id, actor=actor)
        except drafts_service.DraftNotFound:
            await callback.answer(uz.AI_DRAFT_NOT_FOUND, show_alert=True)
            return
        except drafts_service.DraftNotOwnedByCaller:
            await callback.answer(uz.AI_NOT_YOUR_DRAFT, show_alert=True)
            return
        except drafts_service.DraftNotPending:
            await callback.answer(uz.AI_ALREADY_HANDLED, show_alert=True)
            if callback.message is not None:
                await callback.message.edit_reply_markup(reply_markup=None)
            return

    if callback.message is not None:
        await callback.message.edit_text(uz.AI_CANCELLED)
    await callback.answer()


@router.callback_query(F.data.startswith("ai_edit:"))
async def handle_ai_edit(callback: CallbackQuery, pool: asyncpg.Pool) -> None:
    """No in-place edit UI this pass — cancels the draft (so it can never
    be confirmed with stale values) and asks the admin to resend the
    corrected command, which starts a brand new draft. Honest about not
    doing field-level editing rather than faking it."""
    if callback.from_user is None or callback.data is None:
        return
    draft_id = int(callback.data.split(":", 1)[1])

    async with pool.acquire() as conn:
        actor = await _load_actor(conn, callback.from_user.id)
        if actor is None:
            await callback.answer(uz.AI_UNAUTHORIZED, show_alert=True)
            return
        try:
            await drafts_service.cancel(conn, draft_id=draft_id, actor=actor)
        except (drafts_service.DraftNotFound, drafts_service.DraftNotOwnedByCaller, drafts_service.DraftNotPending):
            pass  # already gone — falls through to the same edit prompt regardless

    if callback.message is not None:
        await callback.message.edit_text(uz.AI_EDIT_PROMPT)
    await callback.answer()
