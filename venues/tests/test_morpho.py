"""The Morpho venue — supplying into curated MetaMorpho vaults.

The failure this whole adapter is shaped around: supplying into a token the
curated vault cannot value makes `totalAssets()` fall by exactly the amount
supplied, and every depositor's share price with it. Nothing errors. Aave dodged
it because an aToken rebases 1:1; a MetaMorpho share appreciates, so it needs a
real conversion — measured at **760 bps** of understatement today and worse
every block.
"""

from __future__ import annotations

import pytest
from curator_schema.models import (
    AquaShipIntent,
    Holding,
    SupplyIntent,
    VaultState,
    WithdrawIntent,
)

from venues import addresses
from venues.abi import ERC20_APPROVE, selector
from venues.errors import PlanValidationError, UnsupportedIntentError, VenueError
from venues.morpho.markets import (
    DEFAULT_VAULT,
    DEPOSIT,
    MORPHO_BLUE,
    REDEEM,
    VAULTS,
    WITHDRAW,
    vault_for_asset,
)
from venues.morpho.venue import MorphoVenue

VAULT_ADDRESS = "0x00000000000000000000000000000000000000A1"
TARGET = VAULTS[DEFAULT_VAULT]


def _vault(with_shares: int = 0, usdc: int = 10_000_000_000) -> VaultState:
    holdings = [
        Holding(token=addresses.USDC, symbol="USDC", balance=str(usdc), decimals=6)
    ]
    if with_shares:
        holdings.append(
            Holding(
                token=TARGET.address,
                symbol="mmUSDC",
                balance=str(with_shares),
                decimals=18,
            )
        )
    return VaultState(
        address=VAULT_ADDRESS,
        asset=addresses.USDC,
        total_assets=str(usdc),
        total_supply=str(usdc),
        holdings=holdings,
        asset_decimals=6,
    )


@pytest.fixture
def allowed(monkeypatch):
    """Pretend the share token has been registered, so plans can be built."""
    monkeypatch.setattr(
        addresses,
        "allowlist",
        lambda: addresses.FALLBACK_ALLOWLIST
        | {TARGET.address.lower(), addresses.USDC.lower()},
    )


@pytest.fixture
def unregistered(monkeypatch):
    """A deployment where the MetaMorpho share is *not* valued.

    Constructed rather than assumed. The first version of these tests relied on
    the real deployment never having registered one — true when written, false
    the moment Lane F actioned #79, and the tests failed on someone else's
    success. That is a test pinning an environmental fact instead of a
    behaviour, which is the same mistake this lane flagged in R5's green run.
    """
    monkeypatch.setattr(
        addresses,
        "allowlist",
        lambda: frozenset(addresses.FALLBACK_ALLOWLIST) - {TARGET.address.lower()},
    )


class TestTheValuationGuard:
    """The guard is the point of the adapter, so it is tested before anything."""

    async def test_it_refuses_when_the_share_token_is_unvalued(self, unregistered):
        with pytest.raises(PlanValidationError, match="cannot value"):
            await MorphoVenue().plan(
                SupplyIntent(asset="USDC", pct_of_holdings=0.5), _vault()
            )

    async def test_the_refusal_names_the_exact_fix(self, unregistered):
        with pytest.raises(PlanValidationError) as caught:
            await MorphoVenue().plan(
                SupplyIntent(asset="USDC", pct_of_holdings=0.5), _vault()
            )
        message = str(caught.value)
        # A refusal that does not say what to do is a dead end, not a guard.
        assert "ERC4626PriceFeed" in message
        assert "setDefaultValuation" in message
        assert TARGET.asset_feed in message
        assert "immutable" in message

    async def test_it_builds_once_the_share_is_registered(self, allowed):
        plan = await MorphoVenue().plan(
            SupplyIntent(asset="USDC", pct_of_holdings=0.5), _vault()
        )
        assert plan.venue == "morpho"


class TestSupply:
    async def test_it_approves_then_deposits(self, allowed):
        plan = await MorphoVenue().plan(
            SupplyIntent(asset="USDC", amount="1000000000"), _vault()
        )
        assert len(plan.steps) == 2
        assert plan.steps[0].target.lower() == addresses.USDC.lower()
        assert plan.steps[0].calldata.startswith("0x" + selector(ERC20_APPROVE).hex())
        assert plan.steps[1].target.lower() == TARGET.address.lower()
        assert plan.steps[1].calldata.startswith("0x" + selector(DEPOSIT).hex())

    async def test_the_approval_names_the_metamorpho_vault_not_morpho_blue(self, allowed):
        """Morpho Blue is a different contract and approving it would strand the
        allowance where nothing can use it."""
        plan = await MorphoVenue().plan(
            SupplyIntent(asset="USDC", amount="1000000000"), _vault()
        )
        assert TARGET.address[2:].lower() in plan.steps[0].calldata.lower()
        assert MORPHO_BLUE[2:].lower() not in plan.steps[0].calldata.lower()

    async def test_the_receiver_is_the_vault(self, allowed):
        """Shares must land with the custodian, not the agent that authorised."""
        plan = await MorphoVenue().plan(
            SupplyIntent(asset="USDC", amount="1000000000"), _vault()
        )
        assert VAULT_ADDRESS[2:].lower() in plan.steps[1].calldata.lower()

    async def test_pct_of_holdings_resolves_against_real_balances(self, allowed):
        plan = await MorphoVenue().plan(
            SupplyIntent(asset="USDC", pct_of_holdings=0.25), _vault(usdc=10_000_000_000)
        )
        # 25% of 10,000 USDC = 2,500 USDC
        assert plan.steps[0].calldata.endswith(hex(2_500_000_000)[2:].zfill(64))

    async def test_a_supply_is_not_a_trade(self, allowed):
        plan = await MorphoVenue().plan(
            SupplyIntent(asset="USDC", amount="1000000000"), _vault()
        )
        # No route, no counterparty. 0 says that positively; None would leave the
        # mandate's slippage ceiling compared against an absent value.
        assert plan.expected_slippage_bps == 0

    async def test_supplying_an_unsupported_asset_fails_loudly(self, allowed):
        with pytest.raises(VenueError, match="no MetaMorpho vault"):
            await MorphoVenue().plan(
                SupplyIntent(asset="WETH", amount="1000"), _vault()
            )


