"""Admin-only AI assistant HTTP surface. §7 of the v2 brief: OWNER/ADMIN
only, never USER — enforced by `require_permission("ai.assistant.use")`,
the same server-side permission check every other admin endpoint uses.
"""
from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.ai import resolver
from app.ai.drafts import service as drafts_service
from app.ai.providers.base import ProviderNotConfigured
from app.ai.providers.registry import get_ai_provider, get_stt_provider
from app.config import Settings
from app.db.pool import get_conn
from app.security.permissions import CurrentUser, require_permission

router = APIRouter(tags=["ai"])


def _error(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


class MessageBody(BaseModel):
    text: str


class ConfirmBody(BaseModel):
    confirmation_token: str




@router.post("/admin/ai/message")
async def ai_message(
    body: MessageBody,
    request: Request,
    current_user: CurrentUser = Depends(require_permission("ai.assistant.use")),
    conn: asyncpg.Connection = Depends(get_conn),
) -> dict:
    settings = Settings.from_env()
    provider = get_ai_provider(settings)

    try:
        result = await provider.generate_structured_command(text=body.text)
    except ProviderNotConfigured as exc:
        raise HTTPException(status_code=503, detail=_error("AI_PROVIDER_UNAVAILABLE", str(exc))) from exc

    if result.command_type is None:
        message = result.clarification_message or "Tushunmadim. Iltimos, aniqroq yozing."
        return {
            "understood": False,
            "clarification_required": result.clarification_required,
            "message": message,
            "raw_text": result.raw_text,
        }

    try:
        resolved_payload = await resolver.resolve_command_references(conn, result.command_type, result.payload)
    except resolver.ProductNotFound as exc:
        raise HTTPException(status_code=422, detail=_error("NOT_FOUND", str(exc))) from exc
    except resolver.AmbiguousReference as exc:
        raise HTTPException(
            status_code=409, detail=_error("AMBIGUOUS_REFERENCE", f"{len(exc.matches)} matches") | {"matches": exc.matches}
        ) from exc

    try:
        outcome = await drafts_service.handle_command(
            conn, actor=current_user, command_type=result.command_type, raw_payload=resolved_payload,
            source="TEXT", ip=request.client.host if request.client else None,
        )
    except drafts_service.Forbidden as exc:
        raise HTTPException(status_code=403, detail=_error("FORBIDDEN", str(exc))) from exc
    except Exception as exc:  # InvalidPayload/UnknownCommand from commands.py
        raise HTTPException(status_code=422, detail=_error("INVALID_REQUEST", str(exc))) from exc

    return {"understood": True, "command_type": result.command_type, **outcome}


@router.post("/admin/ai/voice")
async def ai_voice(
    request: Request,
    current_user: CurrentUser = Depends(require_permission("ai.assistant.use")),
    conn: asyncpg.Connection = Depends(get_conn),
) -> dict:
    settings = Settings.from_env()
    stt = get_stt_provider(settings)
    audio_bytes = await request.body()
    content_type = request.headers.get("content-type", "audio/ogg")
    try:
        transcript = await stt.transcribe(audio_bytes=audio_bytes, mime_type=content_type)
    except ProviderNotConfigured as exc:
        raise HTTPException(status_code=503, detail=_error("STT_NOT_CONFIGURED", str(exc))) from exc

    return await ai_message(MessageBody(text=transcript), request, current_user, conn)


@router.post("/admin/ai/drafts/{draft_id}/confirm")
async def ai_confirm(
    draft_id: int,
    body: ConfirmBody,
    request: Request,
    current_user: CurrentUser = Depends(require_permission("ai.assistant.use")),
    conn: asyncpg.Connection = Depends(get_conn),
) -> dict:
    try:
        result = await drafts_service.confirm(
            conn, draft_id=draft_id, confirmation_token=body.confirmation_token, actor=current_user,
            ip=request.client.host if request.client else None,
        )
    except drafts_service.DraftNotFound as exc:
        raise HTTPException(status_code=404, detail=_error("NOT_FOUND", str(exc))) from exc
    except drafts_service.DraftNotOwnedByCaller as exc:
        raise HTTPException(status_code=403, detail=_error("FORBIDDEN", str(exc))) from exc
    except drafts_service.DraftExpired as exc:
        raise HTTPException(status_code=409, detail=_error("DRAFT_EXPIRED", str(exc))) from exc
    except drafts_service.DraftNotPending as exc:
        raise HTTPException(status_code=409, detail=_error("DRAFT_NOT_PENDING", str(exc))) from exc
    except drafts_service.Forbidden as exc:
        raise HTTPException(status_code=403, detail=_error("FORBIDDEN", str(exc))) from exc
    return result


@router.post("/admin/ai/drafts/{draft_id}/cancel")
async def ai_cancel(
    draft_id: int,
    request: Request,
    current_user: CurrentUser = Depends(require_permission("ai.assistant.use")),
    conn: asyncpg.Connection = Depends(get_conn),
) -> dict:
    try:
        result = await drafts_service.cancel(
            conn, draft_id=draft_id, actor=current_user, ip=request.client.host if request.client else None,
        )
    except drafts_service.DraftNotFound as exc:
        raise HTTPException(status_code=404, detail=_error("NOT_FOUND", str(exc))) from exc
    except drafts_service.DraftNotOwnedByCaller as exc:
        raise HTTPException(status_code=403, detail=_error("FORBIDDEN", str(exc))) from exc
    except drafts_service.DraftNotPending as exc:
        raise HTTPException(status_code=409, detail=_error("DRAFT_NOT_PENDING", str(exc))) from exc
    return result
