"""Chainlink source: decoding, identity verification, staleness.

Fixture values are real readings from the Base fork on 2026-07-25 — ETH/USD at
`$1,858.9782` and USDC/USD at `$0.9999`, both 8 decimals.

The identity test is the one that matters most. A wrong feed address does not
raise, time out, or return anything malformed: it returns a confident,
well-formed, completely wrong price, and the vault allocates real capital on
it. Verified against the live fork that pointing WETH at the USDC aggregator
would price WETH at $1.00.
"""

from __future__ import annotations

import time

import pytest

from curator_data.chain.rpc import RpcError, decode_string, decode_word
from curator_data.config import Settings
from curator_data.sources.chainlink import (
    SELECTOR_DECIMALS,
    SELECTOR_DESCRIPTION,
    SELECTOR_LATEST_ROUND_DATA,
    ChainlinkSource,
)
from curator_data.sources.feeds import PriceFeed

SETTINGS = Settings(chain="base", rpc_url="http://node.example")
WETH_FEED = PriceFeed("WETH", "0x71041dddad3595F9CEd3DcCFBe3D1F4b0a16Bb70", "ETH / USD")

# Live ETH/USD reading: answer 0x2b485f8c38 with 8 decimals.
LIVE_ANSWER = 185_897_820_000


def _word(value: int, *, signed: bool = False) -> bytes:
    return value.to_bytes(32, "big", signed=signed)


def _round_data(answer: int, *, updated_at: int | None = None, round_id: int = 5,
                answered_in: int | None = None) -> bytes:
    return (
        _word(round_id)
        + _word(answer, signed=True)
        + _word(0)
        + _word(updated_at if updated_at is not None else int(time.time()))
        + _word(round_id if answered_in is None else answered_in)
    )


def _string(text: str) -> bytes:
    raw = text.encode()
    padded = raw + b"\x00" * ((32 - len(raw) % 32) % 32)
    return _word(32) + _word(len(raw)) + padded


class FakeRpc:
    """Stands in for a node. Records calls so we can assert on caching."""

    def __init__(self, *, description: str = "ETH / USD", decimals: int = 8,
                 round_data: bytes | None = None, fail: Exception | None = None):
        self._description = description
        self._decimals = decimals
        self._round = round_data if round_data is not None else _round_data(LIVE_ANSWER)
        self._fail = fail
        self.calls: list[str] = []

    async def call(self, to: str, selector: str) -> bytes:
        self.calls.append(selector)
        if self._fail is not None:
            raise self._fail
        if selector == SELECTOR_DESCRIPTION:
            return _string(self._description)
        if selector == SELECTOR_DECIMALS:
            return _word(self._decimals)
        if selector == SELECTOR_LATEST_ROUND_DATA:
            return self._round
        raise RpcError(f"unexpected selector {selector}")

    async def aclose(self) -> None:
        return None


def _source(rpc: FakeRpc, feeds=(WETH_FEED,)) -> ChainlinkSource:
    return ChainlinkSource(SETTINGS, rpc=rpc, feeds=feeds)


# ── the identity guard ────────────────────────────────────────────────────


async def test_a_feed_that_is_not_what_we_expect_is_refused():
    """The failure mode with no symptom other than a wrong number."""
    source = _source(FakeRpc(description="USDC / USD"))  # right contract, wrong feed

    assert await source.fetch(["WETH"]) == []
    note = source.drain_notes()[0]
    assert "reports itself as 'USDC / USD'" in note
    assert "refusing to price" in note


async def test_identity_is_verified_once_and_then_cached():
    rpc = FakeRpc()
    source = _source(rpc)
    await source.fetch(["WETH"])
    await source.fetch(["WETH"])
    assert rpc.calls.count(SELECTOR_DESCRIPTION) == 1
    assert rpc.calls.count(SELECTOR_DECIMALS) == 1


async def test_description_matching_ignores_case_and_padding():
    source = _source(FakeRpc(description="  eth / usd  "))
    assert len(await source.fetch(["WETH"])) == 1


# ── decoding ──────────────────────────────────────────────────────────────


async def test_the_answer_is_scaled_by_the_feeds_own_decimals():
    facts = await _source(FakeRpc()).fetch(["WETH"])
    assert len(facts) == 1
    assert round(facts[0].value, 4) == 1858.9782
    assert facts[0].unit == "usd"
    assert facts[0].source == "chainlink"


async def test_decimals_are_read_from_the_feed_not_assumed():
    """An 18-decimal feed must not be read as an 8-decimal one."""
    facts = await _source(FakeRpc(decimals=18, round_data=_round_data(2 * 10**18))).fetch(
        ["WETH"]
    )
    assert facts[0].value == 2.0


