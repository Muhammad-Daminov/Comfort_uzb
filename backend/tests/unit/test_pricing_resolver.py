"""Unit tests for §7.2 discount specificity/priority resolution — no DB
required, pure function (app/domains/pricing/resolver.py)."""
from app.domains.pricing.resolver import DiscountCandidate, resolve_price


def test_no_discounts_returns_base_price():
    result = resolve_price(100_000, [])
    assert result.unit_price == 100_000
    assert result.discount_amount == 0
    assert result.applied_discount_id is None


def test_variant_beats_product_brand_and_all():
    candidates = [
        DiscountCandidate(id=1, kind="PERCENT", value=50, priority=0, target_type="ALL"),
        DiscountCandidate(id=2, kind="PERCENT", value=10, priority=0, target_type="BRAND"),
        DiscountCandidate(id=3, kind="PERCENT", value=5, priority=0, target_type="PRODUCT"),
        DiscountCandidate(id=4, kind="PERCENT", value=1, priority=0, target_type="VARIANT"),
    ]
    result = resolve_price(100_000, candidates)
    assert result.applied_discount_id == 4
    assert result.unit_price == 99_000


def test_higher_priority_wins_within_same_specificity():
    candidates = [
        DiscountCandidate(id=1, kind="PERCENT", value=10, priority=1, target_type="BRAND"),
        DiscountCandidate(id=2, kind="PERCENT", value=20, priority=5, target_type="BRAND"),
    ]
    result = resolve_price(100_000, candidates)
    assert result.applied_discount_id == 2
    assert result.unit_price == 80_000


def test_tie_picks_cheaper_for_user():
    candidates = [
        DiscountCandidate(id=1, kind="PERCENT", value=10, priority=1, target_type="BRAND"),
        DiscountCandidate(id=2, kind="FIXED", value=50_000, priority=1, target_type="BRAND"),
    ]
    result = resolve_price(100_000, candidates)
    # 10% of 100_000 = 10_000 off (-> 90_000); FIXED 50_000 off (-> 50_000).
    # Cheaper for the user wins, and stacking never happens.
    assert result.applied_discount_id == 2
    assert result.unit_price == 50_000


def test_no_stacking_only_one_discount_ever_applies():
    candidates = [
        DiscountCandidate(id=1, kind="PERCENT", value=10, priority=0, target_type="ALL"),
        DiscountCandidate(id=2, kind="PERCENT", value=10, priority=0, target_type="ALL"),
    ]
    result = resolve_price(100_000, candidates)
    assert result.unit_price == 90_000  # not 80_000 — stacking never happens
    assert result.applied_discount_id in (1, 2)


def test_result_never_negative_even_for_misconfigured_fixed_discount():
    candidates = [DiscountCandidate(id=1, kind="FIXED", value=999_999, priority=0, target_type="ALL")]
    result = resolve_price(100_000, candidates)
    assert result.unit_price == 0
    assert result.discount_amount == 100_000


def test_percent_discount_capped_at_100_is_not_enforced_here_but_never_goes_negative():
    # The <=100 CHECK constraint lives at the DB layer (migration
    # 0005_pricing); this function must still be safe even against a
    # value it should never actually receive from valid data.
    candidates = [DiscountCandidate(id=1, kind="PERCENT", value=100, priority=0, target_type="ALL")]
    result = resolve_price(50_000, candidates)
    assert result.unit_price == 0
