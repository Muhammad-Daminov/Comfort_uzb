# ADR-013 — Signed URLs via Nginx `secure_link`

**Status:** Accepted
**Owner:** security
**Domain:** Security / File Storage
**Last updated:** 2026-08-17
**Source:** [00_MASTER_TZ.md](../00_MASTER_TZ.md) §1 ADR-13, §11

## Context
Supabase Storage used to issue signed URLs itself. Self-hosting on Contabo means this has to be built. Serving files through Python (FastAPI) would work but is slow compared to Nginx serving them directly once a signature is verified.

## Decision
Backend generates the signature, Nginx verifies it and serves the file — Python never streams file bytes.

Backend (signing):
```python
def signed_url(path: str, ttl_seconds: int = 3600) -> str:
    expires = int(time.time()) + ttl_seconds
    raw = f"{expires}/files/{path} {SECRET}"
    digest = hashlib.md5(raw.encode()).digest()
    sig = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return f"/files/{path}?s={sig}&e={expires}"
```
Nginx (verifying):
```nginx
location /files/ {
    secure_link         $arg_s,$arg_e;
    secure_link_md5     "$secure_link_expires$uri SECRET";
    if ($secure_link = "")  { return 403; }
    if ($secure_link = "0") { return 410; }
    alias /var/comfort/uploads/;
    add_header Cache-Control "private, max-age=3600";
}
```
Key details: `$remote_addr` is deliberately **not** part of the signature (mobile IPs roam mid-session and would break the link). Requires `nginx-extras` (verify with `nginx -V 2>&1 | grep secure_link`). TTL differs by folder: receipts 15min, product images 24h (full table in §11.1). `SECRET` comes from env, never hardcoded.

## Consequences
- `security` owns the signing function and the shared secret; `devops` owns the Nginx config that verifies it — both must agree on the secret and the exact string format being hashed, or every link 403s.
- No domain that produces files (Catalog images, Payments receipts, Marketplace images, Communication attachments) may construct its own URL scheme — all go through this one signer (REQ-FS-002).
- REQ-TST-001 mandates two tests here specifically: unsigned `/files/receipts/...` → 403, expired signature → 410.
