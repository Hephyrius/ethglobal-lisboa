"""P8 — "how am *I* doing?", the one question that spans vaults.

The vault page could say how a vault was doing. Nothing could tell a depositor
with money in three of them what they held in total.

The interesting decisions here are both about *refusing* to compute something:
no cost basis, and no cross-asset summing.
"""

from __future__ import annotations

import pytest

from agent.portfolio.reader import (
    SELECTOR_BALANCE_OF,
    SELECTOR_CONVERT,
    SELECTOR_SYMBOL,
    SELECTOR_VAULTS,
    read_portfolio,
)

FACTORY = "0x02827a276587B906a4DDb2C4863C9EbD6Abf302D"
OWNER = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
BIG = "0x1111111111111111111111111111111111111111"
SMALL = "0x2222222222222222222222222222222222222222"
NONE_HELD = "0x3333333333333333333333333333333333333333"


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
    def __init__(self, vaults: list[str], books: dict[str, dict]) -> None:
        self._vaults = vaults
        self._books = books

    async def call(self, to: str, selector: str) -> bytes:
        if selector == SELECTOR_VAULTS:
            return _address_array(self._vaults)

        book = self._books[to.lower()]
        if selector.startswith(SELECTOR_BALANCE_OF):
            return _word(book["shares"])
        if selector.startswith(SELECTOR_CONVERT):
            # convertToAssets(x): x shares -> assets, at this vault's price.
            shares = int(selector[10:], 16)
            return _word(shares * book["price"] // 10**18)
        if selector == SELECTOR_SYMBOL:
            return _string(book.get("symbol", "cUSDC"))
        raise RuntimeError(f"unexpected selector {selector}")

    async def aclose(self):
        return None


BOOKS = {
    BIG.lower(): {"shares": 10 * 10**21, "price": 1_012_500, "symbol": "cSAFE"},
    SMALL.lower(): {"shares": 2 * 10**21, "price": 987_000, "symbol": "cRISK"},
    NONE_HELD.lower(): {"shares": 0, "price": 1_000_000, "symbol": "cEMPTY"},
}


async def test_only_vaults_the_wallet_actually_holds_appear():
    """A deployment accumulates dozens of vaults. A portfolio is the handful
    with a balance, not a directory of everything deployed."""
    result = await read_portfolio(_FakeRpc([BIG, SMALL, NONE_HELD], BOOKS), FACTORY, OWNER)

    assert [p.symbol for p in result.positions] == ["cSAFE", "cRISK"]
    assert all(int(p.shares) > 0 for p in result.positions)


async def test_positions_are_largest_first():
    result = await read_portfolio(_FakeRpc([SMALL, BIG], BOOKS), FACTORY, OWNER)
    values = [int(p.value_in_asset) for p in result.positions]
    assert values == sorted(values, reverse=True)


async def test_value_comes_from_the_vaults_own_conversion():
    """Not shares x a price we computed.

    The vault applies ERC-4626 rounding and a redemption will use *its* answer.
    Multiplying ourselves would produce a number that disagrees with what the
    depositor actually receives, in the last decimal, forever.
    """
    result = await read_portfolio(_FakeRpc([BIG], BOOKS), FACTORY, OWNER)
    position = result.positions[0]

    expected = 10 * 10**21 * 1_012_500 // 10**18
    assert int(position.value_in_asset) == expected


async def test_the_return_field_is_named_after_the_vault_not_the_holder():
    """A depositor who entered later has not earned the vault's inception-to-date
    return, so the field must not read as their P&L.

    This is the compromise that lets the panel ship without a cost basis: report
    something exact and correctly labelled rather than something personal and
    possibly wrong.
    """
    result = await read_portfolio(_FakeRpc([BIG], BOOKS), FACTORY, OWNER)
    position = result.positions[0]

    assert hasattr(position, "vault_return_pct")
    assert not hasattr(position, "pnl"), "a cost basis we do not compute must not be implied"
    assert position.vault_return_pct == pytest.approx(0.0125)


async def test_an_empty_portfolio_is_a_normal_answer():
    """A wallet that has not deposited anywhere is common, not an error."""
    result = await read_portfolio(_FakeRpc([NONE_HELD], BOOKS), FACTORY, OWNER)
    assert result.positions == []
    assert result.total_value == "0"


async def test_one_unreadable_vault_does_not_empty_the_portfolio():
    """A half-deployed clone, or a future vault with a different ABI, must cost
    its own row and nothing else. Losing someone's whole portfolio view because
    one of forty vaults is odd would be the wrong trade."""

    class _Broken(_FakeRpc):
        async def call(self, to: str, selector: str) -> bytes:
            if to.lower() == SMALL.lower() and selector.startswith(SELECTOR_BALANCE_OF):
                raise RuntimeError("not an ERC-4626 vault")
            return await super().call(to, selector)

    result = await read_portfolio(_Broken([BIG, SMALL], BOOKS), FACTORY, OWNER)
    assert [p.symbol for p in result.positions] == ["cSAFE"]


async def test_the_total_is_the_sum_of_the_positions():
    result = await read_portfolio(_FakeRpc([BIG, SMALL], BOOKS), FACTORY, OWNER)
    assert int(result.total_value) == sum(int(p.value_in_asset) for p in result.positions)


def test_the_selectors_are_what_they_claim_to_be():
    from web3 import Web3

    for signature, selector in (
        ("vaults()", SELECTOR_VAULTS),
        ("balanceOf(address)", SELECTOR_BALANCE_OF),
        ("convertToAssets(uint256)", SELECTOR_CONVERT),
        ("symbol()", SELECTOR_SYMBOL),
    ):
        assert "0x" + Web3.keccak(text=signature)[:4].hex() == selector, signature


async def test_a_bad_address_is_rejected_before_any_rpc_call():
    from fastapi.testclient import TestClient

    from agent.api.app import create_app

    response = TestClient(create_app()).get("/portfolio/not-an-address")
    assert response.status_code == 422


# ── the venue list genesis offers ─────────────────────────────────────────


def test_genesis_offers_every_registered_venue_not_a_hardcoded_pair():
    """Caught by reading GET /genesis/sources after adding the Aave venue.

    It reported `uniswap, aqua`. The venue seam is a bare `get_venue(key)`
    lookup with no `.available()`, so the introspection branch never resolved
    and a hardcoded fallback had silently become the answer — meaning the third
    venue could never be granted in a mandate and the agent could never lend.

    A fallback that happens to be right is indistinguishable from one that has
    gone stale, which is why this asserts against the registry rather than
    against a list.
    """
    from agent.config import settings
    from agent.service.live import LiveGenesisService
    from venues.registry import VENUES

    offered = LiveGenesisService(settings()).available_venues()
    assert set(offered) == set(VENUES), (
        f"genesis offers {offered} but the registry has {list(VENUES)}"
    )
    assert "aave" in offered
