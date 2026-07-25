"""P7 — other vaults as a data source, and the herding risk it creates.

The only source whose facts are about *agents* rather than about markets, and
therefore the only one that could make the vaults on a deployment correlate with
each other. The design decision that keeps that bounded is testable, so it is
tested: **outcomes cross, positions never do.**
"""

from __future__ import annotations

import json

import pytest

from curator_data.config import Settings
from curator_data.sources.peers import (
    MIN_PEER_ASSETS,
    SELECTOR_CONVERT,
    SELECTOR_SYMBOL,
    SELECTOR_TOTAL_ASSETS,
    SELECTOR_TOTAL_SUPPLY,
    SELECTOR_VAULTS,
    PeerVaultSource,
)

FACTORY = "0x02827a276587B906a4DDb2C4863C9EbD6Abf302D"
ME = "0x0E2c0e50E67B96C9C401C94e111a3DBD00DEB5d1"
PEER_A = "0x1111111111111111111111111111111111111111"
PEER_B = "0x2222222222222222222222222222222222222222"
EMPTY = "0x3333333333333333333333333333333333333333"


def _word(value: int) -> bytes:
    return value.to_bytes(32, "big")


def _address_array(addresses: list[str]) -> bytes:
    body = _word(32) + _word(len(addresses))
    for address in addresses:
        body += bytes(12) + bytes.fromhex(address[2:])
    return body


def _string(text: str) -> bytes:
    raw = text.encode()
    return _word(32) + _word(len(raw)) + raw.ljust(32, b"\x00")


class _FakeRpc:
    """Answers the five calls this source makes, per vault."""

    def __init__(self, vaults: list[str], books: dict[str, dict]) -> None:
        self._vaults = vaults
        self._books = books
        self.calls: list[tuple[str, str]] = []

    async def call(self, to: str, selector: str) -> bytes:
        self.calls.append((to.lower(), selector[:10]))
        if selector == SELECTOR_VAULTS:
            return _address_array(self._vaults)

        book = self._books.get(to.lower())
        if book is None:
            raise RuntimeError(f"no such vault {to}")
        if selector == SELECTOR_TOTAL_ASSETS:
            return _word(book["assets"])
        if selector == SELECTOR_TOTAL_SUPPLY:
            return _word(book["supply"])
        if selector.startswith(SELECTOR_CONVERT):
            return _word(book["share_price"])
        if selector == SELECTOR_SYMBOL:
            return _string(book.get("symbol", "cUSDC"))
        raise RuntimeError(f"unexpected selector {selector}")

    async def aclose(self):
        return None


def _source(rpc, *, exclude=ME, performance_dir=None) -> PeerVaultSource:
    return PeerVaultSource(
        Settings(),
        rpc=rpc,
        factory=FACTORY,
        exclude=exclude,
        performance_dir=performance_dir,
    )


BOOKS = {
    ME.lower(): {"assets": 10_000_000_000, "supply": 10**22, "share_price": 999_402},
    PEER_A.lower(): {
        "assets": 25_000_000_000,
        "supply": 10**22,
        "share_price": 1_012_500,
        "symbol": "cSAFE",
    },
    PEER_B.lower(): {
        "assets": 5_000_000_000,
        "supply": 10**22,
        "share_price": 987_000,
        "symbol": "cRISK",
    },
    # Deployed at genesis, never funded. A fork accumulates dozens of these.
    EMPTY.lower(): {"assets": 0, "supply": 0, "share_price": 0},
}


# ── the herding guard ─────────────────────────────────────────────────────


async def test_a_peers_holdings_are_never_reported():
    """The load-bearing design decision.

    Publishing allocations would make herding one prompt away — every vault
    could mirror the leader tick by tick, and the correlation between vaults
    that looked independent goes to one at exactly the wrong moment. Publishing
    *results* makes it an argument the agent has to reason through instead.
    """
    rpc = _FakeRpc([ME, PEER_A, PEER_B], BOOKS)
    facts = await _source(rpc).fetch([])

    assert facts, "expected peer facts"
    for fact in facts:
        assert fact.kind in {"yield", "tvl", "volatility"}, (
            f"{fact.kind} could describe a position; peers must report outcomes only"
        )
        assert fact.subject.token is None, "a per-token fact is a holding in disguise"


async def test_the_vault_being_curated_is_not_its_own_peer():
    rpc = _FakeRpc([ME, PEER_A], BOOKS)
    facts = await _source(rpc).fetch([])
    assert all(ME[:10].lower() not in (f.subject.market or "").lower() for f in facts)


# ── what it reports ───────────────────────────────────────────────────────


