"""§P5.1: unit tests for app/ai/voice.py's retrieve_voice_audio — mocked
Telegram bot, no real network/Telegram connection. Mirrors the mocking
style already used for the existing voice path in
tests/unit/test_ai_bot_handlers.py (bot.get_file/bot.download_file as
AsyncMocks).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.ai.audio import CANONICAL_MIME_TYPE
from app.ai.voice import VoiceRetrievalError, retrieve_voice_audio

pytestmark = pytest.mark.asyncio

_VALID_OGG = b"OggS" + b"\x00" * 64


def _voice(file_id="v1", mime_type="audio/ogg"):
    return MagicMock(file_id=file_id, mime_type=mime_type)


def _bot(file_path="voice.ogg", audio_bytes=_VALID_OGG, get_file_error=None, download_error=None):
    bot = MagicMock()
    if get_file_error is not None:
        bot.get_file = AsyncMock(side_effect=get_file_error)
    else:
        bot.get_file = AsyncMock(return_value=MagicMock(file_path=file_path))
    if download_error is not None:
        bot.download_file = AsyncMock(side_effect=download_error)
    else:
        buffer = MagicMock()
        buffer.read.return_value = audio_bytes
        bot.download_file = AsyncMock(return_value=buffer)
    return bot


async def test_voice_message_is_detected_and_retrieved():
    bot = _bot()
    audio = await retrieve_voice_audio(bot, _voice(), max_bytes=1_000_000)

    assert audio.data == _VALID_OGG
    assert audio.mime_type == CANONICAL_MIME_TYPE
    bot.get_file.assert_awaited_once_with("v1")


async def test_telegram_file_is_downloaded_via_existing_bot_methods():
    bot = _bot(file_path="voices/abc.ogg")
    await retrieve_voice_audio(bot, _voice(), max_bytes=1_000_000)

    bot.download_file.assert_awaited_once_with("voices/abc.ogg")


async def test_no_file_id_rejected():
    bot = _bot()
    with pytest.raises(VoiceRetrievalError, match="file_id"):
        await retrieve_voice_audio(bot, _voice(file_id=None), max_bytes=1_000_000)
    bot.get_file.assert_not_awaited()


async def test_missing_file_path_from_telegram_rejected():
    bot = MagicMock()
    bot.get_file = AsyncMock(return_value=MagicMock(file_path=None))
    bot.download_file = AsyncMock()
    with pytest.raises(VoiceRetrievalError, match="file_path"):
        await retrieve_voice_audio(bot, _voice(), max_bytes=1_000_000)
    bot.download_file.assert_not_awaited()


async def test_telegram_get_file_failure_is_handled_safely():
    bot = _bot(get_file_error=ConnectionError("network down"))
    with pytest.raises(VoiceRetrievalError, match="lookup failed"):
        await retrieve_voice_audio(bot, _voice(), max_bytes=1_000_000)


async def test_telegram_download_failure_is_handled_safely():
    bot = _bot(download_error=TimeoutError("timed out"))
    with pytest.raises(VoiceRetrievalError, match="download failed"):
        await retrieve_voice_audio(bot, _voice(), max_bytes=1_000_000)


async def test_oversized_audio_rejected_without_bypassing_validation():
    bot = _bot(audio_bytes=b"OggS" + b"\x00" * 5000)
    with pytest.raises(VoiceRetrievalError, match="exceeds"):
        await retrieve_voice_audio(bot, _voice(), max_bytes=1000)


async def test_telegram_metadata_mime_claim_does_not_bypass_byte_validation():
    """Telegram's own `Voice.mime_type` claims audio/ogg, but the actual
    downloaded bytes are not an OGG container — must still be rejected."""
    bot = _bot(audio_bytes=b"not-really-audio-at-all")
    with pytest.raises(VoiceRetrievalError, match="OGG container"):
        await retrieve_voice_audio(bot, _voice(mime_type="audio/ogg"), max_bytes=1_000_000)


async def test_unsupported_client_asserted_mime_rejected():
    bot = _bot()
    with pytest.raises(VoiceRetrievalError, match="unsupported MIME"):
        await retrieve_voice_audio(bot, _voice(mime_type="video/mp4"), max_bytes=1_000_000)


async def test_empty_audio_rejected():
    bot = _bot(audio_bytes=b"")
    with pytest.raises(VoiceRetrievalError, match="empty"):
        await retrieve_voice_audio(bot, _voice(), max_bytes=1_000_000)


async def test_no_temporary_file_is_created_or_left_behind(tmp_path, monkeypatch):
    """§8: 'download to memory ... cleanup' — this module never writes to
    disk at all, so there is nothing to clean up. Verified by asserting
    no new file appears under a scratch directory while the function
    runs (a stand-in for 'no leaked temp file'), and more directly by
    confirming the module imports no filesystem/tempfile APIs at runtime
    for this path."""
    import app.ai.voice as voice_module

    assert not hasattr(voice_module, "tempfile")
    assert not hasattr(voice_module, "NamedTemporaryFile")

    before = set(tmp_path.iterdir())
    bot = _bot()
    await retrieve_voice_audio(bot, _voice(), max_bytes=1_000_000)
    after = set(tmp_path.iterdir())
    assert before == after
