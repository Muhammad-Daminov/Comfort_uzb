"""Maps handler-level exceptions to safe, generic Uzbek responses. Telegram
users must never see a Python traceback, a Postgres error, or any internal
detail (Phase-04 error-handling requirement) — this is the last line of
defense for anything a handler's own try/except didn't already catch.
"""
from __future__ import annotations

import logging

from aiogram import Router
from aiogram.types import ErrorEvent

from bot.locales import uz

logger = logging.getLogger(__name__)

router = Router(name="errors")


@router.errors()
async def handle_unexpected_error(event: ErrorEvent) -> bool:
    logger.exception("unhandled exception in update handler", exc_info=event.exception)
    update = event.update
    message = getattr(update, "message", None)
    if message is not None:
        try:
            await message.answer(uz.GENERIC_ERROR)
        except Exception:  # noqa: BLE001 — best-effort; never let error reporting itself crash
            logger.exception("failed to send generic error message to user")
    return True