async def test_return_since_inception_comes_from_the_share_price():
    """A vault starts at exactly 1.0 by construction, so the deviation from
    1e6 IS the return — no history needed, which is what makes this cheap
    enough to do per-peer inside one tick."""
    rpc = _FakeRpc([ME, PEER_A], BOOKS)
    facts = await _source(rpc).fetch([])

    returns = [f for f in facts if f.kind == "yield"]
    assert len(returns) == 1
    assert returns[0].value == pytest.approx(0.0125), "+1.25% since inception"


async def test_an_unfunded_vault_is_skipped_rather_than_reported_as_flat():
    """A fork accumulates empty vaults from genesis experiments. Each would
    otherwise arrive as a peer with a 0% return, which reads as a rival that is
    flat rather than one that never started."""
    rpc = _FakeRpc([ME, PEER_A, EMPTY], BOOKS)
    facts = await _source(rpc).fetch([])
    assert all("3333" not in (f.subject.market or "") for f in facts)


async def test_a_tiny_vault_is_below_the_floor():
    dust = dict(BOOKS)
    dust[PEER_B.lower()] = {
        "assets": int(MIN_PEER_ASSETS * 10**6) - 1,
        "supply": 10**22,
        "share_price": 1_000_000,
    }
    rpc = _FakeRpc([ME, PEER_B], dust)
    assert await _source(rpc).fetch([]) == []


async def test_no_peers_is_a_remark_not_an_error():
    """A deployment with one vault is a normal state, not a broken feed."""
    source = _source(_FakeRpc([ME], BOOKS))
    assert await source.fetch([]) == []
    assert source.drain_notes() == []
    assert any("track record" in r for r in source.drain_remarks())


async def test_a_vault_that_has_never_traded_is_not_a_peer():
    """Found on the first live run against the fork.

    Seven of the eight peers reported were e2e test vaults holding exactly
    1,000 USDC at exactly 0.000% — identical, uninformative, and they buried the
    one real rival. A vault still sitting at its inception price has no track
    record; it is a deployment artifact, not competition.
    """
    fresh = dict(BOOKS)
    fresh[PEER_A.lower()] = {
        "assets": 1_000_000_000,
        "supply": 10**21,
        "share_price": 1_000_000,  # exactly inception
        "symbol": "e2eUSDC",
    }
    source = _source(_FakeRpc([ME, PEER_A], fresh))
    assert await source.fetch([]) == []


async def test_peer_facts_carry_lower_confidence_than_a_market_fact():
    """A small sample over a short window is a weaker claim than a market
    observation, and `Fact.confidence` is where that belongs."""
    rpc = _FakeRpc([ME, PEER_A], BOOKS)
    facts = await _source(rpc).fetch([])
    assert all(f.confidence is not None and f.confidence < 0.8 for f in facts)


# ── drawdown from the recorded series ─────────────────────────────────────


async def test_drawdown_is_read_from_the_recorded_series(tmp_path):
    series = tmp_path / f"{PEER_A.lower()}.jsonl"
    prices = [1_000_000, 1_050_000, 945_000, 1_012_500]
    series.write_text(
        "\n".join(
            json.dumps({"timestamp": f"2026-07-25T0{i}:00:00Z", "share_price": str(p)})
            for i, p in enumerate(prices)
        ),
        encoding="utf-8",
    )

    rpc = _FakeRpc([ME, PEER_A], BOOKS)
    facts = await _source(rpc, performance_dir=tmp_path).fetch([])

    drawdowns = [f for f in facts if f.kind == "volatility"]
    assert len(drawdowns) == 1
    assert drawdowns[0].value == pytest.approx(0.1), "1.05 -> 0.945 is a 10% fall"


async def test_an_unwatched_peer_gets_no_drawdown_rather_than_zero(tmp_path):
    """Inventing 0% would make the peer we know least about look like the
    safest vault on the deployment."""
    rpc = _FakeRpc([ME, PEER_A], BOOKS)
    facts = await _source(rpc, performance_dir=tmp_path).fetch([])
    assert not [f for f in facts if f.kind == "volatility"]


def test_the_selectors_are_what_they_claim_to_be():
    """A wrong selector does not error — `eth_call` to a missing function on a
    contract with no fallback returns 0x, which reads as 'no such vault'."""
    from web3 import Web3

    for signature, selector in (
        ("vaults()", SELECTOR_VAULTS),
        ("totalAssets()", SELECTOR_TOTAL_ASSETS),
        ("totalSupply()", SELECTOR_TOTAL_SUPPLY),
        ("convertToAssets(uint256)", SELECTOR_CONVERT),
        ("symbol()", SELECTOR_SYMBOL),
    ):
        assert "0x" + Web3.keccak(text=signature)[:4].hex() == selector, signature


def test_the_source_is_registered_and_grantable():
    from curator_data.sources import available_sources

    assert "peers" in available_sources()
