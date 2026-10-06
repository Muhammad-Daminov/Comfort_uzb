"""Post-audit verification matrix (docs/12_POST_AUDIT_STABILIZATION_REPORT.md): deeper checks over real HTTP — pagination walks, search modes, the full order/payment state-transition matrix, concurrent confirm, cross-user idempotency, RBAC per endpoint, stock/ledger invariants. Same env as audit_smoke.py. DISPOSABLE DATABASE ONLY (creates orders, runs the expiry worker, backdates rows). Two expected FAIL lines document the known price-sort/display limitation."""
import asyncio, hashlib, hmac, io, json, os, time, uuid
from urllib.parse import urlencode
import asyncpg, httpx
from PIL import Image
API = "http://127.0.0.1:8123"; TOKEN = os.environ["BOT_TOKEN"]; SUPER = os.environ["SUPERUSER_DATABASE_URL"]
R = []
def rec(n, ok, note=""): R.append((n, ok, note)); print(f"[{'PASS' if ok else 'FAIL'}] {n} {note}")
def init_data(tg, uid=None, fname="V"):
    user = json.dumps({"id": tg, "first_name": fname}); data = {"auth_date": str(int(time.time())), "user": user}
    chk = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    sec = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    data["hash"] = hmac.new(sec, chk.encode(), hashlib.sha256).hexdigest()
    if uid is not None: data["user"] = json.dumps({"id": uid, "first_name": fname})  # tamper after signing
    return urlencode(data)
def sql(q, *a):
    async def run():
        c = await asyncpg.connect(SUPER)
        try: return await c.fetch(q, *a)
        finally: await c.close()
    return asyncio.run(run())
def png():
    b = io.BytesIO(); Image.new("RGB", (20, 20), (1, 2, 3)).save(b, format="PNG"); return b.getvalue()
class C:
    def __init__(s, tok=None): s.h = {"Authorization": f"Bearer {tok}"} if tok else {}; s.c = httpx.Client(base_url=API, timeout=30)
    def r(s, m, p, json_body=None, key=None, files=None, params=None):
        h = dict(s.h)
        if key: h["Idempotency-Key"] = key if isinstance(key, str) else str(uuid.uuid4())
        return s.c.request(m, p, json=json_body, headers=h, files=files, params=params)
def sess(tg, **kw):
    r = httpx.post(f"{API}/auth/session", json={"initData": init_data(tg, **kw)}, timeout=30); return r.status_code, (r.json() if r.content else {})

OWNER_TG = int(os.environ["OWNER_TELEGRAM_ID"])
owner = C(sess(OWNER_TG)[1]["token"])
owner.r("POST", "/owner/admins", json_body={"telegram_id": 710000002})
admin = C(sess(710000002)[1]["token"]); user = C(sess(710000001)[1]["token"]); other = C(sess(710000003)[1]["token"])

# ---- identity tampering ------------------------------------------------
st, _ = sess(710000001, uid=OWNER_TG)
rec("auth: user id swapped after signing -> 401", st == 401, str(st))
r = httpx.post(f"{API}/auth/session", json={"initData": init_data(710000001) + "&role=OWNER"}, timeout=30)
rec("auth: extra role field breaks hash -> 401", r.status_code == 401, str(r.status_code))

# ---- catalog pagination walk ---------------------------------------------
total = sql("SELECT count(*) AS n FROM products p WHERE p.status='ACTIVE' AND p.deleted_at IS NULL AND EXISTS (SELECT 1 FROM product_variants v WHERE v.product_id=p.id AND v.deleted_at IS NULL AND v.status='ACTIVE')")[0]["n"]
for sort in ("newest", "price_asc", "price_desc", "popular"):
    seen, cursor, pages, walks = [], None, 0, []
    for _ in range(2):
        seen, cursor, pages = [], None, 0
        while True:
            p = user.r("GET", "/catalog/products", params={"limit": 5, "sort": sort, **({"cursor": cursor} if cursor else {})})
            assert p.status_code == 200, p.text
            body = p.json(); pages += 1
            seen += [i["id"] for i in body["items"]]
            cursor = body["next_cursor"]
            if not cursor or not body["items"] or pages > 20: break
        walks.append(list(seen))
    rec(f"pagination {sort}: all {total} products once, no dupes", len(seen) == len(set(seen)) == total, f"seen={len(seen)} pages={pages}")
    rec(f"pagination {sort}: stable ordering across two walks", walks[0] == walks[1], "")
    rec(f"pagination {sort}: last page has no next_cursor (no phantom 'load more')", cursor is None, f"cursor={cursor!r}")
    if sort.startswith("price"):
        prices = [next(i for i in user.r("GET", "/catalog/products", params={"limit": 100, "sort": sort}).json()["items"] if i["id"] == pid)["min_price"] for pid in seen]
        base = [sql("SELECT MIN(price) AS m FROM product_variants WHERE product_id=$1 AND status='ACTIVE' AND deleted_at IS NULL", pid)[0]["m"] for pid in seen]
        rec(f"pagination {sort}: monotonic on the sort key (base min price)", base == sorted(base, reverse=(sort == "price_desc")), "")
        rec(f"pagination {sort}: displayed (discounted) price monotonic", prices == sorted(prices, reverse=(sort == "price_desc")), "KNOWN LIMITATION: sort key is base price, display is discounted")
