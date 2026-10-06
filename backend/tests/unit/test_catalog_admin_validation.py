"""Unit tests for Phase 06 admin-catalog validation logic that doesn't
need a DB — status literal validation, image-count limit constant."""
from app.domains.catalog.service import (
    MAX_IMAGES_PER_PRODUCT,
    PRODUCT_STATUSES,
    VARIANT_STATUSES,
)


def test_product_statuses_match_the_db_check_constraint():
    # migration 0003_catalog's CHECK (status IN (...)) — kept in sync here
    # deliberately, not derived at runtime, so a mismatch is a visible diff.
    assert PRODUCT_STATUSES == {"DRAFT", "ACTIVE", "ARCHIVED"}


def test_variant_statuses_match_the_db_check_constraint():
    assert VARIANT_STATUSES == {"ACTIVE", "ARCHIVED"}


def test_max_images_matches_tz_1_to_5_rule():
    assert MAX_IMAGES_PER_PRODUCT == 5
