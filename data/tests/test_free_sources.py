"""P3 — the three sources that need no credential.

Before these, every registered source needed a Graph key, so someone cloning
the repo got an empty snapshot and four error lines. These also close two
substantive gaps rather than just adding rows: the agent could compare exactly
two lending protocols and call it a market, and it could see a 3 bps yield edge
with no way to know that capturing it costs more than it earns.
"""

from __future__ import annotations

import httpx
import pytest

from curator_data.config import Settings
from curator_data.sources.defillama import MIN_TVL_USD, TOP_N, DefiLlamaSource
from curator_data.sources.gas import REBALANCE_GAS_UNITS, GasSource
from curator_data.sources.sentiment import SentimentSource


def _pool(project, symbol, tvl, *, apy=None, apy_base=None, apy_reward=None, chain="Base"):
    return {
        "chain": chain,
        "project": project,
        "symbol": symbol,
        "tvlUsd": tvl,
        "apy": apy,
        "apyBase": apy_base,
        "apyReward": apy_reward,
    }


def _llama(pools) -> DefiLlamaSource:
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"data": pools}))
    return DefiLlamaSource(Settings(), client=httpx.AsyncClient(transport=transport))


# ── DefiLlama: the emissions distinction ──────────────────────────────────


async def test_a_headline_apy_that_is_mostly_emissions_is_reported_as_its_base_yield():
    """The judgement this source turns on, taken from a real live reading.

    The first live run put `aerodrome-slipstream USDC-CBBTC at 91.14%` above
    `aave-v3 USDC at 3.50%`, and an agent told to pursue yield would read that
    as Aave being 26x worse. It is not: 91% was `apyBase + apyReward` and the
    reward leg is a token emission — a bet on the emitted token's price, with a
    different risk profile and an expiry, not interest.
    """
    source = _llama([_pool("aerodrome", "USDC-CBBTC", 4_300_000, apy=91.14, apy_base=14.66)])
    facts = await source.fetch(["USDC"])

    yields = [f for f in facts if f.kind == "yield"]
    assert len(yields) == 1
    assert yields[0].value == pytest.approx(0.1466), "the base yield, not the headline"
    assert any("emissions" in r for r in source.drain_remarks())


async def test_a_pool_with_no_split_is_used_but_flagged():
    """Dropping it would lose a real pool; presenting it as interest would lie."""
    source = _llama([_pool("somewhere", "USDC", 5_000_000, apy=8.0)])
    facts = await source.fetch(["USDC"])

    assert [f.value for f in facts if f.kind == "yield"] == [pytest.approx(0.08)]
    assert any("no base/reward split" in r for r in source.drain_remarks())


async def test_a_shallow_pool_is_not_offered_at_all():
    """A pool the vault would *be* most of is not an opportunity."""
    source = _llama([_pool("dust", "USDC", MIN_TVL_USD / 100, apy_base=40.0)])
    assert await source.fetch(["USDC"]) == []


async def test_another_chain_is_never_included():
    source = _llama([_pool("aave-v3", "USDC", 500_000_000, apy_base=6.0, chain="Ethereum")])
    assert await source.fetch(["USDC"]) == []


async def test_truncation_is_announced_rather_than_silent():
    """A model told 'here is the market' when shown a quarter of it reasons
    confidently about a subset."""
    pools = [
        _pool(f"protocol-{i}", "USDC", 10_000_000 - i, apy_base=3.0) for i in range(TOP_N + 5)
    ]
    source = _llama(pools)
    await source.fetch(["USDC"])
    assert any("deepest by TVL" in r for r in source.drain_remarks())


async def test_aggregator_facts_carry_lower_confidence_than_a_subgraph_would():
    """The Graph stays the depth layer. A number an aggregator computed from
    someone else's indexer is a weaker claim, and `confidence` is where that
    belongs rather than in a comment."""
    source = _llama([_pool("aave-v3", "USDC", 20_000_000, apy_base=3.5)])
    facts = await source.fetch(["USDC"])
    assert all(f.confidence is not None and f.confidence < 1.0 for f in facts)


# ── Fear & Greed ──────────────────────────────────────────────────────────


def _fng(value, *, classification="Fear", timestamp="1784900000") -> SentimentSource:
    payload = {
        "data": [
            {"value": value, "value_classification": classification, "timestamp": timestamp}
        ]
    }
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json=payload))
    return SentimentSource(Settings(), client=httpx.AsyncClient(transport=transport))


async def test_sentiment_is_normalised_to_a_fraction():
    """0.27, not 27. Every other fraction-valued fact in the schema is a
    fraction, and a mixed convention inside one snapshot traps both the model
    and the UI."""
    facts = await _fng("27").fetch([])
    assert len(facts) == 1
    assert facts[0].value == pytest.approx(0.27)
    assert facts[0].kind == "sentiment"


async def test_sentiment_is_its_own_kind_not_an_overloaded_ratio():
    """`_KIND_LABELS` in the curator prompt exists because a 3B model read
    `f6 | liquidity | $12.4M` as '10.43% APY'. Overloading a kind is how that
    happens again — a utilization of 0.78 and a sentiment of 0.78 mean entirely
    different things and must not render alike."""
    facts = await _fng("78", classification="Extreme Greed").fetch([])
    assert facts[0].kind == "sentiment"
    assert facts[0].subject.token is None, "sentiment is not about one asset"
    assert facts[0].subject.protocol is None


async def test_an_out_of_range_reading_fails_rather_than_being_rescaled():
    """Out of 0-100 means the API changed shape. Dividing by 100 anyway would
    hand the agent a number with no defined meaning."""
    with pytest.raises(RuntimeError, match="outside its documented"):
        await _fng("427").fetch([])


