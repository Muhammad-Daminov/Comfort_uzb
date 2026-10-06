"""Env-driven bot settings — same fail-loudly convention as `app/config.py`."""
from __future__ import annotations

import os
from dataclasses import dataclass


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} environment variable is required but not set")
    return value


@dataclass(frozen=True)
class BotSettings:
    bot_token: str
    database_url: str
    miniapp_url: str
    webhook_secret: str

    @classmethod
    def from_env(cls) -> "BotSettings":
        return cls(
            bot_token=_required("BOT_TOKEN"),
            database_url=_required("DATABASE_URL"),
            miniapp_url=_required("MINIAPP_URL"),
            webhook_secret=_required("TELEGRAM_WEBHOOK_SECRET"),
        )
