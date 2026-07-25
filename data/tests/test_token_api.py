"""Token API source: endpoint discovery, price extraction, degradation."""

from __future__ import annotations

import httpx
import pytest

from curator_data.config import Settings
from curator_data.sources.token_api import TokenApiSource

SETTINGS = Settings(token_api_key="jwt-test", token_api_url="https://token-api.example")


def _source(handler) -> TokenApiSource:
    return TokenApiSource(
        SETTINGS, client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )


async def test_price_becomes_a_usd_fact_with_provenance():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"price_usd": 3218.44}]})

    facts = await _source(handler).fetch(["WETH"])

    assert len(facts) == 1
    fact = facts[0]
    assert fact.kind == "price"
    assert fact.unit == "usd"
    assert fact.value == 3218.44
    assert fact.source == "token_api"
    assert fact.subject.token == "WETH"


async def test_endpoint_discovery_falls_through_404s_and_then_sticks():
    """The Token API moved paths during beta; a 404 must not kill the source."""
    attempted: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempted.append(str(request.url))
        if "ohlc" not in request.url.path:
            return httpx.Response(404, text="not found")
        return httpx.Response(200, json={"data": [{"close": 3218.44}]})

    source = _source(handler)
    facts = await source.fetch(["WETH"])
    assert facts[0].value == 3218.44
    first_pass = len(attempted)
    assert first_pass > 1, "expected fallthrough past the 404s"

    # Second call reuses the discovered path rather than re-walking the list.
    attempted.clear()
    await source.fetch(["WETH"])
    assert len(attempted) == 1


async def test_ohlc_close_is_read_when_no_flat_price_field_exists():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"data": [{"open": 3200.0, "high": 3250.0, "low": 3180.0, "close": 3218.44}]}
        )

    facts = await _source(handler).fetch(["WETH"])
    assert facts[0].value == 3218.44


async def test_unknown_symbol_is_noted_with_the_fix_rather_than_guessed():
    """Guessing a contract address on a system that trades is unacceptable."""

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("must not call the API for an unknown symbol")

    source = _source(handler)
    facts = await source.fetch(["NOTAREALTOKEN"])

    assert facts == []
    note = source.drain_notes()[0]
    assert "NOTAREALTOKEN" in note
    assert "tokens.py" in note  # names where to fix it


async def test_rejected_credential_raises_for_the_whole_source():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="unauthorized")

    with pytest.raises(RuntimeError, match="401"):
        await _source(handler).fetch(["WETH"])


async def test_missing_credential_raises_before_any_request():
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("must not call the API without a credential")

    source = TokenApiSource(
        Settings(), client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(RuntimeError, match="TOKEN_API_KEY"):
        await source.fetch(["WETH"])


async def test_one_unpriceable_token_does_not_lose_the_other():
    def handler(request: httpx.Request) -> httpx.Response:
        # The contract address travels as a query parameter, so match the whole
        # URL rather than just the path.
        if "4200" in str(request.url):  # WETH
            return httpx.Response(503, text="unavailable")
        return httpx.Response(200, json={"price_usd": 1.0})

    source = _source(handler)
    facts = await source.fetch(["WETH", "USDC"])

    assert [f.subject.token for f in facts] == ["USDC"]
    assert any("WETH" in n for n in source.drain_notes())


async def test_nonsense_price_is_rejected_rather_than_reported():
    """A zero price would value the vault's holdings at nothing."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"price_usd": 0})

    source = _source(handler)
    assert await source.fetch(["WETH"]) == []
    assert source.drain_notes()
