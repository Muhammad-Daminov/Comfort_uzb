"""§P4.1 Part 8: the primary-provider-fails -> deterministic-fallback
wrapper. No real API key needed — the "primary" here is a fake that raises
on demand."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.ai.providers.base import ProviderNotConfigured, StructuredCommandResult
from app.ai.providers.fallback import FallbackAIProvider
from app.ai.providers.stub import StubAIProvider

pytestmark = pytest.mark.asyncio


class _FakePrimary:
    name = "fake-primary"

    def __init__(self, *, result=None, error: Exception | None = None) -> None:
        self._result = result
        self._error = error
        self.generate_structured_command = AsyncMock(side_effect=self._sc)
        self.generate_response = AsyncMock(side_effect=self._gr)

    async def _sc(self, *, text: str | None = None, audio=None, image_refs=None):
        if self._error is not None:
            raise self._error
        return self._result

    async def _gr(self, *, prompt: str, context: dict):
        if self._error is not None:
            raise self._error
        return "primary response"


async def test_primary_success_never_calls_fallback():
    primary_result = StructuredCommandResult(command_type="GET_STOCK", payload={"product_query": "Malibu 2"})
    primary = _FakePrimary(result=primary_result)
    fallback = StubAIProvider()

    provider = FallbackAIProvider(primary=primary, fallback=fallback)
    result = await provider.generate_structured_command(text="Malibu 2 qancha qoldi?")

    assert result is primary_result
    primary.generate_structured_command.assert_awaited_once()


async def test_primary_failure_falls_back_to_deterministic_parser():
    primary = _FakePrimary(error=ProviderNotConfigured("Anthropic API call failed: TimeoutException"))
    provider = FallbackAIProvider(primary=primary, fallback=StubAIProvider())

    result = await provider.generate_structured_command(text="Malibu 2 + 1")

    # The deterministic stub parser still understands this exact shape —
    # proves the fallback actually ran, not just "didn't crash".
    assert result.command_type == "INCREASE_STOCK"
    assert result.payload == {"product_query": "Malibu 2", "delta": 1}


async def test_primary_failure_on_unparseable_text_falls_back_to_none_not_a_crash():
    primary = _FakePrimary(error=ProviderNotConfigured("boom"))
    provider = FallbackAIProvider(primary=primary, fallback=StubAIProvider())

    result = await provider.generate_structured_command(text="tushunarsiz gap")

    assert result.command_type is None  # never a partially-parsed/guessed command


async def test_provider_name_reflects_primary_not_fallback():
    primary = _FakePrimary(result=StructuredCommandResult(command_type=None))
    provider = FallbackAIProvider(primary=primary, fallback=StubAIProvider())
    assert provider.name == "fake-primary"


async def test_generate_response_falls_back_on_primary_failure():
    primary = _FakePrimary(error=ProviderNotConfigured("boom"))
    provider = FallbackAIProvider(primary=primary, fallback=StubAIProvider())

    # StubAIProvider.generate_response always raises ProviderNotConfigured
    # too (no honest offline free-form-chat equivalent) — the fallback
    # attempt must still happen, and the final error must still be the
    # actionable "not configured" kind, not an unrelated crash.
    with pytest.raises(ProviderNotConfigured):
        await provider.generate_response(prompt="hi", context={})