p = user.r("GET", "/catalog/products", params={"limit": 5, "brand_id": 999999})
rec("pagination: empty first page -> 200, next_cursor null", p.status_code == 200 and p.json() == {"items": [], "next_cursor": None}, p.text[:80])

# ---- search modes ----------------------------------------------------------
def s(q): return user.r("GET", "/catalog/search", params={"q": q})
for q, expect in (("poyandoz", True), ("Poyandoz to'plami", True), ("poyan", True), ("poyandos", True), ("пояндоз", True), ("camry gilam", True), ("neksiya salon", True), ("zzzzqqq", False)):
    r = s(q); items = r.json().get("items", [])
    rec(f"search {q!r}: {'hits' if expect else 'empty'}", r.status_code == 200 and (bool(items) == expect), f"{r.status_code} n={len(items)}")
    if items: rec(f"search {q!r}: prices numeric, no NaN", all(isinstance(i["min_price"], int) and isinstance(i["total_available"], int) for i in items), "")
r = s(""); rec("search '': 422", r.status_code == 422, str(r.status_code))
hits = s("poyandoz").json()["items"]
rec("search ranking: best match first", hits and "oyandoz" in hits[0]["name"].lower(), hits[0]["name"] if hits else "")

# ---- discounted flow end to end ----------------------------------------------
pid = sql("SELECT dt.target_id FROM discount_targets dt JOIN discounts d ON d.id=dt.discount_id WHERE dt.target_type='PRODUCT' AND d.is_active ORDER BY 1 LIMIT 1")[0]["target_id"]
card = next(i for i in user.r("GET", "/catalog/products", params={"limit": 100}).json()["items"] if i["id"] == pid)
det = user.r("GET", f"/catalog/products/{pid}").json(); var = min((v for v in det["variants"] if v["status"] == "ACTIVE"), key=lambda v: v["current_price"])
rec("discount: card min_price == cheapest variant current_price, old_price set", card["min_price"] == var["current_price"] and card["old_price"] == var["price"], f"{card['min_price']}/{card['old_price']} vs {var['current_price']}/{var['price']}")
admin.r("POST", "/admin/inventory/adjust", json_body={"variant_id": var["id"], "quantity_change": 500, "reason": "verification stock"}, key=True)
user.r("POST", "/cart/items", json_body={"variant_id": var["id"], "quantity": 2})
ci = user.r("GET", "/cart").json()["items"][0]
rec("discount: cart current_price == detail current_price", ci["current_price"] == var["current_price"] and ci["price"] == var["price"], "")
o = user.r("POST", "/orders", json_body={"lines": [{"variant_id": var["id"], "quantity": 2, "client_unit_price": ci["current_price"]}]}, key=True)
rec("discount: checkout with cart price -> 201, total = 2*current", o.status_code == 201 and o.json()["total_amount"] == 2 * var["current_price"], f"{o.status_code} {o.json().get('total_amount')}")
oi = sql("SELECT unit_price, discount_amount, line_total, quantity FROM order_items WHERE order_id=$1", o.json()["id"])[0]
rec("discount: snapshot unit_price=base, discount_amount=2*per-unit, line_total consistent", oi["unit_price"] == var["price"] and oi["discount_amount"] == 2 * var["discount_amount"] and oi["line_total"] == oi["unit_price"] * 2 - oi["discount_amount"], str(dict(oi)))
pay = user.r("POST", "/payments", json_body={"order_id": o.json()["id"]}, key=True).json()
rec("discount: payment amount = discounted remaining", pay["amount"] == 2 * var["current_price"], str(pay["amount"]))
rec("cart cleared after checkout", user.r("GET", "/cart").json()["items"] == [], "")

# ---- full state transition matrix -------------------------------------------
def mk_order(client=user, qty=1):
    return client.r("POST", "/orders", json_body={"lines": [{"variant_id": var["id"], "quantity": qty}]}, key=True).json()
