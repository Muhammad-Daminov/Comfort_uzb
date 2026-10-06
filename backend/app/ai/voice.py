"""§P5.1 — Telegram voice retrieval + normalization: the missing piece
between a `message.voice` and an `AudioInput` the AI provider layer can
accept.

This module is infrastructure only. It does not call `app/ai/resolver.py`,
`app/ai/drafts/service.py`, or `app/ai/executor.py`, and it is NOT wired
into `bot/handlers/ai.py`'s live `@router.message(F.voice, ...)` handler.
That handler already has its own, independently-shipped, working voice
path (`Telegram voice -> OpenAI Whisper STT -> the ordinary text command
pipeline -> draft/confirm`) — see `handle_admin_voice`'s own docstring
context; this module does not touch it. Deciding whether/how to route live
Telegram voice traffic through this new native-audio capability instead
of (or alongside) that existing STT path is explicitly out of scope for
this phase (§23 of the brief: "P5.1 must NOT allow Voice -> Gemini -> DB
mutation" — nothing here can reach the database at all).

What this module *does* prove, safely and in isolation: Telegram voice
message -> downloaded, size-limited, magic-byte-validated audio ->
`AudioInput` -> `AIProvider.generate_structured_command(audio=...)` ->
`StructuredCommandResult`, fully testable without a live Telegram
connection or a database.
"""
from __future__ import annotations

import logging

from app.ai.audio import AudioInput, InvalidAudioInput

logger = logging.getLogger(__name__)


class VoiceRetrievalError(Exception):
    """Telegram-side failure retrieving or validating a voice message —
    callers must show the admin a safe, actionable message, never a raw
    exception. Covers: no file_id, Telegram download failure, and any
    `InvalidAudioInput` rejection (empty/oversized/wrong-container/
    mismatched-MIME audio)."""


async def retrieve_voice_audio(bot, voice, *, max_bytes: int) -> AudioInput:
    """Steps 1-6 of the brief's §7 (detection itself is the caller's own
    `message.voice` check/router filter — not duplicated here): obtain the
    Telegram file_id, download the actual bytes (never store them to
    disk — in-memory only, per §8's "download to memory ... cleanup"
    preference; there is no temp file to leak or to clean up), enforce the
    max size, normalize/validate the MIME type, and construct the
    `AudioInput`.

    Never trusts `voice.mime_type` or `voice.file_size` metadata alone —
    `AudioInput.from_bytes` measures and magic-byte-sniffs the actual
    downloaded bytes; a client that reports a small `file_size` or a
    plausible-looking `mime_type` for content that isn't really a small
    OGG file is still rejected (§6/§10 "Telegram metadata does not bypass
    validation").
    """
    file_id = getattr(voice, "file_id", None)
    if not file_id:
        raise VoiceRetrievalError("voice message has no file_id")

    try:
        telegram_file = await bot.get_file(file_id)
    except Exception as exc:  # aiogram/network failure — never leak the raw exception upward
        logger.warning("Telegram get_file failed: %s", type(exc).__name__)
        raise VoiceRetrievalError(f"Telegram file lookup failed: {type(exc).__name__}") from exc

    file_path = getattr(telegram_file, "file_path", None) if telegram_file is not None else None
    if not file_path:
        raise VoiceRetrievalError("Telegram returned no file_path for this voice message")

    try:
        buffer = await bot.download_file(file_path)
    except Exception as exc:
        logger.warning("Telegram download_file failed: %s", type(exc).__name__)
        raise VoiceRetrievalError(f"Telegram file download failed: {type(exc).__name__}") from exc

    data = buffer.read()
    # Never log `data` itself (raw admin audio) — only its length, which is
    # already safe/non-sensitive and useful for debugging oversized
    # rejections.
    try:
        return AudioInput.from_bytes(
            data, mime_type_hint=getattr(voice, "mime_type", None), max_bytes=max_bytes
        )
    except InvalidAudioInput as exc:
        logger.info("rejected voice audio (%d bytes): %s", len(data), exc)
        raise VoiceRetrievalError(str(exc)) from exc
