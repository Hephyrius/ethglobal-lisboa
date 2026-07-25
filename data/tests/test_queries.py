"""Pivots from flat facts back into market rows.

Driven by the shared golden fixture, so this also verifies that the shape Lane
B and Lane E develop against is the shape this layer actually produces.
"""

from __future__ import annotations

import json
import pathlib

from curator_schema.models import MarketSnapshot

from curator_data.queries import errors_as_dicts, pivot_markets, pivot_pools, prices

FIXTURE = (
    pathlib.Path(__file__).resolve().parents[2]
    / "packages"
    / "schema"
    / "fixtures"
    / "market-snapshot.json"
)


def _snapshot() -> MarketSnapshot:
    return MarketSnapshot.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))


def test_the_golden_fixture_still_parses():
    """If this breaks, the frozen interface moved and the lane must catch up."""
    assert _snapshot().facts


def test_markets_pivot_out_of_the_fixture():
    rows = {(r.protocol, r.market): r for r in pivot_markets(_snapshot())}

    morpho = rows[("morpho-blue", "USDC")]
    assert morpho.supply_apy == 0.0587
    assert morpho.tvl_usd == 84_200_000.0
    assert morpho.utilization == 0.91

    aave = rows[("aave-v3", "USDC")]
    assert aave.supply_apy == 0.0432
    assert aave.tvl_usd is None  # the fixture has no TVL fact for aave


def test_rows_are_sorted_by_apy_descending():
    rows = pivot_markets(_snapshot())
    assert rows[0].protocol == "morpho-blue"  # 5.87% beats 4.32%


def test_rows_carry_the_fact_ids_that_built_them():
    """`AllocationDecision.facts_used` expects exactly these."""
    rows = {r.protocol: r for r in pivot_markets(_snapshot())}
    assert set(rows["morpho-blue"].fact_ids) == {"f2", "f3", "f4"}
    assert rows["morpho-blue"].sources == ["messari"]


def test_display_percentage_is_derived_not_stored():
    rows = {r.protocol: r for r in pivot_markets(_snapshot())}
    assert rows["aave-v3"].supply_apy_pct == 4.32


def test_pools_pivot_with_their_pair():
    pools = pivot_pools(_snapshot())
    assert len(pools) == 1
    assert pools[0].protocol == "uniswap-v3"
    assert pools[0].pair == ["USDC", "WETH"]
    assert pools[0].liquidity_usd == 12_400_000.0


def test_prices_pivot_by_symbol():
    weth = prices(_snapshot())["WETH"]
    assert weth["price_usd"] == 3218.44
    assert weth["source"] == "token_api"
    assert weth["fact_id"] == "f5"


def test_errors_survive_the_pivot():
    """Degradation must reach the consumer; a partial view has to look partial."""
    errors = errors_as_dicts(_snapshot())
    assert len(errors) == 1
    assert errors[0]["source"] == "token_api"


def test_pivots_are_empty_not_broken_on_an_empty_snapshot():
    from datetime import datetime, timezone

    empty = MarketSnapshot(taken_at=datetime.now(timezone.utc))
    assert pivot_markets(empty) == []
    assert pivot_pools(empty) == []
    assert prices(empty) == {}
