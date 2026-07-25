"""Token API source: pool discovery, orientation-proof pricing, degradation.

The orientation tests are the important ones. `/evm/swaps` exposes a `price`
field that **flips with the direction of the swap** — verified live on the
WETH/USDC pool, consecutive trades returned `1858.0228` and `0.0005`. Reading
it off the latest swap is a coin flip between the right number and one wrong by
a factor of ~3.4 million, and nothing in the response says which you got.

Every fixture below uses real values observed on 2026-07-25.
"""

from __future__ import annotations

import httpx
import pytest

from curator_data.config import Settings
from curator_data.sources.token_api import MAX_PAGE, TokenApiSource

SETTINGS = Settings(token_api_key="jwt-test", token_api_url="https://token-api.example")

WETH = "0x4200000000000000000000000000000000000006"
USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
POOL = "0xb4cb800910b228ed3d0834cf79d697127bbb00e5"


def _token(address: str, symbol: str, decimals: int) -> dict:
    return {"address": address, "symbol": symbol, "decimals": decimals}


def _pool(pool: str = POOL, transactions: int = 34_002_146, other: str = USDC) -> dict:
    return {
        "pool": pool,
        "protocol": "uniswap_v3",
        "input_token": _token(WETH, "WETH", 18),
        "output_token": _token(other, "USDC", 6),
        "fee": 100,
        "transactions": transactions,
        "network": "base",
    }


def _swap_weth_to_usdc(weth: float, usdc: float) -> dict:
    return {
        "pool": POOL,
        "input_token": _token(WETH, "WETH", 18),
        "output_token": _token(USDC, "USDC", 6),
        "input_value": weth,
        "output_value": usdc,
        "price": usdc / weth,  # the API's own field, in this direction
    }


def _swap_usdc_to_weth(usdc: float, weth: float) -> dict:
    return {
        "pool": POOL,
        "input_token": _token(USDC, "USDC", 6),
        "output_token": _token(WETH, "WETH", 18),
        "input_value": usdc,
        "output_value": weth,
        "price": weth / usdc,  # SAME pool, inverted field
    }


def _router(pools: list[dict] | None = None, swaps: list[dict] | None = None):
    """Route /evm/pools and /evm/swaps the way the live API does."""

    def handler(request: httpx.Request) -> httpx.Response:
        if "/evm/pools" in request.url.path:
            return httpx.Response(200, json={"data": pools if pools is not None else [_pool()]})
        if "/evm/swaps" in request.url.path:
            return httpx.Response(200, json={"data": swaps or []})
        return httpx.Response(404, json={"status": 404, "code": "route_not_found"})

    return handler


def _source(handler) -> TokenApiSource:
    return TokenApiSource(
        SETTINGS, client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )


# ── the orientation trap ──────────────────────────────────────────────────


async def test_price_is_correct_when_the_latest_swap_is_inverted():
    """A USDC->WETH swap must not yield a price of 0.0005."""
    swaps = [_swap_usdc_to_weth(48.428320, 0.026060)]  # live values
    facts = await _source(_router(swaps=swaps)).fetch(["WETH"])

    assert len(facts) == 1
    assert 1800 < facts[0].value < 1900, "read the API's flipped price field"


async def test_price_is_stable_across_mixed_swap_directions():
    """Both directions of the same pool must agree to within noise."""
    swaps = [
        _swap_weth_to_usdc(0.016074, 29.865872),
        _swap_usdc_to_weth(48.428320, 0.026060),
        _swap_weth_to_usdc(0.004956, 9.206119),
        _swap_usdc_to_weth(63.399796, 0.034120),
    ]
    facts = await _source(_router(swaps=swaps)).fetch(["WETH"])
    assert 1855 < facts[0].value < 1860


async def test_a_single_odd_trade_does_not_move_the_price():
    """Median, not mean: one fat-fingered swap should not set the price."""
    swaps = [_swap_weth_to_usdc(0.01, 18.57) for _ in range(5)]
    swaps.append(_swap_weth_to_usdc(0.01, 1857.0))  # 100x outlier
    facts = await _source(_router(swaps=swaps)).fetch(["WETH"])
    assert 1850 < facts[0].value < 1865


async def test_the_fact_carries_provenance_and_the_right_unit():
    facts = await _source(_router(swaps=[_swap_weth_to_usdc(0.01, 18.58)])).fetch(["WETH"])
    fact = facts[0]
    assert fact.kind == "price"
    assert fact.unit == "usd"
    assert fact.source == "token_api"
    assert fact.subject.token == "WETH"


# ── pinned pools ──────────────────────────────────────────────────────────


async def test_a_pinned_pool_skips_discovery_entirely():
    """Discovery costs a round trip against an 8-10s API that also 500s."""
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(200, json={"data": [_swap_weth_to_usdc(0.01, 18.58)]})

    facts = await _source(handler).fetch(["WETH"])  # WETH is pinned
    assert len(facts) == 1
    assert "/evm/pools" not in paths, "pinned pool should not trigger discovery"


@pytest.fixture
def _unpinned(monkeypatch: pytest.MonkeyPatch):
    """Force the discovery path, which pinning otherwise short-circuits."""
    monkeypatch.setattr("curator_data.sources.token_api.pool_for", lambda *a, **k: None)


