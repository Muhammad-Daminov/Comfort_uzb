"""Cyrillic/Latin search normalization — ADR-8. One shared implementation,
called both when writing `products.search_text` (product create/update,
Phase-06) and when parsing a search query (this phase's `GET
/catalog/search`) — a second, divergent implementation would silently break
matching, which is exactly what ADR-8 warns against.
"""
from __future__ import annotations

import re

_CYRILLIC_TO_LATIN = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
    "ж": "j", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "x", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sh",
    "ъ": "", "ы": "i", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    "ў": "o", "қ": "q", "ғ": "g", "ҳ": "h",
}

_APOSTROPHE_VARIANTS = re.compile(r"[ʻʼ'`’]")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize(text: str) -> str:
    lowered = text.lower()
    transliterated = "".join(_CYRILLIC_TO_LATIN.get(ch, ch) for ch in lowered)
    no_apostrophes = _APOSTROPHE_VARIANTS.sub("", transliterated)
    collapsed = _NON_ALNUM.sub(" ", no_apostrophes).strip()
    return re.sub(r"\s+", " ", collapsed)
