"""The worker entrypoints, executed as real subprocesses.

`run_once()` had test coverage already (test_reservation_expiry.py,
test_receipt_purge.py). What had none — and what was actually missing from
the system — is the *process* systemd starts: `python -m app.workers.<name>`.
These tests run that exact command line, so the contract systemd depends on
is verified rather than assumed:

* exit 0 on success, non-zero on failure (systemd marks the unit failed)
* a structured log line per outcome (journald is the only observability
  surface a oneshot unit has)
* overlapping runs skip instead of double-applying
* missing required configuration fails loudly rather than silently no-oping

systemd itself is NOT exercised here — no root, no unit installation in this
environment. This proves the command behaves; deploy/systemd/*.timer
scheduling correctness is covered by tests/unit/test_worker_scheduling_units.py.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys

import asyncpg
import pytest

from tests.integration import factories

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[2]

WORKERS = ["app.workers.reservation_expiry", "app.workers.receipt_purge"]


def _env(**overrides) -> dict:
    env = dict(os.environ)
    env["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "")
    env.setdefault("BOT_TOKEN", "worker-test-bot-token")
    env.setdefault("SESSION_SECRET", "worker-test-session-secret")
    env.setdefault("SIGNING_SECRET", "worker-test-signing-secret")
    env.setdefault("UPLOADS_ROOT", "/tmp")
    env.update({k: v for k, v in overrides.items() if v is not None})
    for key, value in overrides.items():
        if value is None:
            env.pop(key, None)
    return env


def _run(module: str, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", module],
        cwd=BACKEND_DIR, env=env, capture_output=True, text=True, timeout=120,
    )


def _log_lines(result: subprocess.CompletedProcess) -> list[dict]:
    lines = []
    for raw in (result.stdout + result.stderr).splitlines():
        raw = raw.strip()
        if raw.startswith("{"):
            try:
                lines.append(json.loads(raw))
            except json.JSONDecodeError:
                pass
    return lines


@pytest.mark.parametrize("module", WORKERS)
def test_entrypoint_runs_and_exits_zero(module):
    result = _run(module, _env())
    assert result.returncode == 0, result.stderr[-2000:]
    logs = _log_lines(result)
    assert logs, f"no structured log line emitted:\n{result.stderr[-1000:]}"
    assert any("processed" in line.get("message", "") for line in logs), logs


@pytest.mark.parametrize("module", WORKERS)
def test_entrypoint_is_safe_to_rerun(module):
    """Idempotence at the process level — running twice back to back must
    not fail or double-apply."""
    first = _run(module, _env())
    second = _run(module, _env())
    assert first.returncode == 0 and second.returncode == 0
    # Second run finds nothing left to do (the fixtures leave no due work).
    assert any("processed 0 item(s)" in line.get("message", "") for line in _log_lines(second))


@pytest.mark.parametrize("module", WORKERS)
def test_entrypoint_fails_loudly_when_required_config_is_missing(module):
    """`app/config.py` promises no silent fallback for anything
    security-sensitive — the worker process must honour that, not start up
    half-configured."""
    result = _run(module, _env(SESSION_SECRET=None))
    assert result.returncode != 0
    assert "SESSION_SECRET" in (result.stdout + result.stderr)


@pytest.mark.parametrize("module", WORKERS)
def test_entrypoint_fails_loudly_when_the_database_is_unreachable(module):
    """A DB outage must surface as a failed unit, not a silent success that
    quietly skips a retention or expiry cycle."""
    result = _run(module, _env(DATABASE_URL="postgresql://nobody:wrong@127.0.0.1:5432/does_not_exist"))
    assert result.returncode != 0
    logs = _log_lines(result)
    assert any(line.get("level") == "ERROR" for line in logs), logs


@pytest.mark.asyncio
async def test_overlapping_run_skips_instead_of_double_applying(conn):
    """The advisory lock in app/workers/_entrypoint.py. systemd's oneshot
    type already refuses to run one unit twice at once, but a manual run
    racing the timer (or a second host) is not covered by that."""
    from app.workers._entrypoint import LOCK_KEY_RESERVATION_EXPIRY

    holder = await asyncpg.connect(os.environ["TEST_DATABASE_URL"])
    try:
        got = await holder.fetchval("SELECT pg_try_advisory_lock($1)", LOCK_KEY_RESERVATION_EXPIRY)
        assert got is True

        result = _run("app.workers.reservation_expiry", _env())
        # A skip is a normal outcome, not a failure — the next tick retries.
        assert result.returncode == 0, result.stderr[-1000:]
        assert any("skipped" in line.get("message", "") for line in _log_lines(result)), result.stderr[-1000:]
    finally:
        await holder.execute("SELECT pg_advisory_unlock($1)", LOCK_KEY_RESERVATION_EXPIRY)
        await holder.close()

    # With the lock free it runs normally again.
    after = _run("app.workers.reservation_expiry", _env())
    assert after.returncode == 0
    assert any("processed" in line.get("message", "") for line in _log_lines(after))


@pytest.mark.asyncio
async def test_reservation_expiry_entrypoint_actually_releases_an_expired_reservation(conn, clean_slate):
    """End to end through the real process: an already-expired reservation
    is released and its order moves to EXPIRED."""
    user_id = await factories.make_user(conn, role="USER")
    brand_id = await factories.make_brand(conn, name="Worker brand")
    product_id = await factories.make_product(conn, brand_id=brand_id, name="Worker product")
    variant_id = await factories.make_variant(
        conn, product_id=product_id, sku="WORKER-EXP-1", price=1000, stock_on_hand=5, stock_reserved=2
    )
    order_id = await conn.fetchval(
        """
        INSERT INTO orders (order_number, user_id, status, total_amount,
                            required_initial_amount, paid_amount, remaining_amount)
        VALUES ($1, $2, 'CREATED', 2000, 1000, 0, 2000) RETURNING id
        """,
        f"WRK-{user_id}", user_id,
    )
    reservation_id = await conn.fetchval(
        """
        INSERT INTO stock_reservations (order_id, variant_id, quantity, expires_at)
        VALUES ($1, $2, 2, now() - interval '1 hour') RETURNING id
        """,
        order_id, variant_id,
    )

    result = _run("app.workers.reservation_expiry", _env())
    assert result.returncode == 0, result.stderr[-2000:]

    released_at = await conn.fetchval("SELECT released_at FROM stock_reservations WHERE id = $1", reservation_id)
    assert released_at is not None, "the worker process did not release the expired reservation"
    status = await conn.fetchval("SELECT status FROM orders WHERE id = $1", order_id)
    assert status == "EXPIRED", status
    reserved = await conn.fetchval("SELECT stock_reserved FROM product_variants WHERE id = $1", variant_id)
    assert reserved == 0, reserved
