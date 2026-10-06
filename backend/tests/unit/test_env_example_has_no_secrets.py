"""Regression: `.env.example` must contain placeholders only, and must stay
in sync with the variables the code actually reads.

A real, live BotFather token was committed in this file and was only caught
by a manual audit (confirmed live via a read-only Telegram `getMe`). The
file's own header had said "never a real secret" the whole time — prose
alone did not prevent it, so this test enforces it mechanically.

It also catches the class of corruption previously seen in this same file,
where a bulk find/replace spliced a placeholder into the middle of an
unrelated word ("...own runCHANGE_ME:test-bot-token-placeholderning .env").
"""
from __future__ import annotations

import re
from pathlib import Path

ENV_EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"

# BotFather tokens look like `<8-12 digit bot id>:<35-char secret>`.
TELEGRAM_TOKEN_RE = re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{30,}\b")

# Every variable the application, bot, migrations or deploy scripts read.
# Keeping this list here means adding a new required env var without
# documenting it in .env.example fails the test suite.
REQUIRED_KEYS = {
    "DATABASE_URL",
    "BOT_TOKEN",
    "SESSION_SECRET",
    "SIGNING_SECRET",
    "TELEGRAM_WEBHOOK_SECRET",
    "OWNER_TELEGRAM_ID",
    "MINIAPP_URL",
    "UPLOADS_ROOT",
    "ALLOWED_ORIGINS",
    "LOG_LEVEL",
    "MIGRATION_DATABASE_URL",
}

SECRET_KEYS = {
    "BOT_TOKEN",
    "SESSION_SECRET",
    "SIGNING_SECRET",
    "TELEGRAM_WEBHOOK_SECRET",
}


def _content() -> str:
    return ENV_EXAMPLE.read_text(encoding="utf-8")


def _assignments(text: str) -> dict[str, str]:
    """Every KEY=VALUE, including ones commented out with a leading `#`."""
    found = {}
    for line in text.splitlines():
        stripped = line.lstrip("#").strip()
        if "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        if key.isupper() and key.replace("_", "").isalnum():
            found[key] = value.strip()
    return found


def test_no_real_telegram_bot_token():
    match = TELEGRAM_TOKEN_RE.search(_content())
    # Deliberately does not print the match — a failure must not leak the
    # secret into CI logs.
    assert match is None, (
        ".env.example contains something shaped like a real BotFather token. "
        "Replace it with a placeholder and rotate the token via @BotFather — "
        "committing it means it is disclosed, not configured."
    )


def test_secret_values_are_placeholders():
    assignments = _assignments(_content())
    for key in SECRET_KEYS:
        value = assignments.get(key, "")
        assert "CHANGE_ME" in value, (
            f"{key} in .env.example must be a CHANGE_ME placeholder, not a real value."
        )


def test_owner_telegram_id_is_not_a_real_account():
    value = _assignments(_content()).get("OWNER_TELEGRAM_ID", "")
    assert set(value) <= {"0"} and value, (
        "OWNER_TELEGRAM_ID in .env.example must stay an all-zero placeholder — "
        "it is a real person's Telegram account id."
    )


def test_every_required_key_is_documented():
    missing = REQUIRED_KEYS - set(_assignments(_content()))
    assert not missing, f".env.example is missing required variables: {sorted(missing)}"


def test_no_placeholder_spliced_into_a_word():
    """`CHANGE_ME` must only ever appear as a value, never glued inside an
    identifier or an English word by a careless bulk replace."""
    bad = re.findall(r"[A-Za-z]CHANGE_ME|CHANGE_ME[a-z]", _content())
    assert not bad, f"placeholder spliced into surrounding text: {bad}"