async def test_observed_at_is_when_the_oracle_spoke_not_when_we_asked():
    """Staleness is the agent's to reason about, which needs the oracle's clock."""
    when = int(time.time()) - 600
    facts = await _source(FakeRpc(round_data=_round_data(LIVE_ANSWER, updated_at=when))).fetch(
        ["WETH"]
    )
    assert int(facts[0].observed_at.timestamp()) == when


# ── refusing bad data ─────────────────────────────────────────────────────


@pytest.mark.parametrize("answer", [0, -1, -185_897_820_000])
async def test_a_non_positive_answer_is_dropped(answer):
    """A signed return means a broken feed can report a negative price."""
    source = _source(FakeRpc(round_data=_round_data(answer)))
    assert await source.fetch(["WETH"]) == []
    assert "non-positive" in source.drain_notes()[0]


async def test_an_incomplete_round_is_dropped():
    source = _source(FakeRpc(round_data=_round_data(LIVE_ANSWER, round_id=9, answered_in=8)))
    assert await source.fetch(["WETH"]) == []
    assert "incomplete" in source.drain_notes()[0]


async def test_a_stale_price_is_still_returned_but_flagged():
    """Staleness is information, not grounds for hiding the number."""
    old = int(time.time()) - 60 * 60 * 48
    source = _source(FakeRpc(round_data=_round_data(LIVE_ANSWER, updated_at=old)))

    facts = await source.fetch(["WETH"])
    assert len(facts) == 1
    assert "stale" in source.drain_notes()[0]


async def test_an_unreachable_node_degrades_to_a_note():
    source = _source(FakeRpc(fail=RpcError("node unreachable")))
    assert await source.fetch(["WETH"]) == []
    assert "unreachable" in source.drain_notes()[0]


async def test_an_asset_with_no_feed_is_named_with_the_fix():
    source = _source(FakeRpc())
    await source.fetch(["WETH", "DOGE"])
    assert any("DOGE" in n and "feeds.py" in n for n in source.drain_notes())


async def test_one_broken_feed_does_not_lose_the_others():
    class Mixed(FakeRpc):
        async def call(self, to: str, selector: str) -> bytes:
            if to.lower().startswith("0xdead"):
                raise RpcError("no contract there")
            return await super().call(to, selector)

    feeds = (WETH_FEED, PriceFeed("USDC", "0xdead", "USDC / USD"))
    source = ChainlinkSource(SETTINGS, rpc=Mixed(), feeds=feeds)

    facts = await source.fetch(["WETH", "USDC"])
    assert [f.subject.token for f in facts] == ["WETH"]
    assert source.drain_notes()


async def test_missing_rpc_configuration_is_an_actionable_error():
    source = ChainlinkSource(Settings(chain="base"), feeds=(WETH_FEED,))
    await source.fetch(["WETH"])
    assert "DATA_RPC_URL" in source.drain_notes()[0]


async def test_the_source_needs_no_api_credential():
    """The point of this source: price facts survive a missing API key."""
    source = ChainlinkSource(Settings(chain="base", rpc_url="http://node.example"),
                             rpc=FakeRpc(), feeds=(WETH_FEED,))
    assert len(await source.fetch(["WETH"])) == 1


# ── raw decoding helpers ──────────────────────────────────────────────────


def test_decode_word_handles_signed_values():
    assert decode_word(_word(-5, signed=True), 0, signed=True) == -5
    assert decode_word(_word(5), 0) == 5


def test_decode_word_rejects_a_short_response():
    with pytest.raises(RpcError, match="too short"):
        decode_word(b"\x00" * 16, 0)


def test_decode_string_reads_a_dynamic_return():
    assert decode_string(_string("ETH / USD")) == "ETH / USD"


def test_selectors_match_their_signatures():
    """Hardcoded selectors, verified against keccak rather than trusted.

    `eth_utils` is not a dependency of this package — hardcoding three
    argument-free selectors is why we avoid a node library at all. So this
    check runs when a keccak implementation happens to be present and skips
    cleanly when it is not.
    """
    keccak = pytest.importorskip("eth_utils").keccak

    assert SELECTOR_LATEST_ROUND_DATA == "0x" + keccak(text="latestRoundData()")[:4].hex()
    assert SELECTOR_DECIMALS == "0x" + keccak(text="decimals()")[:4].hex()
    assert SELECTOR_DESCRIPTION == "0x" + keccak(text="description()")[:4].hex()
