"""Signed-URL generation for Nginx `secure_link` (ADR-13). Copied verbatim
from the ADR's own code sketch — the exact string format hashed here MUST
match Nginx's `secure_link_md5` directive byte-for-byte or every link 403s;
this is not a place to "improve" the algorithm independently.

Only generation lives here. Nginx-side verification config is `devops`'s
job (Phase-09) — this module produces the query string, nothing serves the
file.
"""
from __future__ import annotations

import base64
import hashlib
import time

# TTLs per §11.1, by upload directory.
TTL_SECONDS_BY_FOLDER = {
    "products": 24 * 60 * 60,
    "receipts": 15 * 60,
    "sell-requests": 60 * 60,
    "chat": 60 * 60,
}


def signed_url(path: str, secret: str, *, ttl_seconds: int, now: float | None = None) -> str:
    current_time = now if now is not None else time.time()
    expires = int(current_time) + ttl_seconds
    raw = f"{expires}/files/{path} {secret}"
    digest = hashlib.md5(raw.encode()).digest()  # noqa: S324 — required by Nginx secure_link_md5, not a security-strength hash use
    sig = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return f"/files/{path}?s={sig}&e={expires}"


def signed_url_for_folder(path: str, folder: str, secret: str, *, now: float | None = None) -> str:
    ttl_seconds = TTL_SECONDS_BY_FOLDER.get(folder)
    if ttl_seconds is None:
        raise ValueError(f"unknown signed-URL folder: {folder!r}")
    return signed_url(path, secret, ttl_seconds=ttl_seconds, now=now)
