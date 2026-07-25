"""Morpho source: the guards that live data forced.

Every fixture value here was read from `blue-api.morpho.org` on 2026-07-25.
Two of them are the reason this source has guards at all:

    USDC/cbBTC     supply APY   4.80%   supplied $1,421,638,741   util 0.90
    USDC/HERMES    supply APY 297,892%  supplied $   54,552,553   util 1.00

The second is a real market with real money in it, and an agent told USDC
yields 297,892% would move the whole book into a position it cannot exit.
"""

from __future__ import annotations

import httpx

from curator_data.config import Settings
from curator_data.sources.morpho import MIN_SUPPLY_USD, MorphoSource

SETTINGS = Settings(chain="base")


def _market(loan: str, collateral: str, apy: float, supplied: float, util: float,
            net: float | None = None) -> dict:
    return {
        "marketId": f"0x{loan}{collateral}",
        "loanAsset": {"symbol": loan, "decimals": 6},
        "collateralAsset": {"symbol": collateral},
        "state": {
            "supplyApy": apy,
            "netSupplyApy": apy if net is None else net,
            "supplyAssetsUsd": supplied,
            "utilization": util,
        },
    }


def _source(markets: list[dict] | None = None, *, handler=None) -> MorphoSource:
    if handler is None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": {"markets": {"items": markets or []}}})

    return MorphoSource(
        SETTINGS, client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )


def _by_market(facts) -> dict:
    out: dict = {}
    for f in facts:
        out.setdefault(f.subject.market, {})[f.kind] = f.value
    return out


# ── the plausibility guard ────────────────────────────────────────────────


async def test_an_impossible_yield_drops_the_whole_market_not_just_the_rate():
    """Live: USDC/HERMES, 297,892% APY on $54M at 100% utilization.

    Keeping the TVL would still present it as a real venue, and size is what
    an agent uses to judge whether a market is safe to enter.
    """
    source = _source([
        _market("USDC", "cbBTC", 0.048, 1_421_638_741, 0.90),
        _market("USDC", "HERMES", 2978.9252, 54_552_553, 1.00),
    ])
    rows = _by_market(await source.fetch(["USDC"]))

    assert "USDC/HERMES" not in rows
    assert rows["USDC/cbBTC"]["yield"] == 0.048

    note = [n for n in source.drain_remarks() if "HERMES" in n][0]
    assert "297893%" in note
    assert "whole market is dropped" in note


async def test_a_plausible_high_yield_is_kept():
    """The guard must not swallow a genuinely good rate. Live: 16.14%."""
    rows = _by_market(await _source([_market("USDC", "RSS", 0.1614, 50_013_133, 1.0)]).fetch(
        ["USDC"]
    ))
    assert round(rows["USDC/RSS"]["yield"], 4) == 0.1614


# ── duplicate markets ─────────────────────────────────────────────────────


async def test_only_the_deepest_market_for_a_pair_is_reported():
    """Morpho Blue permits many markets per pair - USDC/HERMES appeared 24
    times live. An agent wants the best market for a pair, not every variant."""
    source = _source([
        _market("USDC", "cbETH", 0.048, 6_690_391, 0.90),
        _market("USDC", "cbETH", 0.031, 4_958_158, 0.88),
        _market("USDC", "cbETH", 0.020, 2_000_000, 0.50),
    ])
    facts = await source.fetch(["USDC"])

    assert len([f for f in facts if f.kind == "tvl"]) == 1
    rows = _by_market(facts)
    assert rows["USDC/cbETH"]["tvl"] == 6_690_391  # the deepest, not the last


async def test_a_dropped_pair_is_only_reported_once():
    """24 clones of an impossible market must not produce 24 notes."""
    source = _source([_market("USDC", "HERMES", 2978.9, 54_000_000, 1.0) for _ in range(24)])
    await source.fetch(["USDC"])
    assert len([n for n in source.drain_remarks() if "HERMES" in n]) == 1