def to_state(state):
    o = mk_order(); oid = o["id"]; pid_ = None
    if state in ("AWAITING_PAYMENT", "PAYMENT_SUBMITTED", "UNDER_REVIEW", "REJECTED", "CONFIRMED", "APPROVED_UNDER_REVIEW"):
        pid_ = user.r("POST", "/payments", json_body={"order_id": oid}, key=True).json()["id"]
    if state in ("UNDER_REVIEW", "REJECTED", "CONFIRMED", "APPROVED_UNDER_REVIEW"):
        user.r("POST", f"/payments/{pid_}/receipt", files={"file": ("x.png", png(), "image/png")})
    if state == "REJECTED": admin.r("POST", f"/admin/payments/{pid_}/review", json_body={"approve": False, "rejection_reason": "no"})
    if state in ("CONFIRMED", "APPROVED_UNDER_REVIEW"): admin.r("POST", f"/admin/payments/{pid_}/review", json_body={"approve": True})
    if state == "CONFIRMED": admin.r("POST", f"/admin/orders/{oid}/confirm", key=True)
    if state == "EXPIRED":
        sql("UPDATE stock_reservations SET expires_at=now()-interval '1 hour' WHERE order_id=$1", oid)
        from app.workers.reservation_expiry import run_once
        async def w():
            c = await asyncpg.connect(os.environ["DATABASE_URL"]); 
            try: return await run_once(c)
            finally: await c.close()
        asyncio.run(w())
    if state == "CANCELLED": user.r("POST", f"/orders/{oid}/cancel", json_body={"reason": "cancel for matrix"})
    st = sql("SELECT status FROM orders WHERE id=$1", oid)[0]["status"]
    return oid, pid_, st
expect_state = {"CREATED": "CREATED", "AWAITING_PAYMENT": "AWAITING_PAYMENT", "UNDER_REVIEW": "UNDER_REVIEW", "REJECTED": "REJECTED", "CONFIRMED": "CONFIRMED", "EXPIRED": "EXPIRED", "CANCELLED": "CANCELLED", "APPROVED_UNDER_REVIEW": "UNDER_REVIEW"}
for state, exp in expect_state.items():
    oid, pid_, st = to_state(state)
    rec(f"state setup {state}", st == exp, st)
    # user cancel
    r = user.r("POST", f"/orders/{oid}/cancel", json_body={"reason": "matrix cancel attempt"})
    allowed = state in ("CREATED", "AWAITING_PAYMENT", "UNDER_REVIEW", "REJECTED", "APPROVED_UNDER_REVIEW")
    rec(f"  user cancel from {state} -> {'200' if allowed else '422'}", r.status_code == (200 if allowed else 422), str(r.status_code))
    if allowed:
        rel = sql("SELECT count(*) AS n FROM stock_reservations WHERE order_id=$1 AND released_at IS NULL", oid)[0]["n"]
        rec(f"  reservations released after cancel from {state}", rel == 0, str(rel))
    oid2, pid2, _ = to_state(state)
    r = admin.r("POST", f"/admin/orders/{oid2}/confirm", key=True)
    rec(f"  admin confirm from {state} -> {'200' if state in ('UNDER_REVIEW','APPROVED_UNDER_REVIEW') else '422'}", r.status_code == (200 if state in ("UNDER_REVIEW", "APPROVED_UNDER_REVIEW") else 422), str(r.status_code))
    if pid2:
        r = admin.r("POST", f"/admin/payments/{pid2}/review", json_body={"approve": True})
        # after the confirm above: UNDER_REVIEW(pending payment) is CONFIRMED now -> approve still allowed (OPEN-8); REJECTED/APPROVED -> 422; CANCELLED/EXPIRED -> 422
        exp_code = 200 if state == "UNDER_REVIEW" else (200 if state == "AWAITING_PAYMENT" else 422)
        rec(f"  approve payment of {state} order -> {exp_code}", r.status_code == exp_code, str(r.status_code))
    r = user.r("POST", "/payments", json_body={"order_id": oid2}, key=True)
    rec(f"  submit payment on {state} order -> {'201' if state in ('CREATED','AWAITING_PAYMENT') else '422'}", r.status_code == (201 if state in ("CREATED", "AWAITING_PAYMENT") else 422), str(r.status_code))

