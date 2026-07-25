"""Address integrity.

A wrong address here is a silent revert at demo time, so these are cheap
insurance on the one file every adapter reads.
"""

from __future__ import annotations

import json

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
        assert getattr(addresses, name).lower() in addresses.allowlist()


class TestAllowlistSource:
    """The allowlist is read from Lane A's deployment manifest, not hardcoded
    (their cross-lane request 1). The vault's `allowedTargets()` is mutable, so
    a constant compiled in here would drift and the symptom would be an
    on-chain revert instead of a clear failure."""

    def test_it_is_read_from_lane_as_deployment_manifest(self):
        manifest = addresses.deployments_path()
        if not manifest.exists():
            pytest.skip("no deployment manifest yet — falling back is correct")

        published = {
            t.lower()
            for t in json.loads(manifest.read_text(encoding="utf-8"))["executeAllowlist"][
                "targets"
            ]
        }
        assert addresses.allowlist() == published

    def test_our_fallback_agrees_with_what_lane_a_actually_deployed(self):
        """Reconciliation. The fallback exists for a fresh clone, so it should
        not quietly disagree with the deployed vault — if it does, one of us
        changed an address and the other has not noticed."""
        manifest = addresses.deployments_path()
        if not manifest.exists():
            pytest.skip("no deployment manifest to reconcile against")

        published = {
            t.lower()
            for t in json.loads(manifest.read_text(encoding="utf-8"))["executeAllowlist"][
                "targets"
            ]
        }
        missing = addresses.FALLBACK_ALLOWLIST - published
        assert not missing, (
            f"this lane can emit targets the deployed vault will reject: {sorted(missing)}"
        )

    def test_a_missing_manifest_falls_back_instead_of_failing(self, monkeypatch, tmp_path):
        monkeypatch.setenv(
            addresses.DEPLOYMENTS_ENV_VAR, str(tmp_path / "does-not-exist.json")
        )
        assert addresses.allowlist() == addresses.FALLBACK_ALLOWLIST

    def test_a_malformed_manifest_falls_back_instead_of_failing(
        self, monkeypatch, tmp_path
    ):
        broken = tmp_path / "broken.json"
        broken.write_text("{not json", encoding="utf-8")
        monkeypatch.setenv(addresses.DEPLOYMENTS_ENV_VAR, str(broken))
        assert addresses.allowlist() == addresses.FALLBACK_ALLOWLIST

    def test_a_manifest_narrows_the_allowlist(self, monkeypatch, tmp_path):
        """A guardian narrowing the on-chain list must narrow ours too, or we
        keep emitting plans that revert."""
        narrow = tmp_path / "narrow.json"
        narrow.write_text(
            json.dumps({"executeAllowlist": {"targets": [addresses.AQUA]}}),
            encoding="utf-8",
        )
        monkeypatch.setenv(addresses.DEPLOYMENTS_ENV_VAR, str(narrow))
        assert addresses.allowlist() == {addresses.AQUA.lower()}


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
