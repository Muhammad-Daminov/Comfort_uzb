"""§P5.1: unit tests for app/ai/audio.py's AudioInput — the validated,
minimal internal representation of voice-command audio. No network, no
DB, no Telegram — pure validation logic.
"""
from __future__ import annotations

import pytest

from app.ai.audio import CANONICAL_MIME_TYPE, AudioInput, InvalidAudioInput

_VALID_OGG = b"OggS" + b"\x00" * 64


def test_valid_ogg_audio_is_accepted():
    audio = AudioInput.from_bytes(_VALID_OGG, mime_type_hint="audio/ogg")
    assert audio.data == _VALID_OGG
    assert audio.mime_type == CANONICAL_MIME_TYPE
    assert audio.filename is None


def test_valid_audio_accepted_without_mime_hint():
    """The magic-byte check is the actual enforcement boundary — a missing
    hint must not be treated as a rejection, only an untrusted one."""
    audio = AudioInput.from_bytes(_VALID_OGG)
    assert audio.mime_type == CANONICAL_MIME_TYPE


def test_empty_audio_rejected():
    with pytest.raises(InvalidAudioInput, match="empty"):
        AudioInput.from_bytes(b"", mime_type_hint="audio/ogg")


def test_non_ogg_binary_rejected_even_with_correct_mime_hint():
    """§10: 'do NOT silently reinterpret arbitrary binary files as audio.'
    A claimed audio/ogg MIME on non-OGG bytes must still be rejected — the
    hint alone never grants trust."""
    not_audio = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32  # a PNG magic header
    with pytest.raises(InvalidAudioInput, match="OGG container"):
        AudioInput.from_bytes(not_audio, mime_type_hint="audio/ogg")


def test_unsupported_mime_hint_rejected_even_on_valid_ogg_bytes():
    with pytest.raises(InvalidAudioInput, match="unsupported MIME type"):
        AudioInput.from_bytes(_VALID_OGG, mime_type_hint="video/mp4")


def test_oversized_audio_rejected():
    big = b"OggS" + b"\x00" * 100
    with pytest.raises(InvalidAudioInput, match="exceeds"):
        AudioInput.from_bytes(big, mime_type_hint="audio/ogg", max_bytes=50)


def test_audio_at_exactly_the_limit_is_accepted():
    data = b"OggS" + b"\x00" * 46  # exactly 50 bytes
    assert len(data) == 50
    audio = AudioInput.from_bytes(data, max_bytes=50)
    assert len(audio.data) == 50


def test_telegram_reported_file_size_does_not_bypass_byte_level_validation():
    """§6/§10: 'Telegram metadata does not bypass validation.' Even if a
    caller believed (from Voice.file_size, not passed to this function at
    all) that the audio was small, the function must still measure and
    reject based on the real downloaded byte length — simulated here by
    simply passing oversized real bytes regardless of any claimed size."""
    oversized = b"OggS" + b"\x00" * 1000
    with pytest.raises(InvalidAudioInput):
        AudioInput.from_bytes(oversized, mime_type_hint="audio/ogg", max_bytes=100)


@pytest.mark.parametrize("hint", ["audio/ogg", "AUDIO/OGG", "audio/opus", "application/ogg", "audio/ogg; codecs=opus"])
def test_accepted_mime_hint_variants(hint):
    audio = AudioInput.from_bytes(_VALID_OGG, mime_type_hint=hint)
    assert audio.mime_type == CANONICAL_MIME_TYPE


def test_safe_filename_is_preserved():
    audio = AudioInput.from_bytes(_VALID_OGG, filename="voice.ogg")
    assert audio.filename == "voice.ogg"


def test_path_traversal_filename_is_sanitized_to_basename():
    audio = AudioInput.from_bytes(_VALID_OGG, filename="../../etc/passwd")
    assert audio.filename == "passwd"


def test_filename_with_null_byte_rejected():
    with pytest.raises(InvalidAudioInput, match="unsafe"):
        AudioInput.from_bytes(_VALID_OGG, filename="voice\x00.ogg")


def test_empty_filename_after_sanitization_rejected():
    with pytest.raises(InvalidAudioInput):
        AudioInput.from_bytes(_VALID_OGG, filename="../")


def test_overly_long_filename_rejected():
    with pytest.raises(InvalidAudioInput, match="too long"):
        AudioInput.from_bytes(_VALID_OGG, filename="a" * 200 + ".ogg")


def test_audio_input_is_frozen():
    audio = AudioInput.from_bytes(_VALID_OGG)
    with pytest.raises(Exception):
        audio.data = b"different"  # type: ignore[misc]