# duplicate approval idempotent (paid_amount never double-counted)
oid, pid_, _ = to_state("UNDER_REVIEW")
a1 = admin.r("POST", f"/admin/payments/{pid_}/review", json_body={"approve": True}); a2 = admin.r("POST", f"/admin/payments/{pid_}/review", json_body={"approve": True})
paid = sql("SELECT paid_amount, total_amount FROM orders WHERE id=$1", oid)[0]
rec("duplicate approval: second -> 422, paid_amount == total exactly once", a1.status_code == 200 and a2.status_code == 422 and paid["paid_amount"] == paid["total_amount"], f"{a1.status_code}/{a2.status_code} {dict(paid)}")
r = admin.r("POST", f"/admin/payments/{pid_}/review", json_body={"approve": False, "rejection_reason": "late"})
rec("approved -> reject attempt -> 422 (never reverts)", r.status_code == 422 and sql("SELECT status FROM payments WHERE id=$1", pid_)[0]["status"] == "APPROVED", str(r.status_code))
# double confirmation (sequential + concurrent)
r1 = admin.r("POST", f"/admin/orders/{oid}/confirm", key=True); r2 = admin.r("POST", f"/admin/orders/{oid}/confirm", key=True)
rec("double confirm sequential: 200 then 422", (r1.status_code, r2.status_code) == (200, 422), f"{r1.status_code}/{r2.status_code}")
oidc, pidc, _ = to_state("APPROVED_UNDER_REVIEW"); before = sql("SELECT stock_on_hand, stock_reserved FROM product_variants WHERE id=$1", var["id"])[0]
async def conc():
    async with httpx.AsyncClient(base_url=API, timeout=30) as c:
        return await asyncio.gather(*[c.post(f"/admin/orders/{oidc}/confirm", headers={**admin.h, "Idempotency-Key": str(uuid.uuid4())}) for _ in range(4)])
rs = asyncio.run(conc()); after = sql("SELECT stock_on_hand, stock_reserved FROM product_variants WHERE id=$1", var["id"])[0]
rec("concurrent confirm x4 (distinct keys): exactly one 200, stock decremented once", sorted(x.status_code for x in rs) == [200, 409, 409, 409] or sorted(x.status_code for x in rs) == [200, 422, 422, 422] and after["stock_on_hand"] == before["stock_on_hand"] - 1 and after["stock_reserved"] == before["stock_reserved"] - 1, f"{[x.status_code for x in rs]} {dict(before)}->{dict(after)}")
rec("concurrent confirm: stock decremented exactly once", after["stock_on_hand"] == before["stock_on_hand"] - 1 and after["stock_reserved"] == before["stock_reserved"] - 1, f"{dict(before)}->{dict(after)}")
movs = sql("SELECT movement_type, count(*) AS n FROM inventory_movements WHERE reference_type='order' AND reference_id=$1 GROUP BY 1", oidc)
rec("concurrent confirm: ledger has one OUT", {m["movement_type"]: m["n"] for m in movs} == {"RESERVE": 1, "OUT": 1}, str([dict(m) for m in movs]))

# ---- idempotency: replay by another user, different payload ---------------------
key = str(uuid.uuid4()); body = {"lines": [{"variant_id": var["id"], "quantity": 1}]}
r1 = user.r("POST", "/orders", json_body=body, key=key); r2 = other.r("POST", "/orders", json_body=body, key=key)
rec("idempotency: same key replayed by ANOTHER user -> 422, no cross-user replay", r1.status_code == 201 and r2.status_code == 422, f"{r1.status_code}/{r2.status_code}")
r3 = user.r("POST", "/orders", json_body={"lines": [{"variant_id": var["id"], "quantity": 2}]}, key=key)
rec("idempotency: same key different payload -> 422", r3.status_code == 422, str(r3.status_code))
n_before = sql("SELECT count(*) AS n FROM orders")[0]["n"]
r4 = user.r("POST", "/orders", json_body=body, key=key)
rec("idempotency: replay same payload -> same order, no new row", r4.status_code == 201 and r4.json()["id"] == r1.json()["id"] and sql("SELECT count(*) AS n FROM orders")[0]["n"] == n_before, "")

# ---- RBAC matrix: USER on every staff mutation; ADMIN on every owner endpoint -----
staff = [("POST", f"/admin/orders/{oid}/confirm", None, True), ("POST", f"/admin/orders/{oid}/cancel", {"reason": "0123456789"}, True), ("POST", "/admin/inventory/adjust", {"variant_id": var["id"], "quantity_change": 1, "reason": "x"}, True),
         ("POST", "/admin/products", {"name": "x", "brand_id": 1}, False), ("PATCH", f"/admin/products/{pid}", {"name": "x"}, False), ("POST", f"/admin/products/{pid}/status", {"status": "ARCHIVED"}, False),
         ("POST", "/admin/variants", {"product_id": pid, "sku": "X", "price": 1}, False), ("PATCH", f"/admin/variants/{var['id']}", {"price": 1}, False), ("POST", f"/admin/variants/{var['id']}/status", {"status": "ARCHIVED"}, False),
         ("POST", "/admin/brands", {"name": "x"}, False), ("POST", "/admin/colors", {"name": "x"}, False), ("POST", f"/admin/products/{pid}/compatibilities", {"generation_id": 1}, False), ("DELETE", f"/admin/products/{pid}/compatibilities/1", None, False),
         ("DELETE", f"/admin/products/{pid}/images/1", None, False), ("POST", f"/admin/products/{pid}/images/1/primary", None, False), ("GET", "/admin/orders", None, False), ("GET", "/admin/payments", None, False),
         ("POST", f"/admin/payments/{pid_}/review", {"approve": True}, False), ("GET", f"/admin/payments/{pid_}/receipt", None, False), ]
