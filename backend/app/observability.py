"""OPEN-2 resolution (b) — structured, log-based error visibility, no new
external dependency. See docs/06_OPEN_DECISIONS.md OPEN-2 and
docs/08_SECURITY.md "Observability".

This module owns two things: a structured logging configuration, and a
global FastAPI exception handler that guarantees every unexpected exception
is (a) logged server-side with a correlation id and full traceback, and (b)
never leaks its details (message, type, SQL, stack trace) to the client —
only a generic body plus the same correlation id, so a report from a user
can be matched back to the server-side log line.

Actually shipping these log lines to an alert channel (Telegram, per the
TZ's own recommended OPEN-2 resolution, or journald/log-shipping) is
deployment wiring — Phase-09's job (systemd unit + `bot`'s existing
notification channel or a log-forwarding rule), not this module's. This
module's job ends at "the log line exists, is structured, and is safe."
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from contextvars import ContextVar

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

_request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id_var.get()
        return True


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    """Idempotent — safe to call more than once (e.g. once from `main.py`
    import time, once from a test fixture) without duplicating handlers."""
    root = logging.getLogger()
    if getattr(root, "_comfort_configured", False):
        return

    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    handler = logging.StreamHandler()
    handler.setFormatter(_JsonFormatter())
    handler.addFilter(_RequestIdFilter())

    root.handlers = [handler]
    root.setLevel(level)
    root._comfort_configured = True  # type: ignore[attr-defined]


logger = logging.getLogger("comfort")


def install_exception_handling(app: FastAPI) -> None:
    """Registers the request-id middleware + the catch-all handler. Expected
    4xx (`HTTPException`) is explicitly passed through untouched — it is not
    an application failure, so it is logged at most at INFO/WARNING, never
    ERROR, and never re-wrapped."""

    @app.middleware("http")
    async def _request_id_middleware(request: Request, call_next):
        request_id = _request_id_for(request)
        token = _request_id_var.set(request_id)
        start = time.monotonic()
        try:
            response = await call_next(request)
        finally:
            _request_id_var.reset(token)
        response.headers["X-Request-ID"] = request_id
        duration_ms = round((time.monotonic() - start) * 1000, 2)
        logger.info(f"{request.method} {request.url.path} -> {response.status_code} ({duration_ms}ms)")
        return response

    @app.exception_handler(HTTPException)
    async def _http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        # Expected, already-classified errors (4xx/409/etc.) — never a
        # "something is broken" signal, so logged at WARNING at most and
        # passed through with their own status/detail unchanged.
        if exc.status_code >= 500:
            logger.error(f"HTTPException {exc.status_code}: {exc.detail}", exc_info=exc)
        else:
            logger.warning(f"HTTPException {exc.status_code}: {exc.detail}")
        response = JSONResponse(status_code=exc.status_code, content=error_body(exc.status_code, exc.detail))
        response.headers["X-Request-ID"] = _request_id_for(request)
        return response

    @app.exception_handler(RequestValidationError)
    async def _validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Pydantic/FastAPI request-shape failures get the same §13.5 envelope
        # as every other 422, instead of FastAPI's bare `{"detail": [...]}`.
        errors = jsonable_encoder(exc.errors())
        logger.warning(f"validation error on {request.method} {request.url.path}: {errors}")
        body = {
            "detail": errors,
            "error": {"code": "VALIDATION_ERROR", "message": "So'rov noto'g'ri", "details": {"errors": errors}},
        }
        response = JSONResponse(status_code=422, content=body)
        response.headers["X-Request-ID"] = _request_id_for(request)
        return response

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        # Runs in Starlette's outermost ServerErrorMiddleware, AFTER our own
        # middleware's `finally` has already reset the ContextVar — reading
        # the var here gave "-" for exactly the responses whose id matters
        # most. Re-derive it from the request instead.
        request_id = _request_id_for(request)
        logger.error(f"unhandled exception on {request.method} {request.url.path} [request_id={request_id}]", exc_info=exc)
        response = JSONResponse(
            status_code=500,
            content={
                "detail": "internal server error",
                "request_id": request_id,
                "error": {"code": "INTERNAL_ERROR", "message": "Serverda vaqtinchalik xatolik", "details": {"request_id": request_id}},
            },
        )
        response.headers["X-Request-ID"] = request_id
        return response


_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def _request_id_for(request: Request) -> str:
    """One id per request, stable across the middleware and the exception
    handlers (which run outside it). A client-supplied X-Request-ID is
    honoured only if it is a short, plain token — anything else would be
    copied verbatim into JSON logs and a response header."""
    cached = getattr(request.state, "request_id", None)
    if cached:
        return cached
    supplied = request.headers.get("X-Request-ID", "")
    request_id = supplied if _REQUEST_ID_RE.match(supplied) else str(uuid.uuid4())
    request.state.request_id = request_id
    return request_id


_GENERIC_CODES = {
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
    422: "VALIDATION_ERROR",
}


def error_body(status_code: int, detail: object) -> dict:
    """§13.5 / docs/04_API_SPEC.md: every error response carries
    `{"error": {"code", "message", "details"}}`. Routers raise either a plain
    string detail or an already-shaped `{"error": {...}}` dict; both are
    normalised here. `detail` is kept alongside for FastAPI-conventional
    clients and existing tests — it is the same information, never more.

    Before this the body was `{"detail": ...}` only, so the Mini App's
    client (which reads `payload.error`) never saw an error code: the
    checkout's PRICE_MISMATCH / INSUFFICIENT_STOCK handling was dead code."""
    if isinstance(detail, dict) and isinstance(detail.get("error"), dict):
        error = dict(detail["error"])
        error.setdefault("code", _GENERIC_CODES.get(status_code, f"HTTP_{status_code}"))
        error.setdefault("message", "")
        error.setdefault("details", None)
        return {"detail": detail, "error": error}
    message = detail if isinstance(detail, str) else json.dumps(detail, default=str)
    return {
        "detail": detail,
        "error": {"code": _GENERIC_CODES.get(status_code, f"HTTP_{status_code}"), "message": message, "details": None},
    }
