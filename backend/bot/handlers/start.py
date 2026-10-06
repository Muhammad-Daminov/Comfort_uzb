"""`/start` handler, phone-capture flow, blocked-user re-activation
(ADR-12) — the entirety of Phase-04's onboarding deliverable. No business
logic: every mutation goes through `app.domains.identity.service`, the same
functions the Mini App's `/auth/session` path already uses.
"""
from __future__ import annotations

import logging

import asyncpg
from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from app.domains.identity import repository as identity_repository
from app.domains.identity import service as identity_service
from bot import keyboards
from bot.locales import uz

logger = logging.getLogger(__name__)

router = Router(name="start")


@router.message(CommandStart())
async def handle_start(message: Message, pool: asyncpg.Pool, miniapp_url: str) -> None:
    telegram_user = message.from_user
    if telegram_user is None:
        return  # not a user-initiated update; nothing to onboard

    async with pool.acquire() as conn:
        user = await identity_service.get_or_create_user_from_telegram(
            conn,
            telegram_id=telegram_user.id,
            first_name=telegram_user.first_name,
            last_name=telegram_user.last_name,
            username=telegram_user.username,
        )
        # ADR-12: pressing /start again is the documented signal that the
        # bot is no longer blocked — clear it unconditionally (guarded,
        # no-op if it wasn't set).
        was_reactivated = await identity_service.clear_bot_blocked(conn, telegram_id=telegram_user.id)

        profile = await identity_repository.get_by_id(conn, user_id=user["id"])
        has_phone = profile is not None and profile["phone"] is not None

    if was_reactivated:
        await message.answer(uz.BLOCKED_USER_WELCOME_BACK, reply_markup=keyboards.remove_keyboard())

    if has_phone:
        await message.answer(uz.WELCOME_BACK, reply_markup=keyboards.remove_keyboard())
    else:
        await message.answer(uz.WELCOME_NEW_USER, reply_markup=keyboards.phone_request_keyboard())


@router.message(F.contact)
async def handle_contact(message: Message, pool: asyncpg.Pool) -> None:
    telegram_user = message.from_user
    contact = message.contact
    if telegram_user is None or contact is None:
        return

    # Never trust a forwarded contact for someone else — only accept the
    # sender's own contact card, matching "never trust an ID that merely
    # appears in message content" (this is a Telegram-level self-share
    # signal, but still verified against the authenticated sender). A card
    # with no `user_id` at all is an address-book entry for someone who is
    # not on Telegram — never the sender's own number, so it is rejected
    # too (it used to slip through the old `is not None and` guard).
    if contact.user_id != telegram_user.id:
        await message.answer(uz.PHONE_INVALID, reply_markup=keyboards.remove_keyboard())
        return

    await _save_phone(message, pool, contact.phone_number)


_TYPED_PHONE = F.text.regexp(r"^\s*\+?\s*998[\d\s\-()]{9,}$")


@router.message(_TYPED_PHONE)
async def handle_typed_phone(message: Message, pool: asyncpg.Pool) -> None:
    """`uz.PHONE_INVALID` tells the user they may type the number in
    `+998XX XXX XX XX` format — this handler is what makes that true
    (there was none: typed numbers were silently ignored)."""
    if message.from_user is None or message.text is None:
        return
    await _save_phone(message, pool, message.text)


async def _save_phone(message: Message, pool: asyncpg.Pool, raw_phone: str) -> None:
    telegram_user = message.from_user
    assert telegram_user is not None
    async with pool.acquire() as conn:
        user = await identity_service.get_or_create_user_from_telegram(
            conn,
            telegram_id=telegram_user.id,
            first_name=telegram_user.first_name,
            last_name=telegram_user.last_name,
            username=telegram_user.username,
        )
        try:
            await identity_service.record_phone(conn, user_id=user["id"], raw_phone=raw_phone)
        except identity_service.InvalidPhone:
            await message.answer(uz.PHONE_INVALID, reply_markup=keyboards.remove_keyboard())
            return
        except asyncpg.exceptions.UniqueViolationError:
            # §5.3 partial unique index: this number is already bound to a
            # different account. A "try again later" here was a dead end.
            await message.answer(uz.PHONE_ALREADY_USED, reply_markup=keyboards.remove_keyboard())
            return
        except asyncpg.exceptions.PostgresError:
            logger.exception("failed to record phone for user_id=%s", user["id"])
            await message.answer(uz.GENERIC_ERROR, reply_markup=keyboards.remove_keyboard())
            return

    await message.answer(uz.PHONE_SAVED, reply_markup=keyboards.remove_keyboard())
