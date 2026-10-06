from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from aiogram import Bot
from fastapi import FastAPI

from app.config import Settings
from app.cors import install_cors
from app.db.pool import close_pool, create_pool
from app.domains.catalog.admin_router import router as catalog_admin_router
from app.domains.catalog.router import router as catalog_router
from app.ai.router import router as ai_router
from app.domains.commerce.cancellations.router import router as cancellations_router
from app.domains.commerce.cart.router import router as cart_router
from app.domains.commerce.orders.router import router as orders_router
from app.domains.commerce.refunds.router import router as refunds_router
from app.domains.identity.router import router as identity_router
from app.domains.owner.router import router as owner_router
from app.domains.payments.router import router as payments_router
from app.domains.pricing.admin_router import router as pricing_admin_router
from app.domains.vehicle.router import router as vehicle_router
from app.health import router as health_router
from app.observability import configure_logging, install_exception_handling
from bot.config import BotSettings
from bot.main import build_dispatcher, build_webhook_router, configure_bot, run_notification_poller_forever

logger = logging.getLogger("comfort")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings.from_env()
    pool = await create_pool(settings.database_url)

    # ADR-1: the bot is a thin client of the same FastAPI process/Service
    # layer as the Mini App — not a second process, per bot/main.py's own
    # docstring. Wired here (not at import time) so importing app.main
    # never requires bot-specific env vars to be set — every existing test
    # constructs the app without ever running this lifespan (they call
    # create_pool/close_pool directly instead), so this addition changes
    # nothing about what env vars a test needs.
    bot_settings = BotSettings.from_env()
    bot = Bot(token=bot_settings.bot_token)
    dispatcher = build_dispatcher(pool=pool, miniapp_url=bot_settings.miniapp_url)
    app.include_router(
        build_webhook_router(bot=bot, dispatcher=dispatcher, webhook_secret=bot_settings.webhook_secret)
    )
    try:
        await configure_bot(bot, miniapp_url=bot_settings.miniapp_url)
    except Exception:
        # A Telegram API hiccup at startup (rate limit, transient network
        # issue) must not take the whole HTTP API down with it — the Menu
        # Button can be (re)configured on a later restart.
        logger.exception("configure_bot failed at startup — continuing without it")

    poller_task = asyncio.create_task(run_notification_poller_forever(pool, bot))

    yield

    poller_task.cancel()
    try:
        await poller_task
    except asyncio.CancelledError:
        pass
    await bot.session.close()
    await close_pool()


configure_logging()

app = FastAPI(title="COMFORT UZB API", lifespan=lifespan)
install_exception_handling(app)
install_cors(app)

app.include_router(health_router)
app.include_router(identity_router)
app.include_router(catalog_router)
app.include_router(catalog_admin_router)
app.include_router(vehicle_router)
app.include_router(cart_router)
app.include_router(orders_router)
app.include_router(cancellations_router)
app.include_router(refunds_router)
app.include_router(payments_router)
app.include_router(owner_router)
app.include_router(pricing_admin_router)
app.include_router(ai_router)
