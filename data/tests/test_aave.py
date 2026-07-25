"""Aave source: three unit conversions that are each wrong by default.

Aave's schema is not normalised the way Messari's is, and every fixture value
below is a **real reading taken from the live Base subgraph on 2026-07-25**.
That matters — these conversions were derived by inspecting live data, not from
documentation, so the tests pin the actual observed encodings.
"""

from __future__ import annotations

import httpx

from curator_data.config import Settings
from curator_data.graph.gateway import GatewayClient
from curator_data.sources.aave import AaveSource
from curator_data.sources.protocols import Protocol

SETTINGS = Settings(graph_api_key="test-key")
AAVE = Protocol(
    key="aave-v3", subgraph_id="sub-aave", family="lending-aave", label="Aave V3 (Base)"
)


def _reserve(**over) -> dict:
    # Live USDC reading: 3.41% APY, $174.9M supplied, 0.839 utilization.
    reserve = {
        "symbol": "USDC",
        "decimals": 6,
        "isFrozen": False,
        "liquidityRate": "34103326851550584403425692",
        "utilizationRate": "0.83912345",
        "totalATokenSupply": "174891160000000",
        "price": {"priceInEth": "99990000"},
    }
    reserve.update(over)
    return reserve


def _source(handler, protocols=None) -> AaveSource:
    gateway = GatewayClient(
        SETTINGS, client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    return AaveSource(SETTINGS, gateway=gateway, protocols=protocols or [AAVE])


def _handler(reserves):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"reserves": reserves}})

    return handler


# ── the three conversions ─────────────────────────────────────────────────


async def test_liquidity_rate_is_ray_fixed_point_not_a_fraction():
    """`liquidityRate` is an APR in RAY (1e27). Live USDC read 3.41%."""
    facts = await _source(_handler([_reserve()])).fetch(["USDC"])

    yields = [f for f in facts if f.kind == "yield"]
    assert len(yields) == 1
    assert yields[0].unit == "apy_fraction"
    assert round(yields[0].value, 6) == 0.034103  # 3.41%, not 3.41e25


async def test_price_in_eth_actually_holds_usd_with_eight_decimals():
    """A misnomer in Aave's schema. USDC read 99990000 -> $0.9999."""
    facts = await _source(_handler([_reserve()])).fetch(["USDC"])

    tvl = [f for f in facts if f.kind == "tvl"]
    assert len(tvl) == 1
    # 174,891,160 USDC x $0.9999
    assert round(tvl[0].value) == 174_873_671
    assert tvl[0].unit == "usd"


async def test_utilization_is_already_a_ratio_and_is_not_rescaled():
    facts = await _source(_handler([_reserve()])).fetch(["USDC"])
    utilization = [f for f in facts if f.kind == "utilization"]
    assert round(utilization[0].value, 6) == 0.839123


async def test_a_negative_utilization_is_dropped_not_clamped():
    """Live USDbC reported -3.4406. Clamping to 0 would assert 'no borrowing',
    which is a claim about the market rather than a repair of the data."""
    facts = await _source(_handler([_reserve(utilizationRate="-3.4406")])).fetch(["USDC"])

    assert [f for f in facts if f.kind == "utilization"] == []
    # The other facts from the same reserve survive.
    assert {f.kind for f in facts} == {"yield", "tvl"}


async def test_an_eighteen_decimal_token_scales_correctly():
    """WETH: 94,216.1 tokens x $1856.69 -> ~$174.9M. Live reading."""
    facts = await _source(
        _handler(
            [
                _reserve(
                    symbol="WETH",
                    decimals=18,
                    totalATokenSupply="94216100000000000000000",
                    price={"priceInEth": "185669410000"},
                )
            ]
        )
    ).fetch(["WETH"])

    tvl = [f for f in facts if f.kind == "tvl"][0]
    assert 174_000_000 < tvl.value < 176_000_000


# ── provenance and filtering ──────────────────────────────────────────────


async def test_facts_are_attributed_to_aave_not_to_the_messari_adapter():
    """Provenance is the point of a separate source key."""
    facts = await _source(_handler([_reserve()])).fetch(["USDC"])
    assert {f.source for f in facts} == {"aave"}
    assert {f.subject.protocol for f in facts} == {"aave-v3"}


async def test_frozen_reserves_are_skipped():
    """A frozen reserve still reports a rate, but nothing can be supplied."""
    facts = await _source(_handler([_reserve(isFrozen=True)])).fetch(["USDC"])
    assert facts == []


async def test_assets_are_filtered_case_insensitively():
    reserves = [_reserve(), _reserve(symbol="DAI")]
    facts = await _source(_handler(reserves)).fetch(["usdc"])
    assert {f.subject.market for f in facts} == {"USDC"}


async def test_no_matching_reserve_is_noted():
    source = _source(_handler([_reserve(symbol="DAI")]))
    assert await source.fetch(["USDC"]) == []
    assert "no active reserve" in source.drain_notes()[0]


async def test_a_missing_price_costs_only_the_tvl_fact():
    facts = await _source(_handler([_reserve(price=None)])).fetch(["USDC"])
    kinds = {f.kind for f in facts}
    assert "tvl" not in kinds
    assert {"yield", "utilization"} <= kinds


async def test_a_failing_subgraph_degrades_to_a_note():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"errors": [{"message": "indexers unavailable"}]})

    source = _source(handler)
    assert await source.fetch(["USDC"]) == []
    assert "aave-v3" in source.drain_notes()[0]


async def test_the_source_declares_the_kinds_it_provides():
    """Capability lookup routes market queries here without naming it."""
    assert set(AaveSource(SETTINGS).provides) == {"yield", "tvl", "utilization"}
