"""Bot process wiring: aiogram `Bot`/`Dispatcher`, webhook route (mounted
into the same FastAPI app the Mini App API uses — ADR-1: "Butun tizim
bitta VPS da... bir xil Service qatlami", one system, same Service layer),
and the notification poller's lifecycle. Nginx-level webhook proxying is
`devops`'s job (Phase-09); this module owns the application-side route and
dispatch only, per `AGENTS/bot.md`'s "Webhook endpoint wiring (Nginx ->
aiogram, §17.2)" responsibility.
"""
from __future__ import annotations

import asyncio
import hmac
import logging

import asyncpg
from aiogram import Bot, Dispatcher
from aiogram.types import Update
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import ValidationError

from bot import errors as error_handlers
from bot import keyboards
from bot.config import BotSettings
from bot.handlers import ai as ai_handlers
from bot.handlers import start as start_handlers
from bot.notifications.poller import poll_loop

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 5


def build_dispatcher(*, pool: asyncpg.Pool, miniapp_url: str) -> Dispatcher:
    dispatcher = Dispatcher()
    dispatcher.include_router(start_handlers.router)
    dispatcher.include_router(ai_handlers.router)
    dispatcher.include_router(error_handlers.router)
    # aiogram injects workflow_data entries into handlers whose parameter
    # names match — this is how handlers reach the connection pool and
    # config without importing bot-global state directly (testable via
    # plain function calls, per the plan's unit-test approach).
    dispatcher["pool"] = pool
    dispatcher["miniapp_url"] = miniapp_url
    return dispatcher


def build_webhook_router(*, bot: Bot, dispatcher: Dispatcher, webhook_secret: str) -> APIRouter:
    router = APIRouter(tags=["bot-webhook"])

    @router.post("/telegram/webhook")
    async def telegram_webhook(
        request: Request,
        x_telegram_bot_api_secret_token: str | None = Header(default=None),
    ) -> dict:
        # Confirms the request genuinely came from Telegram before
        # dispatching anything — the bot-webhook equivalent of ADR-2's
        # trust boundary (a different mechanism, same purpose: never trust
        # an update without verifying its origin first).
        if not hmac.compare_digest(x_telegram_bot_api_secret_token or "", webhook_secret):
            raise HTTPException(status_code=401, detail="invalid webhook secret")

        try:
            body = await request.json()
            update = Update.model_validate(body)
        except (ValueError, ValidationError) as exc:
            # A body that is not JSON / not a Telegram Update is bad input
            # from whoever holds the secret, not a server fault — it used to
            # surface as an unhandled 500.
            raise HTTPException(status_code=400, detail="malformed update") from exc
        await dispatcher.feed_update(bot, update)
        return {"ok": True}

    return router


async def configure_bot(bot: Bot, *, miniapp_url: str) -> None:
    """One-time setup: Menu Button -> Mini App (ADR-1's bot entry point)."""
    await bot.set_chat_menu_button(menu_button=keyboards.miniapp_menu_button(miniapp_url))


async def run_notification_poller_forever(pool: asyncpg.Pool, bot: Bot) -> None:
    """The in-process outbox poll loop (ADR-016) — runs for the lifetime of
    the bot process, not a separate systemd timer (Phase-09 unaffected)."""
    while True:
        try:
            async with pool.acquire() as conn:
                await poll_loop(conn, bot)
        except Exception:  # noqa: BLE001 — a poll-loop crash must not kill the bot process
            logger.exception("notification poll loop iteration failed")
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
