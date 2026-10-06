"""Runtime smoke harness from the 2026-09-19 full-system audit
(docs/11_FULL_SYSTEM_AUDIT_REPORT.md §14). Drives a running API over real
HTTP with locally forged initData and checks the whole P0 flow — auth,
permission matrix, catalog/pagination/search, cart, checkout+idempotency,
payments/receipts/signed URLs, review/cancel, confirm + expiry worker +
ledger, inventory, owner. Creates its own users/orders; run it ONLY against
a disposable database (it also runs the expiry worker and backdates rows).

Env (same names the app/tests use): BOT_TOKEN (any value — the harness
signs initData with it), SIGNING_SECRET, TELEGRAM_WEBHOOK_SECRET,
OWNER_TELEGRAM_ID, DATABASE_URL (comfort_app), SUPERUSER_DATABASE_URL,
UPLOADS_ROOT, optional SMOKE_API (default http://127.0.0.1:8123).
Run from backend/:  PYTHONPATH=. .venv/bin/python scripts/audit_smoke.py
Never prints secrets."""
from __future__ import annotations

import hashlib
import hmac
import io
import json
import os
import sys
import time
import uuid
from urllib.parse import urlencode

import asyncpg
import asyncio
import httpx
from PIL import Image

API = os.environ.get("SMOKE_API", "http://127.0.0.1:8123")
BOT_TOKEN = os.environ["BOT_TOKEN"]
SUPER_DSN = os.environ["SUPERUSER_DATABASE_URL"]
OWNER_TG = int(os.environ["OWNER_TELEGRAM_ID"])
USER_TG = 700000001
ADMIN_TG = 700000002

results: list[tuple[str, str, str]] = []


def rec(name: str, ok: bool, note: str = "") -> None:
    results.append((name, "PASS" if ok else "FAIL", note))
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {note}")


def init_data(tg_id: int, *, auth_date: int | None = None, tamper: bool = False) -> str:
    user = json.dumps({"id": tg_id, "first_name": "Smoke", "username": f"smoke{tg_id}"})
    data = {"auth_date": str(auth_date or int(time.time())), "query_id": "AAA", "user": user}
    check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    h = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if tamper:
        data["user"] = json.dumps({"id": OWNER_TG, "first_name": "Evil"})
    data["hash"] = h
    return urlencode(data)


def sql(query: str, *args):
    async def run():
        conn = await asyncpg.connect(SUPER_DSN)
        try:
            return await conn.fetch(query, *args)
        finally:
            await conn.close()
    return asyncio.run(run())


