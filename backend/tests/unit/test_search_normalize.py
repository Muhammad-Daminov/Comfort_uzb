"""ADR-8's own example set: Nexia/Neksiya/Нексия/nexiya must all be
findable under the same normalization + alias mechanism. This test proves
the normalization half; the alias half (neksiya/нексия -> nexia) is a data
concern, not a code concern, and is exercised at the DB layer once
`search_aliases` has real rows (Phase-06 content task per ADR-8's own
"Consequences")."""
from app.domains.catalog.search_normalize import normalize


def test_cyrillic_transliterates_to_latin():
    assert normalize("Нексия") == "neksiya"


def test_latin_variants_normalize_consistently():
    assert normalize("Nexia") == "nexia"
    assert normalize("nexiya") == "nexiya"
    assert normalize("Neksiya") == "neksiya"


def test_apostrophe_variants_collapse():
    assert normalize("gʻildirak") == normalize("g'ildirak") == normalize("g`ildirak")


def test_whitespace_and_punctuation_collapse():
    assert normalize("  Chevrolet   Nexia! ") == "chevrolet nexia"