bad = [f"{m} {p}={user.r(m, p, json_body=b, key=k).status_code}" for m, p, b, k in staff if user.r(m, p, json_body=b, key=k).status_code != 403]
rec(f"RBAC: USER denied on all {len(staff)} staff endpoints", not bad, str(bad))
r = user.r("POST", f"/admin/products/{pid}/images", files={"file": ("x.png", png(), "image/png")}); rec("RBAC: USER image upload -> 403", r.status_code == 403, str(r.status_code))
ownerish = [("GET", "/owner/dashboard", None), ("GET", "/owner/finance?from=2026-01-01&to=2026-02-01", None), ("GET", "/owner/analytics?from=2026-01-01&to=2026-02-01", None), ("GET", "/owner/admins", None), ("POST", "/owner/admins", {"telegram_id": 5}), ("POST", "/owner/admins/1/deactivate", None), ("POST", "/owner/admins/1/reactivate", None), ("GET", "/owner/audit-logs", None), ("GET", "/owner/settings", None), ("PUT", "/owner/settings", {"settings": {"a": 1}})]
bad = [f"{m} {p}={admin.r(m, p, json_body=b).status_code}" for m, p, b in ownerish if admin.r(m, p, json_body=b).status_code != 403]
rec(f"RBAC: ADMIN denied on all {len(ownerish)} owner endpoints", not bad, str(bad))
bad = [f"{m} {p}={user.r(m, p, json_body=b).status_code}" for m, p, b in ownerish if user.r(m, p, json_body=b).status_code != 403]
rec("RBAC: USER denied on all owner endpoints", not bad, str(bad))
r = user.r("POST", "/owner/admins", json_body={"telegram_id": 710000001, "role": "OWNER"}); rec("RBAC: USER cannot self-promote via body", r.status_code == 403, str(r.status_code))
r = admin.r("POST", "/admin/orders/%d/confirm" % oid, key=True); rec("ADMIN confirm allowed (already confirmed -> 422 not 403)", r.status_code == 422, str(r.status_code))
# other user's order via admin path is fine; via user path 403
oo = mk_order(other); r = user.r("GET", f"/orders/{oo['id']}"); rec("IDOR: read other's order -> 403", r.status_code == 403, str(r.status_code))
r = user.r("POST", f"/orders/{oo['id']}/cancel", json_body={"reason": "not my order!!"}); rec("IDOR: cancel other's order -> 403", r.status_code == 403, str(r.status_code))
r = user.r("POST", "/payments", json_body={"order_id": oo["id"]}, key=True); rec("IDOR: pay other's order -> 403", r.status_code == 403, str(r.status_code))

# ---- deactivated OWNER? (cannot deactivate via API) ----------------------------------
r = owner.r("POST", f"/owner/admins/{sql('SELECT id FROM users WHERE role=$1', 'OWNER')[0]['id']}/deactivate"); rec("owner cannot deactivate the OWNER row -> 404", r.status_code == 404, str(r.status_code))
# ---- stock invariant ---------------------------------------------------------------
bad = sql("SELECT count(*) AS n FROM product_variants WHERE stock_on_hand < 0 OR stock_reserved < 0 OR stock_reserved > stock_on_hand")[0]["n"]
rec("invariant: no negative / over-reserved stock after all flows", bad == 0, str(bad))
# reserved equals sum of open reservations
mism = sql("SELECT count(*) AS n FROM product_variants v WHERE v.stock_reserved <> COALESCE((SELECT SUM(quantity) FROM stock_reservations r WHERE r.variant_id=v.id AND r.released_at IS NULL),0)")[0]["n"]
rec("invariant: stock_reserved == sum(open reservations) for every variant", mism == 0, str(mism))
fails = [x for x in R if not x[1]]; print(f"\n== {len(R)-len(fails)} PASS / {len(fails)} FAIL ==")
