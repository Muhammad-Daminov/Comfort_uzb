from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.config import Settings
from app.db.pool import get_conn
from app.domains.identity import repository, service
from app.security.permissions import CurrentUser, get_current_user
from app.security.telegram_auth import InvalidInitData

router = APIRouter(prefix="/auth", tags=["auth"])


class SessionRequest(BaseModel):
    initData: str


class SessionResponse(BaseModel):
    token: str
    user_id: int
    role: str


@router.post("/session", response_model=SessionResponse)
async def create_session(
    body: SessionRequest, conn: asyncpg.Connection = Depends(get_conn)
) -> SessionResponse:
    settings = Settings.from_env()
    try:
        token, user = await service.authenticate(
            conn, init_data=body.initData, bot_token=settings.bot_token, session_secret=settings.session_secret
        )
    except InvalidInitData as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    return SessionResponse(token=token, user_id=user["id"], role=user["role"])


class MeResponse(BaseModel):
    id: int
    telegram_id: int
    first_name: str | None
    last_name: str | None
    username: str | None
    role: str
    phone: str | None
    status: str
    # Default matches the column's own `NOT NULL DEFAULT true` (migration
    # 0022_notification_prefs) — keeps this model constructible without the
    # field for any existing caller that doesn't pass it.
    telegram_notifications_enabled: bool = True


@router.get("/me", response_model=MeResponse)
async def get_me(
    current_user: CurrentUser = Depends(get_current_user), conn: asyncpg.Connection = Depends(get_conn)
) -> MeResponse:
    """Phase-05 gap: no endpoint returned the caller's own profile fields
    (`POST /auth/session`'s response is deliberately minimal — token +
    id + role only). Profile/Settings screens need phone/name, which
    already exist on `users`; this is a plain read through the existing
    `get_current_user` dependency, not a new capability or schema change."""
    user = await repository.get_by_id(conn, user_id=current_user.id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    return MeResponse(**dict(user))


class NotificationSettingsRequest(BaseModel):
    telegram_notifications_enabled: bool


@router.patch("/me/notification-settings", response_model=MeResponse)
async def update_notification_settings(
    body: NotificationSettingsRequest,
    current_user: CurrentUser = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_conn),
) -> MeResponse:
    """§P3B-2: a single, real, backend-enforced toggle for the Telegram
    half of the existing dual-channel notification design (§10/ADR-12) —
    `current_user.id` is derived from the signed session token, so this can
    never touch another user's row regardless of client input."""
    await repository.set_telegram_notifications_enabled(
        conn, user_id=current_user.id, enabled=body.telegram_notifications_enabled
    )
    user = await repository.get_by_id(conn, user_id=current_user.id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    return MeResponse(**dict(user))
