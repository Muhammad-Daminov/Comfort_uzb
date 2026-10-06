"""§14-25/§38 of the v2 rebuild brief — the mandatory AI architecture:

    ADMIN -> AI -> STRUCTURED INTENT -> BACKEND VALIDATION -> PREVIEW
          -> ADMIN CONFIRMATION -> DOMAIN SERVICE -> DATABASE

`handle_command` is the single entry point every AI-issued structured
command passes through, whether it came from text, voice-transcript, or
image+text. It:
  1. re-validates the payload against the strict schema (commands.py) —
     never trusts the AI provider's output shape;
  2. re-checks the caller's permission for that specific command via the
     same `has_permission` check every manual admin endpoint uses — the AI
     cannot grant itself a permission the admin's role doesn't already have;
  3. for read-only commands, executes immediately and returns the result
     (§19: safe informational queries don't need confirmation);
  4. for mutations, creates a PENDING draft row and returns a preview —
     nothing is written to product/order/inventory tables at this point.

`confirm` is the only path that turns a draft into an actual mutation, and
only re-reads the payload that was frozen at draft-creation time — the
admin's confirm action cannot be reinterpreted against different values
(§24, "Malibu 2 +1" confirmation must not later work for "Malibu 2 +100").
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import asyncpg

from app.ai import executor
from app.ai.commands import COMMAND_SPECS, InvalidPayload, UnknownCommand, validate_command
from app.ai.drafts import repository
from app.security.audit import record_audit
from app.security.permissions import CurrentUser, has_permission

if TYPE_CHECKING:
    from aiogram import Bot

DRAFT_TTL = timedelta(minutes=15)


class Forbidden(Exception):
    pass


class DraftNotFound(Exception):
    pass


class DraftNotPending(Exception):
    pass


class DraftExpired(Exception):
    pass


class DraftNotOwnedByCaller(Exception):
    pass


def _preview_text(command_type: str, payload) -> str:
    """Plain, literal rendering of the exact stored payload — the same
    values that will be executed on confirm, not a re-derived summary."""
    fields = payload.model_dump()
    lines = [f"{command_type}"] + [f"{k}: {v}" for k, v in fields.items() if v is not None]
    return "\n".join(lines)


async def handle_command(
    conn: asyncpg.Connection,
    *,
    actor: CurrentUser,
    command_type: str,
    raw_payload: dict,
    source: str,
    ip: str | None = None,
) -> dict:
    spec = COMMAND_SPECS.get(command_type)
    if spec is None:
        raise UnknownCommand(f"unknown AI command type: {command_type!r}")

    if not await has_permission(conn, actor.role, spec.permission):
        raise Forbidden(f"role {actor.role} lacks permission {spec.permission} for {command_type}")

    payload = validate_command(command_type, raw_payload)

    if command_type == "CREATE_PRODUCT" and getattr(payload, "cost_price", None) is not None:
        # Cost price is financial data — gated separately from
        # products.create, same rule as the manual cost-price endpoint
        # (catalog/admin_router.py::admin_set_variant_cost_price).
        if not await has_permission(conn, actor.role, "finance.view"):
            raise Forbidden("role lacks permission finance.view to set cost_price via AI")

    if spec.read_only:
        result = await executor.execute(conn, command_type=command_type, payload=payload, actor=actor)
        await record_audit(
            conn, actor_id=actor.id, actor_role=actor.role, action=f"ai.command.{command_type.lower()}",
            entity_type="ai_command", entity_id=0, new_data={"command_type": command_type, "read_only": True}, ip=ip,
        )
        return {"executed": True, "read_only": True, "result": result}

    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + DRAFT_TTL
    draft = await repository.create_draft(
        conn, admin_id=actor.id, command_type=command_type, payload=payload.model_dump(),
        source=source, confirmation_token=token, expires_at=expires_at,
    )
    await record_audit(
        conn, actor_id=actor.id, actor_role=actor.role, action="ai.draft.create",
        entity_type="ai_command_draft", entity_id=draft["id"],
        new_data={"command_type": command_type, "payload": payload.model_dump()}, ip=ip,
    )
    return {
        "executed": False,
        "read_only": False,
        "draft_id": draft["id"],
        "confirmation_token": token,
        "expires_at": expires_at.isoformat(),
        "preview": _preview_text(command_type, payload),
    }


async def confirm(
    conn: asyncpg.Connection, *, draft_id: int, confirmation_token: str, actor: CurrentUser, ip: str | None = None,
    bot: "Bot | None" = None,
) -> dict:
    # Single transaction, held for the whole attempt (the FOR UPDATE lock
    # is what makes test_concurrent_duplicate_confirm_only_one_succeeds
    # correct — a second confirmer blocks until this one commits, then sees
    # status != PENDING). Deliberately never raises *from inside* the
    # `async with` block: raising there would roll back the mark_failed()
    # write for the exact case it exists to record (draft expired / a
    # business rule rejected the frozen payload) — caught live by
    # test_expired_draft_cannot_be_confirmed. Instead every branch sets
    # `outcome` and the block exits normally; the actual exception (if any)
    # is raised once, after the transaction has committed.
    outcome: tuple[str, Exception] | None = None
    result: dict | None = None
    command_type: str | None = None

    async with conn.transaction():
        draft = await repository.get_draft_for_update(conn, draft_id=draft_id)
        if draft is None:
            outcome = ("not_found", DraftNotFound(f"draft {draft_id} not found"))
        elif draft["admin_id"] != actor.id:
            # §24: tied to the authenticated admin who created it — not
            # even another admin/OWNER can confirm someone else's draft.
            outcome = ("not_owned", DraftNotOwnedByCaller(f"draft {draft_id} does not belong to this admin"))
        elif draft["confirmation_token"] != confirmation_token:
            outcome = ("bad_token", Forbidden("confirmation token does not match"))
        elif draft["status"] != "PENDING":
            outcome = ("not_pending", DraftNotPending(f"draft {draft_id} is already {draft['status']}"))
        elif draft["expires_at"] < datetime.now(timezone.utc):
            await repository.mark_failed(conn, draft_id=draft_id, error="expired")
            outcome = ("expired", DraftExpired(f"draft {draft_id} expired at {draft['expires_at']}"))
        else:
            command_type = draft["command_type"]
            spec = COMMAND_SPECS.get(command_type)
            if spec is None:
                await repository.mark_failed(conn, draft_id=draft_id, error="unknown command_type")
                outcome = ("unknown_command", UnknownCommand(command_type))
            elif not await has_permission(conn, actor.role, spec.permission):
                # Re-checked at confirm time too: a role change between
                # draft creation and confirmation must not let a stale
                # grant through.
                await repository.mark_failed(conn, draft_id=draft_id, error=f"permission {spec.permission} revoked")
                outcome = ("forbidden", Forbidden(f"role {actor.role} no longer has permission {spec.permission}"))
            else:
                import json

                payload = validate_command(command_type, json.loads(draft["payload"]))
                if command_type == "CREATE_PRODUCT" and getattr(payload, "cost_price", None) is not None and not await has_permission(conn, actor.role, "finance.view"):
                    await repository.mark_failed(conn, draft_id=draft_id, error="finance.view no longer granted")
                    outcome = ("forbidden", Forbidden("role lacks permission finance.view to set cost_price via AI"))
                else:
                    try:
                        result = await executor.execute(conn, command_type=command_type, payload=payload, actor=actor, bot=bot)
                    except Exception as exc:  # noqa: BLE001 — recorded, then re-raised below
                        await repository.mark_failed(conn, draft_id=draft_id, error=str(exc))
                        outcome = ("execution_failed", exc)
                    else:
                        await repository.mark_confirmed(
                            conn, draft_id=draft_id,
                            result_entity_type=result.get("entity_type"), result_entity_id=result.get("entity_id"),
                        )
                        await record_audit(
                            conn, actor_id=actor.id, actor_role=actor.role, action="ai.draft.confirm",
                            entity_type="ai_command_draft", entity_id=draft_id,
                            new_data={"command_type": command_type, "result": result}, ip=ip,
                        )

    if outcome is not None:
        raise outcome[1]
    return {"draft_id": draft_id, "command_type": command_type, "result": result}


async def cancel(conn: asyncpg.Connection, *, draft_id: int, actor: CurrentUser, ip: str | None = None) -> dict:
    draft = await repository.get_draft(conn, draft_id=draft_id)
    if draft is None:
        raise DraftNotFound(f"draft {draft_id} not found")
    if draft["admin_id"] != actor.id:
        raise DraftNotOwnedByCaller(f"draft {draft_id} does not belong to this admin")
    updated = await repository.mark_cancelled(conn, draft_id=draft_id)
    if updated is None:
        raise DraftNotPending(f"draft {draft_id} is already {draft['status']}")
    await record_audit(
        conn, actor_id=actor.id, actor_role=actor.role, action="ai.draft.cancel",
        entity_type="ai_command_draft", entity_id=draft_id, new_data={}, ip=ip,
    )
    return dict(updated)
