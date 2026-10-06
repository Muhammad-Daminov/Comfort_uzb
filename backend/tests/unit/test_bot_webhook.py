"""Phase 09: `bot/main.py::build_webhook_router` had no test at all before
this pass — the whole route was also unwired from `app/main.py` until this
phase (see the module docstring in `app/main.py::lifespan`). Verifies the
secret-token check (the webhook's equivalent of ADR-2's trust boundary)
without needing a real Telegram Bot/Dispatcher or network access.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bot.main import build_webhook_router

WEBHOOK_SECRET = "test-webhook-secret"

_SAMPLE_UPDATE = {
    "update_id": 1,
    "message": {
        "message_id": 1,
        "date": 1,
        "chat": {"id": 1, "type": "private"},
        "from": {"id": 1, "is_bot": False, "first_name": "T"},
        "text": "/start",
    },
}


def _build_app() -> tuple[FastAPI, MagicMock]:
    bot = MagicMock()
    dispatcher = MagicMock()
    dispatcher.feed_update = AsyncMock()
    router = build_webhook_router(bot=bot, dispatcher=dispatcher, webhook_secret=WEBHOOK_SECRET)
    app = FastAPI()
    app.include_router(router)
    return app, dispatcher


def test_missing_secret_header_is_401():
    app, dispatcher = _build_app()
    with TestClient(app) as client:
        r = client.post("/telegram/webhook", json=_SAMPLE_UPDATE)
    assert r.status_code == 401
    dispatcher.feed_update.assert_not_called()


def test_wrong_secret_header_is_401():
    app, dispatcher = _build_app()
    with TestClient(app) as client:
        r = client.post(
            "/telegram/webhook", json=_SAMPLE_UPDATE, headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"}
        )
    assert r.status_code == 401
    dispatcher.feed_update.assert_not_called()


def test_correct_secret_dispatches_update():
    app, dispatcher = _build_app()
    with TestClient(app) as client:
        r = client.post(
            "/telegram/webhook",
            json=_SAMPLE_UPDATE,
            headers={"X-Telegram-Bot-Api-Secret-Token": WEBHOOK_SECRET},
        )
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    dispatcher.feed_update.assert_awaited_once()


def test_malformed_body_with_valid_secret_is_400_not_500():
    """docs/11_FULL_SYSTEM_AUDIT_REPORT.md M9 — a non-JSON / non-Update body
    used to escape as an unhandled exception."""
    app, dispatcher = _build_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        not_json = client.post(
            "/telegram/webhook", content=b"{not json", headers={
                "X-Telegram-Bot-Api-Secret-Token": WEBHOOK_SECRET, "Content-Type": "application/json",
            },
        )
        not_update = client.post(
            "/telegram/webhook", json={"foo": "bar"}, headers={"X-Telegram-Bot-Api-Secret-Token": WEBHOOK_SECRET},
        )
    assert not_json.status_code == 400
    assert not_update.status_code == 400
    dispatcher.feed_update.assert_not_called()
