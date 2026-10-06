"""§P5.1 — a validated, minimal internal representation of an admin's
voice-command audio. Deliberately small: only what
`app/ai/providers/*.py` actually needs (bytes + a canonical MIME type [+
an optional, sanitized filename]) — no duration/sample-rate/codec metadata
that nothing downstream reads.

Follows the same "sniff, don't trust metadata" convention
`app/security/uploads.py` already established for image uploads
(magic-byte check, a dedicated `Invalid*` exception, a module-level
`MAX_*_BYTES` constant) rather than inventing a parallel validation style.
"""
from __future__ import annotations

from dataclasses import dataclass

# Telegram voice notes (`message.voice`, distinct from `message.audio`
# file uploads) are always an OGG container with Opus-encoded audio — the
# only format this phase supports, matching §10 of the brief ("optimized
# for short voice commands", not a general audio-upload feature).
# `audio/ogg` is the only canonical MIME this module ever returns; any
# other client-asserted MIME hint is rejected outright rather than
# silently reinterpreted.
CANONICAL_MIME_TYPE = "audio/ogg"

# Telegram/clients report slightly different strings for the same OGG/Opus
# container depending on platform — normalized to CANONICAL_MIME_TYPE once
# accepted. Still only ever a *hint*: the magic-byte check below is the
# actual enforcement boundary, per §6 "do NOT trust MIME type supplied by
# the client blindly."
_ACCEPTED_MIME_HINTS = {"audio/ogg", "audio/ogg; codecs=opus", "audio/opus", "application/ogg", "audio/x-ogg"}

# OGG container magic bytes ("OggS") — every OGG file (Opus or otherwise)
# starts with this, regardless of what the client claims its MIME type is.
_OGG_MAGIC = b"OggS"

# §10 of the brief: "this infrastructure should be optimized for short
# voice commands rather than long recordings." Telegram voice notes encode
# at a low Opus bitrate (roughly 16-32 kbps mono for speech) — even a
# generous 4-minute ceiling fits well under 1 MB. 1,000,000 bytes is a
# conservative, deliberately explicit bound (not an arbitrary round
# number): generous for any realistic short admin command, while still
# bounding worst-case payload size/cost. Configurable via AI_VOICE_MAX_BYTES
# (app/config.py) if real-world recordings run longer than expected.
DEFAULT_MAX_VOICE_BYTES = 1_000_000

_MAX_FILENAME_LENGTH = 128
_UNSAFE_FILENAME_CHARS = "\x00\r\n"


class InvalidAudioInput(Exception):
    """Rejected audio — empty, oversized, wrong container, mismatched
    MIME hint, or an unsafe filename. Callers map this to a safe,
    actionable message — never a raw exception shown to the admin. Same
    role as `app.security.uploads.InvalidUpload`."""


def _safe_filename(filename: str | None) -> str | None:
    """Only used if a filename is actually retained (§6) — Telegram voice
    notes themselves carry no filename field, so this exists for the
    general `AudioInput` abstraction (e.g. a future `message.audio` path),
    not today's voice-note handler specifically."""
    if filename is None:
        return None
    # Strip any path component — never trust a client-supplied path.
    name = filename.strip().replace("\\", "/").rsplit("/", 1)[-1]
    if not name or name in (".", ".."):
        raise InvalidAudioInput("unsafe or empty filename")
    if len(name) > _MAX_FILENAME_LENGTH:
        raise InvalidAudioInput("filename too long")
    if any(ch in name for ch in _UNSAFE_FILENAME_CHARS):
        raise InvalidAudioInput("filename contains unsafe characters")
    return name


@dataclass(frozen=True)
class AudioInput:
    """The only shape `AIProvider.generate_structured_command`'s `audio`
    parameter ever carries. `mime_type` is always `CANONICAL_MIME_TYPE`
    once constructed via `from_bytes` — there is no other way to build one
    with a validated payload, short of a test deliberately bypassing
    validation."""

    data: bytes
    mime_type: str
    filename: str | None = None

    @classmethod
    def from_bytes(
        cls,
        data: bytes,
        *,
        mime_type_hint: str | None = None,
        filename: str | None = None,
        max_bytes: int = DEFAULT_MAX_VOICE_BYTES,
    ) -> "AudioInput":
        """Validates `data` as a real OGG container by its own bytes —
        `mime_type_hint` (from Telegram's `Voice.mime_type` or any other
        client-reported metadata) is cross-checked against that, never
        trusted alone (§6/§10: "Telegram metadata does not bypass
        validation" / "do NOT silently reinterpret arbitrary binary files
        as audio")."""
        if not data:
            raise InvalidAudioInput("audio is empty")
        if len(data) > max_bytes:
            raise InvalidAudioInput(f"audio exceeds the {max_bytes}-byte limit")
        if not data.startswith(_OGG_MAGIC):
            raise InvalidAudioInput("audio is not a recognized OGG container (magic-byte check failed)")
        if mime_type_hint is not None and mime_type_hint.strip().lower() not in _ACCEPTED_MIME_HINTS:
            raise InvalidAudioInput(f"unsupported MIME type: {mime_type_hint!r}")

        return cls(data=data, mime_type=CANONICAL_MIME_TYPE, filename=_safe_filename(filename))