def png_bytes(size=(64, 64)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(buf, format="PNG")
    return buf.getvalue()


class Client:
    def __init__(self, token: str | None = None):
        self.h = {"Authorization": f"Bearer {token}"} if token else {}
        self.c = httpx.Client(base_url=API, timeout=30)

    def req(self, method, path, *, json_body=None, key=False, files=None, params=None, headers=None):
        hd = dict(self.h)
        if key:
            hd["Idempotency-Key"] = str(uuid.uuid4()) if key is True else key
        if headers:
            hd.update(headers)
        return self.c.request(method, path, json=json_body, headers=hd, files=files, params=params)


def session(tg_id: int, **kw) -> tuple[int, dict]:
    r = httpx.post(f"{API}/auth/session", json={"initData": init_data(tg_id, **kw)}, timeout=30)
    return r.status_code, (r.json() if r.content else {})


def main() -> None:
    # ---- auth ---------------------------------------------------------
    st, body = session(USER_TG)
    rec("auth: valid initData -> 200", st == 200 and body.get("role") == "USER", str(st))
    user = Client(body["token"])
    st, _ = session(USER_TG, tamper=True)
    rec("auth: tampered user field -> 401", st == 401, str(st))
    st, _ = session(USER_TG, auth_date=int(time.time()) - 90000)
    rec("auth: auth_date 25h old -> 401", st == 401, str(st))
    r = httpx.post(f"{API}/auth/session", json={"initData": "garbage=1"}, timeout=30)
    rec("auth: malformed initData -> 401", r.status_code == 401, str(r.status_code))
    r = httpx.get(f"{API}/cart", headers={"Authorization": "Bearer nope"}, timeout=30)
    rec("auth: malformed bearer -> 401", r.status_code == 401, str(r.status_code))
    r = httpx.get(f"{API}/cart", timeout=30)
    rec("auth: missing bearer -> 401", r.status_code == 401, str(r.status_code))

    # owner + admin sessions (admin created by owner)
    st, ob = session(OWNER_TG)
    rec("auth: OWNER row from migration 0002 -> role OWNER", st == 200 and ob.get("role") == "OWNER", str(ob.get("role")))
    owner = Client(ob["token"])
    r = owner.req("POST", "/owner/admins", json_body={"telegram_id": ADMIN_TG, "first_name": "Adm"})
    rec("owner: create admin -> 200", r.status_code == 200, str(r.status_code))
    st, ab = session(ADMIN_TG)
    rec("auth: ADMIN session role", st == 200 and ab.get("role") == "ADMIN", str(ab.get("role")))
    admin = Client(ab["token"])

    # ---- permission matrix ------------------------------------------
    for path in ("/owner/dashboard", "/owner/finance?from=2026-01-01&to=2026-02-01", "/owner/analytics?from=2026-01-01&to=2026-02-01", "/owner/admins", "/owner/audit-logs", "/owner/settings"):
        ra, ru, ro = admin.req("GET", path), user.req("GET", path), owner.req("GET", path)
        rec(f"perm: {path.split('?')[0]} ADMIN=403 USER=403 OWNER=200", ra.status_code == 403 and ru.status_code == 403 and ro.status_code == 200, f"{ra.status_code}/{ru.status_code}/{ro.status_code}")
    r = user.req("GET", "/admin/orders")
    rec("perm: USER /admin/orders -> 403", r.status_code == 403, str(r.status_code))
    r = admin.req("GET", "/admin/orders")
    rec("perm: ADMIN /admin/orders -> 200", r.status_code == 200, str(r.status_code))

    # ---- catalog -----------------------------------------------------
    page1 = user.req("GET", "/catalog/products", params={"limit": 3}).json()
    rec("catalog: page1 200 with next_cursor", bool(page1.get("items")) and page1.get("next_cursor"), "")
    for sort in ("newest", "price_asc", "price_desc", "popular"):
        p1 = user.req("GET", "/catalog/products", params={"limit": 3, "sort": sort})
        p2 = user.req("GET", "/catalog/products", params={"limit": 3, "sort": sort, "cursor": p1.json()["next_cursor"]})
        ok = p2.status_code == 200 and p2.json()["items"] and not ({i["id"] for i in p1.json()["items"]} & {i["id"] for i in p2.json()["items"]})
        rec(f"catalog: page2 sort={sort} -> 200 disjoint", ok, str(p2.status_code))
    r = user.req("GET", "/catalog/products", params={"cursor": "!!!notbase64"})
    rec("catalog: malformed cursor -> 422", r.status_code == 422, str(r.status_code))
    item0 = page1["items"][0]
    rec("catalog: listing item has primary_image_url key & no storage_path", "primary_image_url" in item0 and "primary_image_path" not in item0, "")
    # H7: total_available must equal sum of active variants' available
    row = sql("SELECT p.id, COALESCE(SUM(GREATEST(v.stock_on_hand-v.stock_reserved,0)),0) AS avail FROM products p JOIN product_variants v ON v.product_id=p.id AND v.deleted_at IS NULL AND v.status='ACTIVE' WHERE p.id=$1 GROUP BY p.id", item0["id"])
    rec("catalog: total_available matches DB (pre-order)", int(item0["total_available"]) == int(row[0]["avail"]), f"{item0['total_available']} vs {row[0]['avail']}")
    s = user.req("GET", "/catalog/search", params={"q": "gilam"})
    sitems = s.json().get("items", [])
    rec("search: 200 with items", s.status_code == 200 and len(sitems) > 0, str(len(sitems)))
    if sitems:
        rec("search: items carry min_price/total_available/primary_image_url", all(k in sitems[0] for k in ("min_price", "total_available", "primary_image_url")), str(sorted(sitems[0].keys())))
    # discounted product detail
    disc = sql("SELECT dt.target_id FROM discount_targets dt JOIN discounts d ON d.id=dt.discount_id WHERE dt.target_type='PRODUCT' AND d.is_active ORDER BY dt.target_id LIMIT 1")
    pid = disc[0]["target_id"]
    det = user.req("GET", f"/catalog/products/{pid}").json()
    var = next(v for v in det["variants"] if v["status"] == "ACTIVE")
    rec("detail: discounted variant current_price < price", var["current_price"] < var["price"], f"{var['current_price']} < {var['price']}")

    # ---- cart --------------------------------------------------------
    r = user.req("POST", "/cart/items", json_body={"variant_id": var["id"], "quantity": 2})
    rec("cart: add -> 200", r.status_code == 200, str(r.status_code))
    r = user.req("POST", "/cart/items", json_body={"variant_id": 999999, "quantity": 1})
    rec("cart: unknown variant -> 422", r.status_code == 422, str(r.status_code))
    r = user.req("POST", "/cart/items", json_body={"variant_id": var["id"], "quantity": 0})
    rec("cart: qty 0 -> 422", r.status_code == 422, str(r.status_code))
    cart = user.req("GET", "/cart").json()["items"]
    ci = cart[0]
    rec("cart: item exposes current_price == detail current_price", ci.get("current_price") == var["current_price"], f"cart={ci.get('current_price')} detail={var['current_price']}")
    r = user.req("PATCH", f"/cart/items/{ci['id']}", json_body={"quantity": 1})
    rec("cart: patch qty -> 200", r.status_code == 200 and r.json()["quantity"] == 1, str(r.status_code))
    other = Client(session(700000009)[1]["token"])
    r = other.req("PATCH", f"/cart/items/{ci['id']}", json_body={"quantity": 5})
    rec("cart: IDOR patch other's item -> 404", r.status_code == 404, str(r.status_code))

    # ---- checkout ----------------------------------------------------
    lines = [{"variant_id": var["id"], "quantity": 1, "client_unit_price": var["price"]}]  # base price (what the old cart sent)
    r = user.req("POST", "/orders", json_body={"lines": lines}, key=True)
    body = r.json()
    env = body.get("error") or (body.get("detail") or {}).get("error") if isinstance(body.get("detail"), dict) else body.get("error")
    rec("checkout: base price on discounted item -> 409 PRICE_MISMATCH", r.status_code == 409 and (env or {}).get("code") == "PRICE_MISMATCH", f"{r.status_code} keys={list(body)}")
    rec("checkout: 409 body carries top-level error envelope (§13.5)", isinstance(body.get("error"), dict), str(list(body)))
    lines = [{"variant_id": var["id"], "quantity": 1, "client_unit_price": var["current_price"]}]
    key = str(uuid.uuid4())
    r = user.req("POST", "/orders", json_body={"lines": lines}, key=key)
    rec("checkout: current price -> 201", r.status_code == 201, str(r.status_code) + (r.text[:200] if r.status_code != 201 else ""))
    order = r.json()
    r2 = user.req("POST", "/orders", json_body={"lines": lines}, key=key)
    rec("checkout: same key replay -> same order", r2.status_code in (200, 201) and r2.json().get("id") == order.get("id"), str(r2.status_code))
    r3 = user.req("POST", "/orders", json_body={"lines": [{"variant_id": var["id"], "quantity": 2}]}, key=key)
    rec("checkout: same key different body -> 422", r3.status_code == 422, str(r3.status_code))
    cart_after = user.req("GET", "/cart").json()["items"]
    rec("checkout: cart cleared of ordered variant", all(i["variant_id"] != var["id"] for i in cart_after), str(len(cart_after)))
    rec("checkout: order total = current_price", order.get("total_amount") == var["current_price"], str(order.get("total_amount")))
    reserved = sql("SELECT stock_reserved, stock_on_hand FROM product_variants WHERE id=$1", var["id"])[0]
    rec("checkout: stock_reserved incremented", reserved["stock_reserved"] >= 1, str(dict(reserved)))
    r = other.req("GET", f"/orders/{order['id']}")
    rec("orders: IDOR other user's order -> 403", r.status_code == 403, str(r.status_code))
    r = admin.req("GET", f"/orders/{order['id']}")
    rec("orders: admin can view any order -> 200", r.status_code == 200, str(r.status_code))
    # insufficient stock
    r = user.req("POST", "/orders", json_body={"lines": [{"variant_id": var["id"], "quantity": 100000}]}, key=True)
    b = r.json()
    rec("checkout: insufficient stock -> 409 INSUFFICIENT_STOCK envelope", r.status_code == 409 and (b.get("error") or {}).get("code") == "INSUFFICIENT_STOCK", f"{r.status_code} {list(b)}")
    # concurrent same-key checkout (M1)
    key2 = str(uuid.uuid4())
    async def dup():
        async with httpx.AsyncClient(base_url=API, timeout=30) as c:
            hd = {**user.h, "Idempotency-Key": key2}
            return await asyncio.gather(*[c.post("/orders", json={"lines": [{"variant_id": var["id"], "quantity": 1}]}, headers=hd) for _ in range(4)])
    rs = asyncio.run(dup())
    ids = {x.json().get("id") for x in rs if x.status_code == 201}
    n_orders = sql("SELECT count(*) AS n FROM orders WHERE user_id=(SELECT id FROM users WHERE telegram_id=$1)", USER_TG)[0]["n"]
    rec("idempotency: 4 concurrent same-key POST /orders -> exactly 1 new order", len(ids) == 1 and n_orders == 2, f"ids={ids} orders={n_orders} statuses={[x.status_code for x in rs]}")
    dup_order_id = next(iter(ids)) if ids else None

    # ---- payments ----------------------------------------------------
    r = user.req("POST", "/payments", json_body={"order_id": order["id"]}, key=True)
    rec("payment: submit -> 201", r.status_code == 201, str(r.status_code))
    pay = r.json()
    r = user.req("POST", "/payments", json_body={"order_id": order["id"]}, key=True)
    rec("payment: second submit (new key) returns the same PENDING payment, no duplicate", r.status_code in (200, 201) and r.json().get("id") == pay["id"], f"{r.status_code} id={r.json().get('id')} vs {pay['id']}")
    npay = sql("SELECT count(*) AS n FROM payments WHERE order_id=$1", order["id"])[0]["n"]
    rec("payment: exactly one payment row for the order", npay == 1, str(npay))
    r = other.req("POST", "/payments", json_body={"order_id": order["id"]}, key=True)
    rec("payment: other user pays my order -> 403", r.status_code == 403, str(r.status_code))
    r = user.req("POST", f"/payments/{pay['id']}/receipt", files={"file": ("x.png", b"not an image", "image/png")})
    rec("receipt: bad magic bytes -> 422", r.status_code == 422, str(r.status_code))
    r = other.req("POST", f"/payments/{pay['id']}/receipt", files={"file": ("x.png", png_bytes(), "image/png")})
    rec("receipt: other user's upload -> 403", r.status_code == 403, str(r.status_code))
    r = user.req("POST", f"/payments/{pay['id']}/receipt", files={"file": ("x.png", png_bytes(), "image/png")})
    rec("receipt: valid PNG -> 200", r.status_code == 200, str(r.status_code) + r.text[:120])
    o = user.req("GET", f"/orders/{order['id']}").json()
    rec("receipt: order now UNDER_REVIEW", o["status"] == "UNDER_REVIEW", o["status"])
    r = admin.req("GET", f"/admin/payments/{pay['id']}/receipt")
    url = r.json().get("url", "")
    rec("receipt: admin gets signed url", r.status_code == 200 and url.startswith("/files/receipts/") and "s=" in url and "e=" in url, url[:60])
    # signed url math vs nginx secure_link_md5 "$secure_link_expires$uri SECRET"
    import base64, re
    m = re.match(r"(/files/[^?]+)\?s=([^&]+)&e=(\d+)", url)
    raw = f"{m.group(3)}{m.group(1)} {os.environ['SIGNING_SECRET']}".encode()
    expect = base64.urlsafe_b64encode(hashlib.md5(raw).digest()).decode().rstrip("=")
    rec("signed-url: signature matches nginx secure_link_md5 formula", expect == m.group(2), "")
    rec("signed-url: receipts TTL ~15min", 0 < int(m.group(3)) - time.time() <= 15 * 60 + 5, "")
    fpath = os.path.join(os.environ["UPLOADS_ROOT"], m.group(1)[len("/files/"):])
    rec("receipt: file exists on disk under UPLOADS_ROOT as webp", os.path.exists(fpath) and open(fpath, "rb").read(12)[8:12] == b"WEBP", fpath)
    r = user.req("GET", f"/admin/payments/{pay['id']}/receipt")
    rec("receipt: USER cannot fetch admin receipt url -> 403", r.status_code == 403, str(r.status_code))

    # ---- payment reject -> order REJECTED (H6) ------------------------
    r = admin.req("POST", f"/admin/payments/{pay['id']}/review", json_body={"approve": False})
    rec("review: reject without reason -> 422", r.status_code == 422, str(r.status_code))
    r = admin.req("POST", f"/admin/payments/{pay['id']}/review", json_body={"approve": False, "rejection_reason": "blurry"})
    rec("review: reject -> 200 REJECTED", r.status_code == 200 and r.json()["status"] == "REJECTED", str(r.status_code))
    o = user.req("GET", f"/orders/{order['id']}").json()
    rec("review: rejected payment -> order REJECTED", o["status"] == "REJECTED", o["status"])
    r = admin.req("POST", f"/admin/payments/{pay['id']}/review", json_body={"approve": True})
    rec("review: approve after reject -> 422 (never reverts)", r.status_code == 422, str(r.status_code))
    p = sql("SELECT status FROM payments WHERE id=$1", pay["id"])[0]["status"]
    rec("review: payment still REJECTED in DB", p == "REJECTED", p)
    r = user.req("POST", f"/orders/{order['id']}/cancel", json_body={"reason": "changed my mind ok"})
    rec("cancel: REJECTED -> CANCELLED by user -> 200", r.status_code == 200 and r.json()["status"] == "CANCELLED", str(r.status_code))
    r = user.req("POST", f"/orders/{order['id']}/cancel", json_body={"reason": "changed my mind ok"})
    rec("cancel: double cancel -> 422", r.status_code == 422, str(r.status_code))
    rel = sql("SELECT count(*) AS n FROM stock_reservations WHERE order_id=$1 AND released_at IS NULL", order["id"])[0]["n"]
    rec("cancel: reservations released", rel == 0, str(rel))

    # ---- full happy path: approve + confirm + expiry worker (H2) ------
    r = user.req("POST", "/orders", json_body={"lines": [{"variant_id": var["id"], "quantity": 1}]}, key=True)
    o2 = r.json()
    p2 = user.req("POST", "/payments", json_body={"order_id": o2["id"]}, key=True).json()
    user.req("POST", f"/payments/{p2['id']}/receipt", files={"file": ("x.png", png_bytes(), "image/png")})
    r = admin.req("POST", f"/admin/payments/{p2['id']}/review", json_body={"approve": True})
    rec("review: approve -> 200", r.status_code == 200 and r.json()["status"] == "APPROVED", str(r.status_code))
    o2b = user.req("GET", f"/orders/{o2['id']}").json()
    rec("review: approve updates paid/remaining", o2b["paid_amount"] == o2b["total_amount"] and o2b["remaining_amount"] == 0, f"{o2b['paid_amount']}/{o2b['remaining_amount']}")
    before = sql("SELECT stock_on_hand, stock_reserved FROM product_variants WHERE id=$1", var["id"])[0]
    r = user.req("POST", f"/admin/orders/{o2['id']}/confirm", key=True)
    rec("confirm: USER -> 403", r.status_code == 403, str(r.status_code))
    ck = str(uuid.uuid4())
    r = admin.req("POST", f"/admin/orders/{o2['id']}/confirm", key=ck)
    rec("confirm: ADMIN -> 200 CONFIRMED", r.status_code == 200 and r.json()["status"] == "CONFIRMED", str(r.status_code) + r.text[:200])
    r = admin.req("POST", f"/admin/orders/{o2['id']}/confirm", key=ck)
    rec("confirm: replay same key -> 200 same", r.status_code == 200, str(r.status_code))
    r = admin.req("POST", f"/admin/orders/{o2['id']}/confirm", key=True)
    rec("confirm: second confirm new key -> 422", r.status_code == 422, str(r.status_code))
    after = sql("SELECT stock_on_hand, stock_reserved FROM product_variants WHERE id=$1", var["id"])[0]
    rec("confirm: on_hand-1, reserved-1", after["stock_on_hand"] == before["stock_on_hand"] - 1 and after["stock_reserved"] == before["stock_reserved"] - 1, f"{dict(before)} -> {dict(after)}")
    unrel = sql("SELECT count(*) AS n FROM stock_reservations WHERE order_id=$1 AND released_at IS NULL", o2["id"])[0]["n"]
    rec("confirm: reservation consumed (released_at set)", unrel == 0, f"unreleased={unrel}")
    # run expiry worker after backdating everything
    sql("UPDATE stock_reservations SET expires_at = now() - interval '1 hour' WHERE order_id=$1", o2["id"])
    from app.workers.reservation_expiry import run_once
    async def worker():
        conn = await asyncpg.connect(os.environ["DATABASE_URL"])
        try:
            return await run_once(conn)
        finally:
            await conn.close()
    try:
        released = asyncio.run(worker())
        werr = None
    except Exception as exc:  # noqa: BLE001
        released, werr = None, f"{type(exc).__name__}: {exc}"
    after2 = sql("SELECT stock_on_hand, stock_reserved FROM product_variants WHERE id=$1", var["id"])[0]
    rec("expiry worker after confirm: no release, no error, stock unchanged", werr is None and released == 0 and dict(after2) == dict(after), f"released={released} err={werr} {dict(after2)}")
    ostat = sql("SELECT status FROM orders WHERE id=$1", o2["id"])[0]["status"]
    rec("expiry worker: confirmed order stays CONFIRMED", ostat == "CONFIRMED", ostat)
    movs = sql("SELECT movement_type, count(*) AS n FROM inventory_movements WHERE reference_id=$1 AND reference_type='order' GROUP BY 1 ORDER BY 1", o2["id"])
    rec("ledger: order has RESERVE and OUT movements, no double RELEASE", {m["movement_type"]: m["n"] for m in movs} == {"OUT": 1, "RESERVE": 1}, str([dict(m) for m in movs]))

    # genuine expiry: dup_order (CREATED) backdated -> EXPIRED + released
    if dup_order_id:
        sql("UPDATE stock_reservations SET expires_at = now() - interval '1 hour' WHERE order_id=$1", dup_order_id)
        released = asyncio.run(worker())
        st2 = sql("SELECT status FROM orders WHERE id=$1", dup_order_id)[0]["status"]
        rec("expiry worker: CREATED order expires + releases", released == 1 and st2 == "EXPIRED", f"released={released} status={st2}")
    after3 = sql("SELECT stock_on_hand, stock_reserved FROM product_variants WHERE id=$1", var["id"])[0]
    rec("stock never negative", after3["stock_on_hand"] >= 0 and after3["stock_reserved"] >= 0, str(dict(after3)))
    # listing total_available after orders (H7)
    lst = user.req("GET", "/catalog/products", params={"limit": 100}).json()["items"]
    li = next(i for i in lst if i["id"] == pid)
    row = sql("SELECT COALESCE(SUM(GREATEST(v.stock_on_hand-v.stock_reserved,0)),0) AS avail FROM product_variants v WHERE v.product_id=$1 AND v.deleted_at IS NULL AND v.status='ACTIVE'", pid)[0]["avail"]
    rec("catalog: total_available not inflated by order_items", int(li["total_available"]) == int(row), f"{li['total_available']} vs {row}")

    # ---- admin: inventory + limits ------------------------------------
    r = admin.req("POST", "/admin/inventory/adjust", json_body={"variant_id": var["id"], "quantity_change": -100000, "reason": "audit"}, key=True)
    rec("inventory: adjust below reserved -> 422", r.status_code == 422, str(r.status_code))
    r = admin.req("POST", "/admin/inventory/adjust", json_body={"variant_id": var["id"], "quantity_change": 1, "reason": ""}, key=True)
    rec("inventory: adjust without reason -> 422", r.status_code == 422, str(r.status_code))
    r = admin.req("POST", "/admin/inventory/adjust", json_body={"variant_id": var["id"], "quantity_change": 1, "reason": "audit restock"}, key=True)
    rec("inventory: adjust +1 -> 201", r.status_code == 201, str(r.status_code))
    r = admin.req("GET", "/admin/orders", params={"limit": 200})
    rec("admin: /admin/orders?limit=200 -> 200", r.status_code == 200, str(r.status_code))
    r = admin.req("PATCH", "/admin/variants/%d" % var["id"], json_body={"stock_on_hand": 999})
    v = sql("SELECT stock_on_hand FROM product_variants WHERE id=$1", var["id"])[0]["stock_on_hand"]
    rec("admin: variant PATCH cannot set stock", v != 999, str(v))

    # ---- owner: deactivate admin -> token rejected ---------------------
    aid = sql("SELECT id FROM users WHERE telegram_id=$1", ADMIN_TG)[0]["id"]
    r = owner.req("POST", f"/owner/admins/{aid}/deactivate")
    rec("owner: deactivate admin -> 200", r.status_code == 200, str(r.status_code))
    r = admin.req("GET", "/admin/orders")
    rec("deactivated admin: existing token -> 403", r.status_code == 403, str(r.status_code))
    st, _ = session(ADMIN_TG)
    rec("deactivated admin: new session -> 403", st == 403, str(st))
    owner.req("POST", f"/owner/admins/{aid}/reactivate")
    r = admin.req("POST", "/owner/admins", json_body={"telegram_id": 700000099})
    rec("admin cannot create admins -> 403", r.status_code == 403, str(r.status_code))
    r = owner.req("POST", "/owner/admins", json_body={"telegram_id": OWNER_TG})
    rec("owner cannot demote self via create_admin -> 422", r.status_code == 422, str(r.status_code))
    r = owner.req("GET", "/owner/audit-logs", params={"limit": 5})
    logs = r.json()
    rec("owner: audit logs paginate", r.status_code == 200 and logs["next_cursor"], "")
    r2 = owner.req("GET", "/owner/audit-logs", params={"limit": 5, "cursor": logs["next_cursor"]})
    rec("owner: audit page2 -> 200", r2.status_code == 200, str(r2.status_code))
    r = owner.req("PUT", "/owner/settings", json_body={"settings": {"store_name": "Audit"}})
    rec("owner: put settings -> 200", r.status_code == 200 and r.json().get("store_name") == "Audit", str(r.status_code))

    # ---- error handling ----------------------------------------------
    r = user.req("POST", "/cart/items", json_body={"variant_id": "abc"})
    b = r.json()
    rec("validation error carries error envelope", r.status_code == 422 and isinstance(b.get("error"), dict), str(list(b)))
    r = user.req("GET", "/catalog/products", params={"limit": 3, "cursor": "!!!"}, headers={"X-Request-ID": "smoke-req-1"})
    rec("X-Request-ID echoed", r.headers.get("x-request-id") == "smoke-req-1", str(r.headers.get("x-request-id")))
    r = httpx.post(f"{API}/telegram/webhook", json={"update_id": 1}, headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"}, timeout=30)
    rec("webhook: wrong secret -> 401", r.status_code == 401, str(r.status_code))
    r = httpx.post(f"{API}/telegram/webhook", content=b"{not json", headers={"X-Telegram-Bot-Api-Secret-Token": os.environ["TELEGRAM_WEBHOOK_SECRET"], "Content-Type": "application/json"}, timeout=30)
    rec("webhook: malformed body -> 400 (not 500)", r.status_code == 400, str(r.status_code))

    fails = [x for x in results if x[1] == "FAIL"]
    print(f"\n== {len(results) - len(fails)} PASS / {len(fails)} FAIL ==")


if __name__ == "__main__":
    main()
