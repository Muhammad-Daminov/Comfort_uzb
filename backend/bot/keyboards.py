"""Phone-capture keyboard (§1 ADR-2: "bot da KeyboardButton(request_contact=
True), bepul") and the Mini App Menu Button (ADR-1's bot->Mini App entry
point). No business logic — pure presentation."""
from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    MenuButtonWebApp,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    WebAppInfo,
)

from bot.locales import uz


def phone_request_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=uz.REQUEST_PHONE_BUTTON, request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def remove_keyboard() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()


def miniapp_menu_button(miniapp_url: str) -> MenuButtonWebApp:
    return MenuButtonWebApp(text=uz.OPEN_CATALOG_BUTTON, web_app=WebAppInfo(url=miniapp_url))


def ai_confirmation_keyboard(draft_id: int) -> InlineKeyboardMarkup:
    # callback_data is just "ai_<action>:<draft_id>" — well under Telegram's
    # 64-byte limit. The confirmation_token itself is never put in
    # callback_data (never round-tripped through a client-visible field);
    # the callback handler re-reads it from the DB after verifying the
    # caller is the draft's own admin (see bot/handlers/ai.py).
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=uz.AI_CONFIRM_BUTTON, callback_data=f"ai_confirm:{draft_id}")],
            [
                InlineKeyboardButton(text=uz.AI_EDIT_BUTTON, callback_data=f"ai_edit:{draft_id}"),
                InlineKeyboardButton(text=uz.AI_CANCEL_BUTTON, callback_data=f"ai_cancel:{draft_id}"),
            ],
        ]
    )