async def test_observed_at_is_when_the_index_published_not_when_we_asked():
    """Staleness is the agent's to reason about (frozen schema), which only
    works if we report when the SOURCE spoke."""
    facts = await _fng("50", timestamp="1784900000").fetch([])
    assert int(facts[0].observed_at.timestamp()) == 1784900000


# ── Gas ───────────────────────────────────────────────────────────────────


class _FakeRpc:
    """Answers eth_gasPrice and the ETH/USD feed, nothing else."""

    def __init__(self, gas_wei: int, eth_usd: float | None = 2000.0) -> None:
        self._gas_wei = gas_wei
        self._eth_usd = eth_usd

    async def request(self, method, params):
        assert method == "eth_gasPrice"
        return hex(self._gas_wei)

    async def call(self, to, selector):
        if self._eth_usd is None:
            raise RuntimeError("feed unreachable")
        # latestRoundData: five words, answer is the second, 8 decimals.
        answer = int(self._eth_usd * 10**8)
        return b"".join(
            [
                (1).to_bytes(32, "big"),
                answer.to_bytes(32, "big"),
                (0).to_bytes(32, "big"),
                (0).to_bytes(32, "big"),
                (1).to_bytes(32, "big"),
            ]
        )

    async def aclose(self):
        return None


async def test_gas_reports_a_dollar_cost_not_just_gwei():
    """'0.05 gwei' does not tell a model whether a 3 bps edge is worth taking.

    The multiplication is done here rather than in the prompt because
    gwei x gas units x 1e-9 x ETH/USD is exactly the unit-juggling that made a
    3B model report $12.4M of liquidity as a 10.43% APY.
    """
    source = GasSource(Settings(), rpc=_FakeRpc(gas_wei=50_000_000, eth_usd=2_000.0))
    facts = await source.fetch([])

    usd = [f for f in facts if f.unit == "usd"]
    assert len(usd) == 1
    expected = (50_000_000 * REBALANCE_GAS_UNITS / 1e18) * 2_000.0
    assert usd[0].value == pytest.approx(expected)
    assert all(f.kind == "gas" for f in facts)


async def test_gas_still_reports_gwei_when_the_price_feed_is_unreachable():
    """Losing the gwei figure because the oracle blinked is the wrong trade."""
    source = GasSource(Settings(), rpc=_FakeRpc(gas_wei=50_000_000, eth_usd=None))
    facts = await source.fetch([])

    assert [f.unit for f in facts] == ["token_amount"]
    assert source.drain_notes() == [], "a missing extra is not a source failure"
    assert any("USD cost" in r for r in source.drain_remarks())


# ── liquid-staking yield: the yield that is not chain-scoped ──────────────
#
# The Wave 2 feedback asked for LST yield by name. It is the one rate here that
# deliberately ignores the Base filter: a staking rate attaches to the TOKEN,
# not the venue, so wstETH held on Base accrues exactly the Lido rate. Live
# values on 2026-07-25: Lido STETH 2.045%, rocket-pool RETH 2.207%,
# coinbase cbETH 2.358%.

def _staking_pool(project: str, symbol: str, apy: float, tvl: float = 5e9,
                  chain: str = "Ethereum") -> dict:
    return {
        "project": project, "symbol": symbol, "chain": chain,
        "apy": apy, "apyBase": apy, "apyReward": None, "tvlUsd": tvl,
    }


async def test_the_staking_yield_of_a_held_token_is_reported():
    source = _llama([_staking_pool("rocket-pool", "RETH", 2.20696)])
    facts = await source.fetch(["rETH"])

    staking = [f for f in facts if f.subject.token == "RETH"]
    assert len(staking) == 1
    assert round(staking[0].value, 5) == 0.02207


async def test_wsteth_resolves_through_lidos_steth_pool():
    """A mandate names wstETH; Lido publishes STETH. Looking for a pool called
    WSTETH finds nothing, and the agent concludes wstETH earns only the 0.08%
    it gets from lending."""
    source = _llama([_staking_pool("lido", "STETH", 2.045, tvl=1.7e10)])
    facts = await source.fetch(["wstETH"])

    staking = [f for f in facts if f.subject.token == "WSTETH"]
    assert len(staking) == 1
    assert round(staking[0].value, 5) == 0.02045


async def test_the_staking_pool_is_not_chain_filtered():
    """Every other pool here is Base-only. This one must not be, or the
    canonical Lido pool on Ethereum is invisible."""
    source = _llama([_staking_pool("lido", "STETH", 2.045, chain="Ethereum")])
    assert [f for f in await source.fetch(["wstETH"]) if f.subject.token]


async def test_a_small_mirror_pool_does_not_set_the_rate():
    """The same project publishes small mirrors on other chains."""
    source = _llama([
        _staking_pool("lido", "STETH", 9.99, tvl=1_000.0, chain="Fantom"),
        _staking_pool("lido", "STETH", 2.045, tvl=1.7e10, chain="Ethereum"),
    ])
    facts = [f for f in await source.fetch(["wstETH"]) if f.subject.token]
    assert round(facts[0].value, 5) == 0.02045


async def test_the_note_says_staking_stacks_with_lending():
    """An agent reading them as alternatives draws the wrong conclusion:
    holding wstETH earns staking, and lending it earns lending on top."""
    source = _llama([_staking_pool("lido", "STETH", 2.045)])
    await source.fetch(["wstETH"])
    note = [n for n in source.drain_remarks() if "staking yield" in n][0]
    assert "just for being held" in note
    assert "stacks" in note


async def test_an_unrequested_lst_is_not_reported():
    source = _llama([_staking_pool("lido", "STETH", 2.045)])
    assert [f for f in await source.fetch(["USDC"]) if f.subject.token] == []