# ── base versus headline, again ───────────────────────────────────────────


async def test_the_base_supply_apy_is_reported_not_the_net_figure():
    """netSupplyApy adds rewards and subtracts fees - the same base-versus-
    headline trap DefiLlama taught this lane."""
    source = _source([_market("USDC", "WETH", 0.048, 77_467_597, 0.90, net=0.092)])
    rows = _by_market(await source.fetch(["USDC"]))

    assert rows["USDC/WETH"]["yield"] == 0.048
    note = [n for n in source.drain_remarks() if "WETH" in n][0]
    assert "4.80%" in note and "9.20%" in note
    assert "not interest earned" in note


# ── liquidity and exit risk ───────────────────────────────────────────────


async def test_full_utilization_is_flagged_as_hard_to_exit():
    source = _source([_market("USDC", "RSS", 0.16, 50_013_133, 1.0)])
    await source.fetch(["USDC"])
    note = [n for n in source.drain_remarks() if "utilization" in n][0]
    assert "100%" in note
    assert "hard to exit" in note


async def test_a_healthy_utilization_is_not_flagged():
    source = _source([_market("USDC", "cbBTC", 0.048, 1_421_638_741, 0.90)])
    await source.fetch(["USDC"])
    assert not [n for n in source.drain_remarks() if "hard to exit" in n]


async def test_thin_markets_are_skipped():
    """Below the floor the vault would become most of the market."""
    facts = await _source([_market("USDC", "TINY", 0.05, MIN_SUPPLY_USD - 1, 0.5)]).fetch(
        ["USDC"]
    )
    assert facts == []


# ── filtering and provenance ──────────────────────────────────────────────


async def test_markets_are_matched_on_the_loan_asset():
    """The vault supplies the loan side; collateral is someone else's risk."""
    source = _source([
        _market("USDC", "cbBTC", 0.048, 1_421_638_741, 0.90),
        _market("WETH", "wstETH", 0.0157, 6_988_221, 0.90),
    ])
    rows = _by_market(await source.fetch(["USDC"]))
    assert set(rows) == {"USDC/cbBTC"}


async def test_facts_carry_morpho_as_provenance():
    facts = await _source([_market("USDC", "cbBTC", 0.048, 1_421_638_741, 0.9)]).fetch(["USDC"])
    assert {f.source for f in facts} == {"morpho"}
    assert {f.subject.protocol for f in facts} == {"morpho"}


async def test_no_matching_market_is_context_not_a_failure():
    source = _source([_market("USDC", "cbBTC", 0.048, 1_421_638_741, 0.9)])
    assert await source.fetch(["DAI"]) == []
    assert source.drain_notes() == []
    assert "not an option" in source.drain_remarks()[0]


# ── degradation ───────────────────────────────────────────────────────────


async def test_an_unreachable_api_degrades_rather_than_raising():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("[Errno 11001] getaddrinfo failed")

    source = _source(handler=handler)
    assert await source.fetch(["USDC"]) == []
    note = source.drain_notes()[0]
    assert "DNS" in note          # translated, not an errno dump
    assert " - " in note          # three-part diagnosis


async def test_a_graphql_error_degrades_with_the_message():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"errors": [{"message": "Cannot query field 'x'"}]})

    source = _source(handler=handler)
    assert await source.fetch(["USDC"]) == []
    assert "Cannot query field" in source.drain_notes()[0]


async def test_a_stray_error_does_not_kill_the_source():
    """`except Exception`, not a tuple of the two types that came to mind -
    a stray RuntimeError took the gas source down in Wave 1 for that reason."""
    def handler(request: httpx.Request) -> httpx.Response:
        raise RuntimeError("something nobody predicted")

    source = _source(handler=handler)
    assert await source.fetch(["USDC"]) == []
    assert source.drain_notes()


async def test_the_source_needs_no_credential():
    """Registered alongside defillama, feargreed and gas on the same terms."""
    assert MorphoSource(Settings(chain="base")) is not None
