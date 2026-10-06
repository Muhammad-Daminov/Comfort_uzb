"""§5.5: order numbers are short random codes (`CU-7F3K92`), never a
sequential/guessable number — that would leak order volume to anyone who
sees one order number."""
from __future__ import annotations

import secrets

_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"  # excludes 0/O/1/I to avoid ambiguity


def generate_order_number() -> str:
    suffix = "".join(secrets.choice(_ALPHABET) for _ in range(6))
    return f"CU-{suffix}"
