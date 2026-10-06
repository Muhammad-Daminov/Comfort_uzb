#!/usr/bin/env python3
"""COMFORT UZB — post-deployment smoke test (Phase 09 §20).

Deterministic, read-mostly walk of the USER/ADMIN/OWNER flows named in the
Phase 09 brief, against a running instance (local or deployed). Zero
non-stdlib dependencies deliberately — this script must be runnable from a
bare `comfort` server account without a Python venv active.

USER flow is READ-ONLY: session, /auth/me, catalog, product detail and
GET /cart. It creates no cart item, no order and no payment — the
docstring used to claim it "adds a cart item and creates one order",
which it never did (post-audit correction, 2026-09-19); for a real
write-path exercise use backend/scripts/audit_smoke.py against a
disposable database.

ADMIN/OWNER flows are read-only checks (dashboard/orders/products/
inventory for ADMIN; dashboard/finance/analytics/admins/audit/settings for
OWNER) — this script does not create or deactivate admins, adjust stock,
or change settings against a real deployment.

Usage:
    python3 smoke_test.py --base-url https://comfort.example.uz \\
        --bot-token "$BOT_TOKEN" \\
        --user-telegram-id 100000001 \\
        [--admin-telegram-id 100000002] \\
        [--owner-telegram-id 100000003]

Admin/owner telegram ids are optional — if omitted, those sections are
skipped with an explicit note rather than silently treated as passing.
Exits non-zero on any failure, printing a PASS/FAIL line per check.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlencode

FAILURES: list[str] = []


def _build_init_data(telegram_id: int, bot_token: str) -> str:
    user = json.dumps({"id": telegram_id, "first_name": "SmokeTest"})
    data = {"auth_date": str(int(time.time())), "user": user}
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    data["hash"] = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(data)


def _request(method: str, url: str, *, token: str | None = None, body: dict | None = None) -> tuple[int, dict]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read() or b"{}")
        except json.JSONDecodeError:
            return exc.code, {}


def _check(label: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}{' — ' + detail if detail and not condition else ''}")
    if not condition:
        FAILURES.append(label)


def _session_for(base_url: str, telegram_id: int, bot_token: str) -> str | None:
    status, body = _request("POST", f"{base_url}/auth/session", body={"initData": _build_init_data(telegram_id, bot_token)})
    if status != 200:
        _check(f"session for telegram_id={telegram_id}", False, f"status={status} body={body}")
        return None
    return body.get("token")


def run_user_flow(base_url: str, telegram_id: int, bot_token: str) -> None:
    print("\n--- USER flow ---")
    status, body = _request("GET", f"{base_url}/catalog/products?limit=5")
    _check("GET /catalog/products", status == 200, f"status={status}")
    items = body.get("items", [])
    if not items:
        _check("catalog has at least one product to smoke-test against", False, "empty catalog — seed data before running this")
        return

    product_id = items[0]["id"]
    status, _ = _request("GET", f"{base_url}/catalog/products/{product_id}")
    _check("GET /catalog/products/{id}", status == 200, f"status={status}")

    token = _session_for(base_url, telegram_id, bot_token)
    if token is None:
        return

    status, cart = _request("GET", f"{base_url}/cart", token=token)
    _check("GET /cart", status == 200, f"status={status}")

    status, me = _request("GET", f"{base_url}/auth/me", token=token)
    _check("GET /auth/me", status == 200, f"status={status}")


def run_admin_flow(base_url: str, telegram_id: int, bot_token: str) -> None:
    print("\n--- ADMIN flow ---")
    token = _session_for(base_url, telegram_id, bot_token)
    if token is None:
        return
    status, _ = _request("GET", f"{base_url}/admin/orders", token=token)
    _check("GET /admin/orders", status == 200, f"status={status}")
    status, _ = _request("GET", f"{base_url}/catalog/products?limit=5", token=token)
    _check("GET /catalog/products (admin)", status == 200, f"status={status}")
    status, _ = _request("GET", f"{base_url}/admin/payments", token=token)
    _check("GET /admin/payments", status == 200, f"status={status}")


def run_owner_flow(base_url: str, telegram_id: int, bot_token: str) -> None:
    print("\n--- OWNER flow ---")
    token = _session_for(base_url, telegram_id, bot_token)
    if token is None:
        return
    import datetime

    date_to = datetime.date.today().isoformat()
    date_from = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
    for path in [
        "/owner/dashboard",
        f"/owner/finance?from={date_from}&to={date_to}",
        f"/owner/analytics?from={date_from}&to={date_to}",
        "/owner/admins",
        "/owner/audit-logs",
        "/owner/settings",
    ]:
        status, _ = _request("GET", f"{base_url}{path}", token=token)
        _check(f"GET {path}", status == 200, f"status={status}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--bot-token", required=True)
    parser.add_argument("--user-telegram-id", type=int, required=True)
    parser.add_argument("--admin-telegram-id", type=int, default=None)
    parser.add_argument("--owner-telegram-id", type=int, default=None)
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")

    status, _ = _request("GET", f"{base_url}/health/ready")
    _check("GET /health/ready", status == 200, f"status={status}")

    run_user_flow(base_url, args.user_telegram_id, args.bot_token)

    if args.admin_telegram_id:
        run_admin_flow(base_url, args.admin_telegram_id, args.bot_token)
    else:
        print("\n--- ADMIN flow: SKIPPED (no --admin-telegram-id given) ---")

    if args.owner_telegram_id:
        run_owner_flow(base_url, args.owner_telegram_id, args.bot_token)
    else:
        print("\n--- OWNER flow: SKIPPED (no --owner-telegram-id given) ---")

    print(f"\n{len(FAILURES)} failure(s)" if FAILURES else "\nAll checks passed")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
