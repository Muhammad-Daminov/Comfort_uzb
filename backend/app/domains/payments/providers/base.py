"""§8 of the v2 rebuild brief: the domain must not be tightly coupled to
Hamyon (or any single provider). This is the narrow interface both the
existing manual-receipt flow and a future Hamyon integration implement —
narrow because only operations actually confirmed/used today are here;
adding a method later (e.g. a real `refund()` body) does not require
touching this file's shape, just the concrete provider.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class ProviderNotConfigured(Exception):
    """Raised by a provider method that has no verified implementation yet.
    Never caught-and-faked — it must surface as an actionable error."""


@dataclass(frozen=True)
class PaymentIntent:
    provider_payment_id: str
    status: str  # provider-native status string, not one of our order/payment states
    redirect_url: str | None = None


@dataclass(frozen=True)
class CallbackResult:
    provider_payment_id: str
    order_id: int
    amount: int
    verified: bool
    raw: dict


class PaymentProvider(Protocol):
    name: str

    async def create_payment(self, *, order_id: int, amount: int, currency: str) -> PaymentIntent:
        ...

    async def get_status(self, *, provider_payment_id: str) -> str:
        ...

    async def verify_callback(self, *, headers: dict[str, str], raw_body: bytes) -> CallbackResult:
        ...

    async def refund(self, *, provider_payment_id: str, amount: int) -> None:
        ...
