"""Messari source: query shape, normalisation, and partial failure.

Runs against `httpx.MockTransport` rather than the live gateway — no network,
no credential, deterministic. The live path is covered separately by
`curator-data verify-live`, which is a demo-path check rather than a unit test.

The assertion that matters most is the percent→fraction one. Messari reports
`InterestRate.rate` as `4.32` meaning 4.32%; the frozen schema requires
`0.0432`. Getting that wrong by 100x would not crash anything — it would just
make the agent believe every market yields 400% and rebalance into whichever
one it misread worst.
"""

from __future__ import annotations

import json

import httpx

from curator_data.config import Settings
from curator_data.graph.gateway import GatewayClient
from curator_data.sources.messari import MessariSource
from curator_data.sources.protocols import Protocol

SETTINGS = Settings(graph_api_key="test-key")

AAVE = Protocol(key="aave-v3", subgraph_id="sub-aave", family="lending", label="Aave V3")
MOONWELL = Protocol(key="moonwell", subgraph_id="sub-moon", family="lending", label="Moonwell")
UNI = Protocol(key="uniswap-v3", subgraph_id="sub-uni", family="dex-amm", label="Uniswap V3")


def _market(symbol: str, apy_percent: float, tvl: str, deposits: str, borrows: str) -> dict:
    return {
        "id": f"0xmarket-{symbol}",
        "name": f"{symbol} market",
        "isActive": True,
        "inputToken": {"id": "0xtoken", "symbol": symbol, "decimals": 6},
        "totalValueLockedUSD": tvl,
        "totalDepositBalanceUSD": deposits,
        "totalBorrowBalanceUSD": borrows,
        "rates": [
            {"rate": str(apy_percent + 2.0), "side": "BORROWER", "type": "VARIABLE"},
            {"rate": str(apy_percent), "side": "LENDER", "type": "VARIABLE"},
        ],
    }


def _gateway(handler) -> GatewayClient:
    return GatewayClient(SETTINGS, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def _source(handler, protocols) -> MessariSource:
    return MessariSource(SETTINGS, gateway=_gateway(handler), protocols=protocols)


# ── normalisation ─────────────────────────────────────────────────────────


async def test_percent_apy_is_normalised_to_a_fraction():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"data": {"markets": [_market("USDC", 4.32, "1000", "1000", "0")]}}
        )

    facts = await _source(handler, [AAVE]).fetch(["USDC"])

    yields = [f for f in facts if f.kind == "yield"]
    assert len(yields) == 1
    assert yields[0].unit == "apy_fraction"
    assert yields[0].value == 0.0432  # 4.32%, not 4.32


async def test_lender_side_rate_is_used_not_borrower():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"data": {"markets": [_market("USDC", 3.0, "1000", "1000", "0")]}}
        )

    facts = await _source(handler, [AAVE]).fetch(["USDC"])
    # The fixture's borrower rate is 5.0; the vault is a depositor.
    assert [f.value for f in facts if f.kind == "yield"] == [0.03]


async def test_utilization_is_derived_from_the_two_balances():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": {"markets": [_market("USDC", 4.0, "1000000", "1000000", "910000")]}},
        )

    facts = await _source(handler, [AAVE]).fetch(["USDC"])

    utilization = [f for f in facts if f.kind == "utilization"]
    assert len(utilization) == 1
    assert utilization[0].unit == "ratio"
    assert utilization[0].value == 0.91


async def test_zero_deposits_yields_no_utilization_rather_than_dividing_by_zero():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"data": {"markets": [_market("USDC", 4.0, "0", "0", "0")]}}
        )

    facts = await _source(handler, [AAVE]).fetch(["USDC"])
    assert [f for f in facts if f.kind == "utilization"] == []


async def test_missing_rates_still_produce_tvl_facts():
    """A partial market is worth reporting; it is not an error."""

    def handler(request: httpx.Request) -> httpx.Response:
        market = _market("USDC", 4.0, "5000", "5000", "0")
        market["rates"] = []
        return httpx.Response(200, json={"data": {"markets": [market]}})

    facts = await _source(handler, [AAVE]).fetch(["USDC"])
    kinds = {f.kind for f in facts}
    assert "tvl" in kinds
    assert "yield" not in kinds


# ── provenance and shape ──────────────────────────────────────────────────


async def test_every_fact_carries_the_registry_key_as_provenance():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"data": {"markets": [_market("USDC", 4.0, "1", "1", "0")]}}
        )

    facts = await _source(handler, [AAVE]).fetch(["USDC"])
    assert facts, "expected facts"
    assert {f.source for f in facts} == {"messari"}
    assert {f.subject.protocol for f in facts} == {"aave-v3"}


async def test_assets_are_filtered_case_insensitively():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": {
                    "markets": [
                        _market("USDC", 4.0, "1", "1", "0"),
                        _market("DAI", 9.0, "1", "1", "0"),
                    ]
                }
            },
        )

    facts = await _source(handler, [AAVE]).fetch(["usdc"])
    assert {f.subject.market for f in facts} == {"USDC"}


async def test_one_query_shape_serves_every_lending_protocol():
    """The composition argument, asserted: identical document, N protocols."""
    documents: list[str] = []
    seen_subgraphs: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        documents.append(body["query"])
        seen_subgraphs.append(str(request.url).rsplit("/", 1)[-1])
        return httpx.Response(
            200, json={"data": {"markets": [_market("USDC", 4.0, "1", "1", "0")]}}
        )

    facts = await _source(handler, [AAVE, MOONWELL]).fetch(["USDC"])

    assert len(set(documents)) == 1, "two protocols must share one query shape"
    assert sorted(seen_subgraphs) == ["sub-aave", "sub-moon"]
    assert {f.subject.protocol for f in facts} == {"aave-v3", "moonwell"}


