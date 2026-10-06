"""`app/security/signing.py` had no unit test at all — the generator's
expiry arithmetic and its byte-for-byte agreement with Nginx's
`secure_link_md5 "$secure_link_expires$uri <secret>"` directive
(deploy/nginx/comfort.conf.template) are what every /files/ URL depends on."""
from __future__ import annotations

import base64
import hashlib

import pytest

from app.security.signing import TTL_SECONDS_BY_FOLDER, signed_url, signed_url_for_folder


def _nginx_side(uri: str, expires: int, secret: str) -> str:
    # What Nginx computes for `secure_link_md5 "$secure_link_expires$uri SECRET"`,
    # compared base64url-without-padding against $arg_s.
    digest = hashlib.md5(f"{expires}{uri} {secret}".encode()).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def test_signature_matches_the_nginx_secure_link_formula():
    url = signed_url("products/7/abc.webp", "s3cret", ttl_seconds=60, now=1_700_000_000)
    assert url == f"/files/products/7/abc.webp?s={_nginx_side('/files/products/7/abc.webp', 1_700_000_060, 's3cret')}&e=1700000060"


def test_expiry_is_now_plus_folder_ttl():
    for folder, ttl in TTL_SECONDS_BY_FOLDER.items():
        url = signed_url_for_folder("x.webp", folder, "k", now=1_000)
        assert url.endswith(f"&e={1_000 + ttl}")


def test_different_secret_or_path_changes_signature():
    a = signed_url("receipts/a.webp", "k1", ttl_seconds=10, now=0)
    b = signed_url("receipts/a.webp", "k2", ttl_seconds=10, now=0)
    c = signed_url("receipts/b.webp", "k1", ttl_seconds=10, now=0)
    assert len({a, b, c}) == 3


def test_unknown_folder_is_rejected():
    with pytest.raises(ValueError):
        signed_url_for_folder("x", "nope", "k")