# ── pool discovery (the fallback for anything not pinned) ─────────────────


async def test_the_busiest_usd_paired_pool_is_chosen(_unpinned):
    """`transactions` is the closest thing to depth the API exposes."""
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if "/evm/pools" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "data": [
                        _pool(pool="0xquiet", transactions=10),
                        _pool(pool="0xbusy", transactions=34_000_000),
                    ]
                },
            )
        return httpx.Response(200, json={"data": [_swap_weth_to_usdc(0.01, 18.58)]})

    await _source(handler).fetch(["WETH"])
    assert any("pool=0xbusy" in url for url in requested)


async def test_pool_discovery_is_cached_across_calls(_unpinned):
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if "/evm/pools" in request.url.path:
            return httpx.Response(200, json={"data": [_pool()]})
        return httpx.Response(200, json={"data": [_swap_weth_to_usdc(0.01, 18.58)]})

    source = _source(handler)
    await source.fetch(["WETH"])
    await source.fetch(["WETH"])
    assert calls.count("/evm/pools") == 1


async def test_a_pool_with_no_usd_leg_is_rejected(_unpinned):
    """Pricing WETH against a random token is not a USD price."""
    degen = "0x4ed4e862860bed51a9570b96d89af5e1b0efefed"
    source = _source(_router(pools=[_pool(other=degen)]))

    assert await source.fetch(["WETH"]) == []
    assert "no pool pairs it with a USD quote token" in source.drain_notes()[0]


async def test_page_size_never_exceeds_the_plan_ceiling():
    """limit=20 returns 403 on the free plan. Verified live."""
    urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        if "/evm/pools" in request.url.path:
            return httpx.Response(200, json={"data": [_pool()]})
        return httpx.Response(200, json={"data": [_swap_weth_to_usdc(0.01, 18.58)]})

    await _source(handler).fetch(["WETH"])
    assert urls, "expected requests"
    for url in urls:
        limit = int(url.split("limit=")[1].split("&")[0])
        assert limit <= MAX_PAGE, url


# ── degradation ───────────────────────────────────────────────────────────


async def test_a_plan_limit_403_does_not_kill_the_whole_source():
    """A page-size complaint is not a rejected credential."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={"status": 403, "code": "forbidden",
                  "message": "Parameter 'limit' exceeds the maximum allowed"},
        )

    source = _source(handler)
    assert await source.fetch(["WETH"]) == []  # degraded, not raised
    notes = source.drain_notes()
    assert any("free plan refused" in n for n in notes)
    # A quota refusal clears by itself; saying so is what separates it from a
    # rejected credential, which never will.
    assert any("next tick" in n for n in notes)


async def test_a_genuine_credential_403_still_fails_the_source():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"status": 403, "code": "forbidden",
                                         "message": "invalid token"})

    with pytest.raises(RuntimeError, match="credential"):
        await _source(handler).fetch(["WETH"])


async def test_a_401_fails_the_source_naming_the_right_credential():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="unauthorized")

    with pytest.raises(RuntimeError, match="Graph Market JWT"):
        await _source(handler).fetch(["WETH"])


async def test_missing_credential_raises_before_any_request():
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("must not call the API without a credential")

    source = TokenApiSource(
        Settings(), client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(RuntimeError, match="TOKEN_API_KEY"):
        await source.fetch(["WETH"])


async def test_a_quote_token_is_not_priced_against_itself():
    """USDC's price here would be a peg assumption, not an observation.

    And the *channel* is the assertion, not just the message. This fired on 35
    of 36 journalled ticks, and while it lived in `drain_notes` it reached the
    curator prompt under "Data you could NOT read this tick. Reason about this
    explicitly" — telling the agent a working source was broken, every tick.
    A question the source was never able to answer is context, not a gap.
    """
    source = _source(_router(swaps=[_swap_weth_to_usdc(0.01, 18.58)]))
    facts = await source.fetch(["USDC"])

    assert facts == []
    assert source.drain_notes() == [], "a category mistake must not be reported as a failure"
    assert "quote token" in source.drain_remarks()[0]


async def test_unknown_symbol_is_noted_with_the_fix_rather_than_guessed():
    source = _source(_router())
    assert await source.fetch(["NOTAREALTOKEN"]) == []
    note = source.drain_notes()[0]
    assert "NOTAREALTOKEN" in note and "tokens.py" in note


async def test_no_swaps_returns_no_price_rather_than_a_wrong_one():
    source = _source(_router(swaps=[]))
    assert await source.fetch(["WETH"]) == []
    assert source.drain_notes()


async def test_a_zero_amount_swap_is_skipped_not_divided_by():
    swaps = [_swap_weth_to_usdc(0.01, 18.58)]
    swaps.insert(0, {
        "pool": POOL,
        "input_token": _token(WETH, "WETH", 18),
        "output_token": _token(USDC, "USDC", 6),
        "input_value": 0.0,
        "output_value": 0.0,
    })
    facts = await _source(_router(swaps=swaps)).fetch(["WETH"])
    assert len(facts) == 1
    assert 1850 < facts[0].value < 1865
