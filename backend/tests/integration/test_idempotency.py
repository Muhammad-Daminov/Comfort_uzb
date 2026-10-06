"""ADR-7/REQ-TST-001: a duplicate Idempotency-Key executes the action
exactly once and replays the stored response, at the storage-primitive
level `app/security/idempotency.py` provides (the Router-layer wiring
around it is covered by manual end-to-end verification, per the plan)."""
from __future__ import annotations

import uuid

import pytest

from app.security.idempotency import (
    IdempotencyKeyReused,
    check_idempotency_key,
    hash_request,
    store_idempotency_result,
)
from tests.integration import factories

pytestmark = pytest.mark.asyncio


async def test_first_call_has_no_stored_result(conn, clean_slate):
    user_id = await factories.make_user(conn)
    key = uuid.uuid4()
    result = await check_idempotency_key(
        conn, key=key, endpoint="POST /orders", user_id=user_id, request_hash=hash_request({"a": 1})
    )
    assert result is None


async def test_duplicate_key_same_body_replays_stored_response(conn, clean_slate):
    user_id = await factories.make_user(conn)
    key = uuid.uuid4()
    body_hash = hash_request({"lines": [{"variant_id": 1, "quantity": 1}]})

    await store_idempotency_result(
        conn, key=key, endpoint="POST /orders", user_id=user_id, request_hash=body_hash,
        status_code=201, response_body={"id": 42, "order_number": "CU-ABC123"},
    )

    replayed = await check_idempotency_key(
        conn, key=key, endpoint="POST /orders", user_id=user_id, request_hash=body_hash
    )
    assert replayed is not None
    assert replayed.status_code == 201
    assert replayed.response_body == {"id": 42, "order_number": "CU-ABC123"}


async def test_duplicate_key_different_body_is_rejected(conn, clean_slate):
    user_id = await factories.make_user(conn)
    key = uuid.uuid4()

    await store_idempotency_result(
        conn, key=key, endpoint="POST /orders", user_id=user_id, request_hash=hash_request({"a": 1}),
        status_code=201, response_body={"ok": True},
    )

    with pytest.raises(IdempotencyKeyReused):
        await check_idempotency_key(
            conn, key=key, endpoint="POST /orders", user_id=user_id, request_hash=hash_request({"a": 2})
        )
