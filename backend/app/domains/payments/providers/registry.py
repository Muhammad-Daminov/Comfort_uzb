from __future__ import annotations

from app.config import Settings
from app.domains.payments.providers.base import PaymentProvider
from app.domains.payments.providers.hamyon import HamyonPaymentProvider
from app.domains.payments.providers.manual_receipt import ManualReceiptPaymentProvider


def get_payment_provider(settings: Settings) -> PaymentProvider:
    if settings.payment_provider == "hamyon":
        return HamyonPaymentProvider(settings)
    if settings.payment_provider == "manual_receipt":
        return ManualReceiptPaymentProvider()
    raise ValueError(f"unknown PAYMENT_PROVIDER: {settings.payment_provider!r}")
