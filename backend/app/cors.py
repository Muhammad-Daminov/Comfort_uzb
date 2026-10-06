"""CORS configuration (Phase 09 §12).

The primary production deployment serves the built Mini App and the API
from the same origin (Nginx routes `/` to the static `dist/` build and
`/auth`, `/catalog`, etc. to FastAPI on the same domain — see
`docs/09_DEPLOYMENT.md`), which needs no CORS grant at all: same-origin
requests aren't subject to CORS in the first place. This module exists for
the cases that genuinely are cross-origin — a separately-hosted Mini App
build, a staging frontend on a different subdomain, or local frontend dev
against a deployed backend — and is explicit and closed by default rather
than silently permissive.

`ALLOWED_ORIGINS` is a comma-separated env var. Unset or empty means no
cross-origin access is granted at all (not a wildcard) — the safe default
for a same-origin deployment. `*` is never used for this project: the API
issues bearer tokens (not cookies), so `*` wouldn't even be a credential
leak in the browser-cookie sense, but an explicit, reviewable allowlist
costs nothing and removes the question entirely.
"""
from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def install_cors(app: FastAPI) -> None:
    raw = os.environ.get("ALLOWED_ORIGINS", "")
    origins = [origin.strip() for origin in raw.split(",") if origin.strip()]
    if not origins:
        return  # same-origin deployment — no CORS middleware needed at all
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
        allow_credentials=False,  # bearer-token auth, not cookies — no credentialed CORS needed
    )
