"""Deterministic, no-network provider. Active whenever AI_PROVIDER/
STT_PROVIDER are unset (the default). Real, testable regex/heuristic logic
— not a mock of an AI response — covering every example command the v2
rebuild brief gives verbatim. Anything it cannot confidently parse returns
`command_type=None`, which the caller must present to the admin as
"could not understand this request", never guess at.

No FX conversion: a price written as "500 dollar" is parsed as the raw
number 500 and stored as-is (so'm is the only currency the system has,
ADR-003) — there is no exchange rate anywhere in this codebase to convert
with, so inventing one would violate the "do not invent" rule. The preview
text shown before confirmation echoes the parsed number so the admin can
catch and correct this with [Tahrirlash] if they meant an actual
dollar-to-so'm conversion.

Voice transcription has no honest offline equivalent, so
`StubSpeechToTextProvider` always raises `ProviderNotConfigured` — this is
the "clearly mark live-provider testing as pending credentials" case from
the brief, not something to fake.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from app.ai.providers.base import ProviderNotConfigured, StructuredCommandResult

# Asia/Tashkent is a fixed UTC+5 offset with no DST — not a shortcut, that
# is simply what the zone is, so a fixed offset is correct, not a hack.
_TASHKENT = timezone(timedelta(hours=5))

_STOCK_DELTA = re.compile(r"^(?P<name>.+?)\s*([+−-])\s*(?P<qty>\d+)\s*$")
_ARCHIVE = re.compile(r"^(?P<name>.+?)\s*(?:ni|ning)?\s*arxivla", re.IGNORECASE)
# §P2-2 UPDATE_PRODUCT patterns — "qil" at the end matches the brief's own
# five examples verbatim ("... nomini ... qil", "... rangini ... qil", ...).
_UPDATE_NAME = re.compile(r"^(?P<name>.+?)\s+nomini\s+(?P<value>.+?)\s+qil", re.IGNORECASE)
_UPDATE_DESCRIPTION = re.compile(r"^(?P<name>.+?)\s+tavsifini\s+(?P<value>.+?)\s+qil", re.IGNORECASE)
_UPDATE_COLOR = re.compile(r"^(?P<name>.+?)\s+rangini\s+(?P<value>.+?)\s+qil", re.IGNORECASE)
_UPDATE_MATERIAL = re.compile(r"^(?P<name>.+?)\s+materialini\s+(?P<value>.+?)\s+qil", re.IGNORECASE)
_UPDATE_TYPE = re.compile(r"^(?P<name>.+?)\s+turini\s+(?P<value>.+?)\s+qil", re.IGNORECASE)
_PRICE_CHANGE = re.compile(
    r"^(?P<name>.+?)\s+narxini\s+(?P<price>[\d\s]+)\s*(?:dollar|\$|so'?m|sum)?\s*(?:ga|gacha)?\s*o'?zgart",
    re.IGNORECASE,
)
_GET_STOCK = re.compile(r"^(?P<name>.+?)\s*(?:dan)?\s*nechta\s*qold", re.IGNORECASE)
_GET_COST_PRICE = re.compile(r"^(?P<name>.+?)\s*(?:ning)?\s*tannarx", re.IGNORECASE)
_GET_SALES_STATS = re.compile(r"nechta\s*buyurtma|qaysi\s*mahsulotdan|nechta\s*sotil", re.IGNORECASE)
_GET_REVENUE = re.compile(r"tushum", re.IGNORECASE)
_GET_PROFIT = re.compile(r"foyda", re.IGNORECASE)
_PRICE_TOKEN = re.compile(r"(\d[\d\s]*)\s*(?:dollar|\$|so'?m|sum)", re.IGNORECASE)
_QTY_TOKEN = re.compile(r"(\d+)\s*dona", re.IGNORECASE)


def _today_range() -> tuple[str, str]:
    now = datetime.now(_TASHKENT)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return start.date().isoformat(), end.date().isoformat()


def _strip_number(text: str) -> int:
    return int(re.sub(r"\s", "", text))


def _normalize_product_type(text: str) -> str | None:
    lowered = text.lower()
    if "chexol" in lowered:
        return "SIDENA_COVER"
    if "sidena" in lowered:
        return "SIDENA"
    return None  # unrecognized — left unset, not guessed (commands.py then reports "no field to change")


class StubAIProvider:
    name = "stub"

    async def generate_structured_command(
        self, *, text: str | None = None, audio=None, image_refs: list[str] | None = None
    ) -> StructuredCommandResult:
        # §P5.1: this is a regex-over-text parser — it has no honest way
        # to interpret raw audio, so `audio` is accepted only for
        # AIProvider protocol/fallback compatibility. An audio-only call
        # (no text) falls through exactly like any other text this parser
        # cannot match: `command_type=None`, never a guess. This matters
        # specifically because StubAIProvider is FallbackAIProvider's
        # fallback target for both AnthropicAIProvider and
        # GeminiAIProvider — a Gemini audio-call failure must not silently
        # "succeed" with a fabricated command.
        raw = (text or "").strip()

        match = _UPDATE_NAME.match(raw)
        if match:
            return StructuredCommandResult(
                command_type="UPDATE_PRODUCT",
                payload={"product_query": match.group("name").strip(), "name": match.group("value").strip()},
                confidence=0.8, raw_text=raw,
            )

        match = _UPDATE_DESCRIPTION.match(raw)
        if match:
            return StructuredCommandResult(
                command_type="UPDATE_PRODUCT",
                payload={"product_query": match.group("name").strip(), "description": match.group("value").strip()},
                confidence=0.8, raw_text=raw,
            )

        match = _UPDATE_MATERIAL.match(raw)
        if match:
            return StructuredCommandResult(
                command_type="UPDATE_PRODUCT",
                payload={"product_query": match.group("name").strip(), "material": match.group("value").strip()},
                confidence=0.8, raw_text=raw,
            )

        match = _UPDATE_TYPE.match(raw)
        if match:
            product_type = _normalize_product_type(match.group("value"))
            payload = {"product_query": match.group("name").strip()}
            if product_type is not None:
                payload["product_type"] = product_type
            return StructuredCommandResult(command_type="UPDATE_PRODUCT", payload=payload, confidence=0.75, raw_text=raw)

        match = _UPDATE_COLOR.match(raw)
        if match:
            return StructuredCommandResult(
                command_type="UPDATE_PRODUCT",
                payload={"product_query": match.group("name").strip(), "color_query": match.group("value").strip()},
                confidence=0.75, raw_text=raw,
            )

        match = _ARCHIVE.match(raw)
        if match:
            return StructuredCommandResult(
                command_type="ARCHIVE_PRODUCT", payload={"product_query": match.group("name").strip()},
                confidence=0.85, raw_text=raw,
            )

        match = _PRICE_CHANGE.match(raw)
        if match:
            return StructuredCommandResult(
                command_type="UPDATE_PRICE",
                payload={"product_query": match.group("name").strip(), "price": _strip_number(match.group("price"))},
                confidence=0.85, raw_text=raw,
            )

        match = _GET_COST_PRICE.match(raw)
        if match:
            return StructuredCommandResult(
                command_type="GET_COST_PRICE", payload={"product_query": match.group("name").strip()},
                confidence=0.85, raw_text=raw,
            )

        match = _GET_STOCK.match(raw)
        if match:
            return StructuredCommandResult(
                command_type="GET_STOCK", payload={"product_query": match.group("name").strip()},
                confidence=0.85, raw_text=raw,
            )

        if _GET_SALES_STATS.search(raw):
            date_from, date_to = _today_range()
            return StructuredCommandResult(
                command_type="GET_SALES_STATISTICS", payload={"date_from": date_from, "date_to": date_to},
                confidence=0.8, raw_text=raw,
            )

        if _GET_REVENUE.search(raw):
            date_from, date_to = _today_range()
            return StructuredCommandResult(
                command_type="GET_REVENUE", payload={"date_from": date_from, "date_to": date_to},
                confidence=0.8, raw_text=raw,
            )

        if _GET_PROFIT.search(raw):
            date_from, date_to = _today_range()
            return StructuredCommandResult(
                command_type="GET_PROFIT", payload={"date_from": date_from, "date_to": date_to},
                confidence=0.8, raw_text=raw,
            )

        match = _STOCK_DELTA.match(raw)
        if match:
            qty = int(match.group("qty"))
            sign = match.group(2)
            command_type = "INCREASE_STOCK" if sign == "+" else "DECREASE_STOCK"
            delta = qty if sign == "+" else -qty
            return StructuredCommandResult(
                command_type=command_type,
                payload={"product_query": match.group("name").strip(), "delta": delta},
                confidence=0.9, raw_text=raw,
            )

        # CREATE_PRODUCT heuristic (§15 of the brief, e.g. "malibu 2, 2 ta
        # old sidenasi, qora, koja, 500 dollar, 1 dona"): comma-separated
        # free text naming a price and a quantity is the only shape this
        # deterministic parser treats as a product-creation request — it
        # does not attempt full NLP, just this one bounded, testable
        # pattern the brief itself gives as the canonical example.
        price_match = _PRICE_TOKEN.search(raw)
        qty_match = _QTY_TOKEN.search(raw)
        if "," in raw and price_match and qty_match:
            segments = [s.strip() for s in raw.split(",") if s.strip()]
            name = segments[0] if segments else raw
            price_segment = price_match.group(0)
            qty_segment = qty_match.group(0)
            # Every segment after the name that isn't the price/qty token
            # itself becomes the description — simple, honest assembly.
            description_parts = [
                s for s in segments[1:]
                if price_segment.lower() not in s.lower() and qty_segment.lower() not in s.lower()
            ]
            return StructuredCommandResult(
                command_type="CREATE_PRODUCT",
                payload={
                    "name": name,
                    "description": ", ".join(description_parts) or None,
                    "price": _strip_number(price_match.group(1)),
                    "initial_stock": int(qty_match.group(1)),
                    # brand_id is NOT guessed — commands.py requires it;
                    # the resolver (app/ai/resolver.py) turns a
                    # "brand_query" into a real id if the admin's phrasing
                    # includes one, otherwise CREATE_PRODUCT's draft
                    # creation fails validation with a clear "brand_id
                    # required" error rather than guessing which brand.
                },
                confidence=0.6, raw_text=raw,
            )

        return StructuredCommandResult(command_type=None, payload={}, confidence=0.0, raw_text=raw)

    async def generate_response(self, *, prompt: str, context: dict) -> str:
        raise ProviderNotConfigured(
            "no AI_PROVIDER configured — free-form chat replies are unavailable; "
            "structured commands (e.g. 'Malibu 2 + 1') still work via the stub parser"
        )


class StubSpeechToTextProvider:
    name = "stub"

    async def transcribe(self, *, audio_bytes: bytes, mime_type: str) -> str:
        raise ProviderNotConfigured(
            "no STT_PROVIDER configured — voice messages cannot be transcribed without a real "
            "speech-to-text provider (set STT_PROVIDER=openai_whisper and OPENAI_API_KEY)"
        )