# ── degradation ───────────────────────────────────────────────────────────


async def test_one_failing_protocol_does_not_lose_the_others():
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith("sub-moon"):
            return httpx.Response(502, text="bad gateway")
        return httpx.Response(
            200, json={"data": {"markets": [_market("USDC", 4.0, "1", "1", "0")]}}
        )

    source = _source(handler, [AAVE, MOONWELL])
    facts = await source.fetch(["USDC"])

    assert {f.subject.protocol for f in facts} == {"aave-v3"}
    notes = source.drain_notes()
    assert len(notes) == 1
    assert "moonwell" in notes[0]
    assert "502" in notes[0]


async def test_graphql_errors_become_a_note_naming_the_protocol():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"errors": [{"message": "Type `Market` has no field `rates`"}]}
        )

    source = _source(handler, [AAVE])
    facts = await source.fetch(["USDC"])

    assert facts == []
    notes = source.drain_notes()
    assert "aave-v3" in notes[0]
    assert "no field" in notes[0]


async def test_no_matching_market_is_noted_not_silent():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"data": {"markets": [_market("DAI", 4.0, "1", "1", "0")]}}
        )

    source = _source(handler, [AAVE])
    facts = await source.fetch(["USDC"])

    assert facts == []
    assert "no active market" in source.drain_notes()[0]


async def test_missing_api_key_fails_once_for_the_whole_source():
    """One actionable error, not one per configured protocol."""
    source = MessariSource(Settings(), protocols=[AAVE, MOONWELL, UNI])
    try:
        await source.fetch(["USDC"])
    except RuntimeError as exc:
        assert "GRAPH_API_KEY" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected a RuntimeError")


# ── dex ───────────────────────────────────────────────────────────────────


async def test_dex_pools_produce_liquidity_facts_with_a_pair_subject():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": {
                    "liquidityPools": [
                        {
                            "id": "0xpool",
                            "name": "USDC/WETH 0.05%",
                            "inputTokens": [
                                {"id": "0x1", "symbol": "USDC", "decimals": 6},
                                {"id": "0x2", "symbol": "WETH", "decimals": 18},
                            ],
                            "totalValueLockedUSD": "12400000",
                        }
                    ]
                }
            },
        )

    facts = await _source(handler, [UNI]).fetch(["USDC", "WETH"])

    assert len(facts) == 1
    assert facts[0].kind == "liquidity"
    assert facts[0].unit == "usd"
    assert facts[0].value == 12_400_000.0
    assert facts[0].subject.pair == ["USDC", "WETH"]


async def test_a_dex_subgraph_with_its_own_schema_falls_back_to_the_native_shape():
    """Uniswap's own subgraph exposes `pools { token0 token1 }`, not Messari's
    `liquidityPools { inputTokens }`. Losing DEX liquidity entirely because a
    subgraph is published by its protocol rather than by Messari is avoidable."""
    documents: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        document = json.loads(request.content)["query"]
        documents.append(document)
        if "liquidityPools" in document:
            return httpx.Response(
                200,
                json={"errors": [{"message": "Type `Query` has no field `liquidityPools`"}]},
            )
        return httpx.Response(
            200,
            json={
                "data": {
                    "pools": [
                        {
                            "id": "0xpool",
                            "token0": {"id": "0x1", "symbol": "USDC", "decimals": 6},
                            "token1": {"id": "0x2", "symbol": "WETH", "decimals": 18},
                            "totalValueLockedUSD": "9100000",
                        }
                    ]
                }
            },
        )

    source = _source(handler, [UNI])
    facts = await source.fetch(["USDC", "WETH"])

    assert len(documents) == 2, "expected the standardized shape then the native one"
    assert len(facts) == 1
    assert facts[0].kind == "liquidity"
    assert facts[0].value == 9_100_000.0
    assert facts[0].subject.pair == ["USDC", "WETH"]
    # The fallback is reported, not silent — it is a config fix worth making.
    assert "own pool schema" in source.drain_notes()[0]


async def test_the_standardized_shape_is_preferred_and_costs_no_extra_request():
    documents: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        documents.append(json.loads(request.content)["query"])
        return httpx.Response(
            200,
            json={
                "data": {
                    "liquidityPools": [
                        {
                            "id": "0xpool",
                            "name": "USDC/WETH",
                            "inputTokens": [
                                {"symbol": "USDC"},
                                {"symbol": "WETH"},
                            ],
                            "totalValueLockedUSD": "12400000",
                        }
                    ]
                }
            },
        )

    source = _source(handler, [UNI])
    facts = await source.fetch(["USDC", "WETH"])

    assert len(documents) == 1, "no fallback request when the first shape works"
    assert facts[0].value == 12_400_000.0
    assert source.drain_notes() == []


async def test_a_dex_subgraph_that_answers_neither_shape_degrades_to_a_note():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"errors": [{"message": "no such field"}]})

    source = _source(handler, [UNI])
    assert await source.fetch(["USDC", "WETH"]) == []
    assert "uniswap-v3" in source.drain_notes()[0]


async def test_pools_with_a_leg_outside_the_mandate_are_skipped():
    """The vault can only hold permitted assets, so an ineligible pool is noise."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": {
                    "liquidityPools": [
                        {
                            "id": "0xpool",
                            "name": "USDC/DEGEN",
                            "inputTokens": [
                                {"id": "0x1", "symbol": "USDC", "decimals": 6},
                                {"id": "0x2", "symbol": "DEGEN", "decimals": 18},
                            ],
                            "totalValueLockedUSD": "999",
                        }
                    ]
                }
            },
        )

    assert await _source(handler, [UNI]).fetch(["USDC", "WETH"]) == []