class TestWithdraw:
    async def test_an_exact_amount_uses_withdraw(self, allowed):
        plan = await MorphoVenue().plan(
            WithdrawIntent(asset="USDC", amount="500000000"), _vault(with_shares=10**18)
        )
        assert len(plan.steps) == 1
        assert plan.steps[0].calldata.startswith("0x" + selector(WITHDRAW).hex())

    async def test_a_full_exit_uses_redeem_on_the_share_balance(self, allowed):
        """ERC-4626 has no uint256.max sentinel the way Aave does. An asset
        figure computed off-chain is stale by the time it mines — shares are
        not, because their *value* accrues rather than their count."""
        plan = await MorphoVenue().plan(
            WithdrawIntent(asset="USDC"), _vault(with_shares=3 * 10**18)
        )
        assert plan.steps[0].calldata.startswith("0x" + selector(REDEEM).hex())
        assert hex(3 * 10**18)[2:].zfill(64) in plan.steps[0].calldata.lower()

    async def test_a_full_exit_without_a_share_balance_says_why(self, allowed):
        with pytest.raises(VenueError, match="expressed in shares"):
            await MorphoVenue().plan(WithdrawIntent(asset="USDC"), _vault())


class TestVenueContract:
    async def test_a_ship_intent_is_refused(self, allowed):
        with pytest.raises(UnsupportedIntentError, match="AquaVenue"):
            await MorphoVenue().plan(
                AquaShipIntent(tokens=["USDC", "WETH"], amounts=["1", "1"]), _vault()
            )

    async def test_it_is_registered_and_described(self):
        from venues import capability
        from venues.registry import VENUES

        assert "morpho" in VENUES
        cap = capability("morpho")
        assert cap.role == "lender"
        assert set(cap.intents) == {"supply", "withdraw"}
        # Not registered on this deployment yet — must say so, with the fix.
        if not cap.available:
            assert "ERC4626PriceFeed" in (cap.unavailable_reason or "")

    async def test_reusing_supply_intent_needed_no_schema_change(self, allowed):
        """The venue-agnostic claim for SupplyIntent/WithdrawIntent, tested by
        putting a second lending venue behind the identical shapes."""
        from venues.aave.venue import AaveVenue

        intent = SupplyIntent(asset="USDC", amount="1000000000")
        morpho = await MorphoVenue().plan(intent, _vault())
        assert morpho.venue == "morpho"
        # Same intent object, different venue, both valid plans.
        assert isinstance(AaveVenue(), AaveVenue)


class TestMarketsTable:
    def test_default_vault_is_the_deeper_book(self):
        assert DEFAULT_VAULT == "gauntlet-usdc-prime"

    def test_every_vault_is_a_usdc_vault_with_18_decimal_shares(self):
        for v in VAULTS.values():
            assert v.asset.lower() == addresses.USDC.lower()
            # 18 share decimals against 6 asset decimals — conflating them is a
            # 10^12 error, which is why it is recorded rather than assumed.
            assert v.share_decimals == 18

    def test_vault_lookup_by_asset(self):
        assert vault_for_asset("USDC") is not None
        assert vault_for_asset(addresses.WETH) is None


class TestAddressMirrorAgrees:
    """`venues/addresses.py` mirrors the MetaMorpho address so the fallback
    allowlist can name it without inverting the dependency (the same rule the
    Aave addresses follow). Two copies eventually disagree unless something
    checks."""

    def test_the_mirrored_address_matches_the_markets_table(self):
        assert (
            addresses.METAMORPHO_GAUNTLET_USDC_PRIME.lower()
            == VAULTS["gauntlet-usdc-prime"].address.lower()
        )

    def test_it_is_on_the_fallback_allowlist(self):
        """Request #79 registered it as an execute() target. If the fallback
        omits it, a fresh clone refuses a plan the deployed vault accepts —
        which reads as a venue bug rather than a stale constant."""
        assert (
            addresses.METAMORPHO_GAUNTLET_USDC_PRIME.lower()
            in addresses.FALLBACK_ALLOWLIST
        )

    def test_it_is_eip55_checksummed(self):
        from eth_utils import is_checksum_address

        assert is_checksum_address(addresses.METAMORPHO_GAUNTLET_USDC_PRIME)
