"""Address integrity.

A wrong address here is a silent revert at demo time, so these are cheap
insurance on the one file every adapter reads.
"""

from __future__ import annotations

import pytest
from eth_utils import is_checksum_address

from venues import addresses
from venues.addresses import UnknownTokenError, resolve_token

ADDRESS_CONSTANTS = [
    "AQUA",
    "SWAPVM",
    "UNIVERSAL_ROUTER",
    "UNIVERSAL_ROUTER_LEGACY",
    "PERMIT2",
    "USDC",
    "WETH",
]


@pytest.mark.parametrize("name", ADDRESS_CONSTANTS)
def test_every_address_has_a_valid_eip55_checksum(name: str):
    """Regression guard. The master plan lists the 1inch addresses in lowercase;
    hand-casing them produced two invalid checksums that Python accepted happily
    (comparisons here are case-insensitive) and solc rejected outright. Anything
    doing strict EIP-55 validation — web3.py, a wallet, Lane E — would have
    choked on an address this lane published as correct."""
    value = getattr(addresses, name)
    assert is_checksum_address(value), f"{name} = {value} is not EIP-55 checksummed"


def test_the_two_routers_are_actually_different():
    """Cross-lane request 7 exists because the golden fixture's router is not
    the one the API returns. If these ever collapse to one value, that request
    is obsolete — and this test is how we would notice."""
    assert (
        addresses.UNIVERSAL_ROUTER.lower() != addresses.UNIVERSAL_ROUTER_LEGACY.lower()
    )


def test_allowlist_covers_every_target_an_adapter_can_emit():
    for name in ADDRESS_CONSTANTS:
        assert getattr(addresses, name).lower() in addresses.EXPECTED_ALLOWLIST


def test_weth_sorts_below_usdc_on_base():
    """MakerTraitsLib requires tokenA < tokenB, and this ordering reads
    backwards. The Solidity builder sorts, but the invariant is worth pinning
    somewhere a Python reader will see it."""
    assert int(addresses.WETH, 16) < int(addresses.USDC, 16)


class TestTokenResolution:
    @pytest.mark.parametrize(
        ("symbol", "expected"),
        [("USDC", addresses.USDC), ("weth", addresses.WETH), ("ETH", addresses.WETH)],
    )
    def test_symbols_resolve_case_insensitively(self, symbol, expected):
        assert resolve_token(symbol) == expected

    def test_a_raw_address_passes_through(self):
        raw = "0x1234567890abcdef1234567890ABCDEF12345678"
        assert resolve_token(raw) == raw

    def test_an_unknown_symbol_raises_rather_than_guessing(self):
        # Silently returning None here would route a swap to address zero.
        with pytest.raises(UnknownTokenError, match="cannot resolve token"):
            resolve_token("NOTATOKEN")

    def test_decimals_are_known_for_the_supported_tokens(self):
        assert addresses.decimals_for(addresses.USDC) == 6
        assert addresses.decimals_for(addresses.WETH) == 18

    def test_unknown_decimals_are_none_not_eighteen(self):
        # Defaulting to 18 is how an amount becomes 10^12 times wrong.
        assert addresses.decimals_for("0x" + "11" * 20) is None
