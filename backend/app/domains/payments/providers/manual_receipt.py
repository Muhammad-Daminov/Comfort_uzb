"""Wraps the existing, fully working manual receipt-review flow
(`payments/service.py::submit_payment/upload_receipt/review_payment`) behind
the `PaymentProvider` shape. This is the active provider today — nothing
about its behavior changes; this class exists so the router/service layer
can be provider-agnostic without rewriting the working flow.
"""
from __future__ import annotations

from app.domains.payments.providers.base import CallbackResult, PaymentIntent, ProviderNotConfigured

name = "manual_receipt"


class ManualReceiptPaymentProvider:
    name = "manual_receipt"

    async def create_payment(self, *, order_id: int, amount: int, currency: str) -> PaymentIntent:
        # No-op by design: the manual flow's "payment creation" is
        # `payments.service.submit_payment`, called directly by the router —
        # there is no external provider call to make here.
        raise ProviderNotConfigured(
            "manual_receipt provider does not create remote payments; call payments.service.submit_payment directly"
        )

    async def get_status(self, *, provider_payment_id: str) -> str:
        raise ProviderNotConfigured("manual_receipt provider has no remote status; read payments.status from the DB")

    async def verify_callback(self, *, headers: dict[str, str], raw_body: bytes) -> CallbackResult:
        raise ProviderNotConfigured("manual_receipt provider has no callback; review happens via the admin endpoint")

    async def refund(self, *, provider_payment_id: str, amount: int) -> None:
        raise ProviderNotConfigured(
            "manual_receipt provider has no automated refund; use the refunds domain's manual record/complete flow"
        )
