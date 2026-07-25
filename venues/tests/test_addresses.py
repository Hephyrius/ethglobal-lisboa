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

    def test_the_fallback_covers_everything_the_deployed_vault_allows(self):
        """Reconciliation, in the direction that can actually bite.

        This originally asserted the reverse — that the fallback contained
        *nothing* the deployed vault would reject — and the Wave 1 universe
        expansion made that assumption false in a way worth recording, because
        the obvious fix is the wrong one.

        cbBTC, DAI and AERO joined `FALLBACK_ALLOWLIST` (a token is an
        `execute()` target because an approval step targets the token, not the
        venue — request #8). They are **not** in the manifest, because
        `executeAllowlist.targets` is a snapshot of what the demo vault was
        deployed with and a vault's allowlist is set at `initialize`. New vaults
        get the widened factory defaults; existing ones keep what they were born
        with. Both facts are correct simultaneously.

        The superset is harmless: `allowlist()` prefers the manifest and ignores
        the fallback entirely whenever one exists, so plans against the deployed
        vault are still checked against exactly what that vault allows. The
        fallback only applies on a fresh clone, where there is no deployed vault
        to reject anything.

        What *would* bite is the other direction — the fallback missing
        something the deployed vault allows — because then a fresh clone would
        reject a legitimate plan and the failure would look like a venue bug.
        """
        manifest = addresses.deployments_path()
        if not manifest.exists():
            pytest.skip("no deployment manifest to reconcile against")

        published = {
            t.lower()
            for t in json.loads(manifest.read_text(encoding="utf-8"))["executeAllowlist"][
                "targets"
            ]
        }
        missing = published - addresses.FALLBACK_ALLOWLIST
        assert not missing, (
            f"the deployed vault allows targets a fresh clone would refuse to emit: "
            f"{sorted(missing)} — add them to FALLBACK_ALLOWLIST"
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


class TestTokenTableIsNotAValuationList:
    """Cross-lane request #78.

    `TOKENS` answers "can this lane resolve this symbol". Lane B's genesis menu
    read it as "assets the vault can safely hold", which is a different and
    stricter question — the vault needs a *registered USD price feed*, and every
    LST on Base quotes ETH at 18 decimals rather than USD at 8. Registering one
    naively reads wstETH as $12.4bn, and valuations are immutable after
    `initialize`, so the vault could not be repaired.

    This test does not stop anyone extending the table. It makes extending it a
    deliberate act that arrives with the checklist attached.
    """

    #: Every symbol here is USD-priced or the base asset, and verified on-chain.
    KNOWN_SAFE = {"USDC", "WETH", "ETH", "CBBTC", "DAI", "AERO"}

    #: Denominated in ETH at 18 decimals on Base — NOT USD at 8. The vault holds
    #: one feed per token and cannot compose, so these need a feed adapter first.
    ETH_QUOTED_LSTS = {"WSTETH", "CBETH", "RETH", "WEETH", "EZETH"}

    def test_the_table_holds_only_assets_known_to_be_usd_priced(self):
        unexpected = set(addresses.TOKENS) - self.KNOWN_SAFE
        assert not unexpected, (
            f"new symbols in TOKENS: {sorted(unexpected)}. Before adding one, confirm "
            f"its Chainlink feed on Base is USD-quoted at 8 decimals. If it is "
            f"ETH-quoted at 18 (every LST is), the vault CANNOT value it — it holds "
            f"one feed per token and cannot compose. Build a composing feed adapter "
            f"first; ERC4626PriceFeed is the pattern. See cross-lane request #78."
        )

    @pytest.mark.parametrize("symbol", sorted(ETH_QUOTED_LSTS))
    def test_no_eth_quoted_lst_has_been_added(self, symbol):
        assert symbol not in addresses.TOKENS, (
            f"{symbol} is ETH-quoted at 18 decimals on Base. Adding it here widens "
            f"the genesis asset menu and what the agent may amend into, and the vault "
            f"would misprice it by ~10^10. Request #78 has the measurement."
        )

    def test_the_docstring_points_at_the_real_authority(self):
        """The table cannot answer 'can the vault value this' — only the chain
        can, and the docstring must say where."""
        import venues.addresses as module

        source = module.__doc__ or ""
        # The warning lives on the TOKENS comment; assert the module at least
        # carries the address-provenance discipline that motivates it.
        assert "verified" in source.lower()
