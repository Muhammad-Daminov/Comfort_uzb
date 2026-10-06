"""Hamyon payment provider — STRUCTURALLY PRESENT, NOT FUNCTIONALLY
IMPLEMENTED.

docs/13_V2_REBUILD_AUDIT.md §2 records the full capability matrix: every
Hamyon capability (auth, payment creation, webhook shape/signature, refund,
sandbox) is NOT DOCUMENTED — no public API docs were found, and none exist
in this repository. Per the v2 brief's explicit rule ("do not invent
undocumented endpoints, payloads, webhook fields, authentication mechanisms,
refund APIs... do not fake an integration"), every method here raises
`ProviderNotConfigured` instead of guessing a request/response shape.

This class exists so `PAYMENT_PROVIDER=hamyon` is a real, selectable
configuration point (validated at startup in `app/config.py`) the moment
real API documentation is available — implementing a method then means
filling in this file, not redesigning the provider boundary.
"""
from __future__ import annotations

from app.config import Settings
from app.domains.payments.providers.base import CallbackResult, PaymentIntent, ProviderNotConfigured

name = "hamyon"

_BLOCKER = (
    "Hamyon API is not documented (docs/13_V2_REBUILD_AUDIT.md §2) — "
    "this method cannot run without inventing an unverified request/response shape."
)


class HamyonPaymentProvider:
    name = "hamyon"

    def __init__(self, settings: Settings) -> None:
        # Reads config eagerly so a misconfigured deployment fails at
        # construction, not on the first real payment.
        self._api_url = settings.hamyon_api_url
        self._api_key = settings.hamyon_api_key
        self._merchant_id = settings.hamyon_merchant_id
        self._webhook_secret = settings.hamyon_webhook_secret

    async def create_payment(self, *, order_id: int, amount: int, currency: str) -> PaymentIntent:
        raise ProviderNotConfigured(_BLOCKER)

    async def get_status(self, *, provider_payment_id: str) -> str:
        raise ProviderNotConfigured(_BLOCKER)

    async def verify_callback(self, *, headers: dict[str, str], raw_body: bytes) -> CallbackResult:
        raise ProviderNotConfigured(_BLOCKER)

    async def refund(self, *, provider_payment_id: str, amount: int) -> None:
        raise ProviderNotConfigured(_BLOCKER)
