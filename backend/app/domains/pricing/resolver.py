"""Discount specificity/priority resolution — §7.2. Pure function, no DB
access, so it's directly unit-testable (REQ-TST-002-style rationale) and
reused verbatim by `backend-commerce`'s checkout re-validation (§7.3) — the
current-price computation must never be duplicated between "show the price"
and "charge the price" paths.
"""
from __future__ import annotations

from dataclasses import dataclass

_SPECIFICITY = {"VARIANT": 4, "PRODUCT": 3, "BRAND": 2, "CAR_MODEL": 1, "ALL": 0}


@dataclass(frozen=True)
class DiscountCandidate:
    id: int
    kind: str  # 'PERCENT' | 'FIXED'
    value: int
    priority: int
    target_type: str  # 'VARIANT' | 'PRODUCT' | 'BRAND' | 'CAR_MODEL' | 'ALL'


@dataclass(frozen=True)
class ResolvedPrice:
    unit_price: int
    discount_amount: int
    applied_discount_id: int | None


def _apply(base_price: int, candidate: DiscountCandidate) -> tuple[int, int]:
    if candidate.kind == "PERCENT":
        discount_amount = (base_price * candidate.value) // 100
    else:
        discount_amount = candidate.value
    # §7.2 "Natija manfiy bo'lmaydi" (result is never negative) — clamp the
    # discount itself so unit_price can never go below zero even for a
    # mis-configured FIXED discount larger than the price.
    discount_amount = min(discount_amount, base_price)
    return max(base_price - discount_amount, 0), discount_amount


def resolve_price(base_price: int, candidates: list[DiscountCandidate]) -> ResolvedPrice:
    if base_price < 0:
        raise ValueError("base_price must not be negative")
    if not candidates:
        return ResolvedPrice(unit_price=base_price, discount_amount=0, applied_discount_id=None)

    # §7.2 "Aniqlik": VARIANT > PRODUCT > BRAND > CAR_MODEL > ALL — only the
    # most specific level present is considered at all.
    max_specificity = max(_SPECIFICITY[c.target_type] for c in candidates)
    most_specific = [c for c in candidates if _SPECIFICITY[c.target_type] == max_specificity]

    # "Bir darajada bir nechta bo'lsa - priority kattasi" (within one level,
    # highest priority wins).
    max_priority = max(c.priority for c in most_specific)
    top_priority = [c for c in most_specific if c.priority == max_priority]

    # "Teng bo'lsa - foydalanuvchiga foydali (arzon)" (tie -> whichever is
    # cheaper for the user). "Stacking yo'q - faqat bittasi qo'llanadi" (no
    # stacking — exactly one discount applies, never a combination).
    best_candidate = min(top_priority, key=lambda c: _apply(base_price, c)[0])
    unit_price, discount_amount = _apply(base_price, best_candidate)
    return ResolvedPrice(
        unit_price=unit_price, discount_amount=discount_amount, applied_discount_id=best_candidate.id
    )
