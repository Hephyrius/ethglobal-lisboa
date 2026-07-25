"""P4 — supplying to Aave, and the two ways it could silently go wrong.

The gap this venue closes is measurable: across the first 36 journalled ticks
the `aave` data source contributed 204 facts about lending yields and no intent
type could act on any of them. The agent read "Aave pays 3.5% on USDC" and its
only possible response was a Uniswap swap between USDC and WETH.

The two failures worth testing for are both silent:

  * `onBehalfOf` pointing anywhere but the vault hands the position to a party
    that is not the custodian, on a call that succeeds;
  * supplying into a vault that cannot value the aToken makes `totalAssets()`
    fall by the amount supplied and collapses the share price, with no error.
"""

from __future__ import annotations

import pytest
from curator_schema.models import Holding, SupplyIntent, SwapIntent, VaultState, WithdrawIntent

from venues import addresses
from venues.aave.markets import ATOKENS, POOL, SUPPLY, WITHDRAW
from venues.aave.venue import UINT256_MAX, AaveVenue
from venues.abi import selector
from venues.errors import PlanValidationError, UnsupportedIntentError, VenueError

VAULT = "0x0E2c0e50E67B96C9C401C94e111a3DBD00DEB5d1"
ABAS_USDC = ATOKENS[addresses.USDC.lower()]


def _vault(usdc: int = 10_000_000_000, weth: int = 0) -> VaultState:
    holdings = [
        Holding(
            token=addresses.USDC,
            symbol="USDC",
            balance=str(usdc),
            decimals=6,
            value_in_asset=str(usdc),
        )
    ]
    if weth:
        holdings.append(
            Holding(
                token=addresses.WETH,
                symbol="WETH",
                balance=str(weth),
                decimals=18,
                value_in_asset=str(weth // 10**12),
            )
        )
    return VaultState(
        address=VAULT,
        asset=addresses.USDC,
        total_assets=str(usdc + (weth // 10**12)),
        total_supply="10000000000000000000000",
        asset_decimals=6,
        holdings=holdings,
    )


def _hex_word(calldata: str, index: int) -> str:
    """The `index`-th 32-byte word after the selector, as lowercase hex."""
    body = calldata[10:]
    return body[index * 64 : (index + 1) * 64]


def _address_arg(calldata: str, index: int) -> str:
    return "0x" + _hex_word(calldata, index)[24:]


def _uint_arg(calldata: str, index: int) -> int:
    return int(_hex_word(calldata, index), 16)


# ── supply ────────────────────────────────────────────────────────────────


async def test_a_supply_approves_the_pool_then_calls_supply():
    plan = await AaveVenue().plan(
        SupplyIntent(asset="USDC", pct_of_holdings=0.5), _vault()
    )

    assert plan.venue == "aave"
    assert len(plan.steps) == 2

    approve, supply = plan.steps
    assert approve.target.lower() == addresses.USDC.lower()
    assert _address_arg(approve.calldata, 0).lower() == POOL.lower()

    assert supply.target.lower() == POOL.lower()
    assert supply.calldata.startswith("0x" + selector(SUPPLY).hex())


async def test_on_behalf_of_is_always_the_vault():
    """The whole trust model in one argument.

    Aave credits the aToken to `onBehalfOf`. Anything but the vault hands the
    position to a party that is not the custodian — and the transaction
    succeeds, so nothing anywhere would report it.
    """
    plan = await AaveVenue().plan(SupplyIntent(asset="USDC", amount="1000000"), _vault())
    supply = plan.steps[1]

    assert _address_arg(supply.calldata, 0).lower() == addresses.USDC.lower(), "asset"
    assert _uint_arg(supply.calldata, 1) == 1_000_000, "amount"
    assert _address_arg(supply.calldata, 2).lower() == VAULT.lower(), "onBehalfOf"
    assert _uint_arg(supply.calldata, 3) == 0, "referralCode"


async def test_a_percentage_is_taken_of_the_vaults_actual_balance():
    plan = await AaveVenue().plan(
        SupplyIntent(asset="USDC", pct_of_holdings=0.25), _vault(usdc=8_000_000_000)
    )
    assert _uint_arg(plan.steps[1].calldata, 1) == 2_000_000_000


async def test_supplying_an_asset_the_vault_does_not_hold_is_refused():
    with pytest.raises(VenueError, match="holds no"):
        await AaveVenue().plan(SupplyIntent(asset="WETH", pct_of_holdings=0.5), _vault())


async def test_a_supply_with_neither_amount_nor_percentage_is_refused():
    with pytest.raises(VenueError, match="amount"):
        await AaveVenue().plan(SupplyIntent(asset="USDC"), _vault())


async def test_a_supply_reports_zero_slippage_rather_than_none():
    """A supply is not a trade — no route, no price impact, no counterparty.

    Zero says that positively. None would leave the mandate's slippage ceiling
    with nothing to compare against, which reads as "unknown" rather than
    "there is none".
    """
    plan = await AaveVenue().plan(SupplyIntent(asset="USDC", amount="1000000"), _vault())
    assert plan.expected_slippage_bps == 0


# ── the valuation trap ────────────────────────────────────────────────────


async def test_supplying_is_refused_when_the_vault_cannot_value_the_atoken(monkeypatch):
    """The failure that would destroy the share price, caught at plan time.

    `totalAssets()` counts the base asset plus *registered* valued tokens. A
    vault that does not know `aBasUSDC` sees its worth fall by exactly the
    amount supplied — every depositor's share price drops and nothing errors.

    Valuations are immutable after `initialize`, so this is a property of when
    the vault was created. Vaults minted before `expand-universe.sh` ran
    genuinely cannot lend, and saying so loudly is the only correct answer.
    """
    narrow = frozenset({addresses.USDC.lower(), POOL.lower()})
    monkeypatch.setattr(addresses, "allowlist", lambda: narrow)

    with pytest.raises(PlanValidationError, match="collapse the share"):
        await AaveVenue().plan(SupplyIntent(asset="USDC", amount="1000000"), _vault())


async def test_an_asset_with_no_recorded_atoken_is_refused_by_name():
    with pytest.raises(VenueError, match="no Aave aToken"):
        await AaveVenue().plan(SupplyIntent(asset="AERO", amount="1000"), _vault())


# ── withdraw ──────────────────────────────────────────────────────────────


async def test_a_full_withdrawal_uses_the_max_sentinel():
    """An aToken balance grows every block.

    Any concrete amount computed off-chain is already stale by the time the
    transaction mines: asking for the exact balance leaves dust, asking for a
    hair more reverts. `type(uint256).max` makes a full exit exact.
    """
    plan = await AaveVenue().plan(WithdrawIntent(asset="USDC"), _vault())

    assert len(plan.steps) == 1
    step = plan.steps[0]
    assert step.target.lower() == POOL.lower()
    assert step.calldata.startswith("0x" + selector(WITHDRAW).hex())
    assert _uint_arg(step.calldata, 1) == UINT256_MAX


async def test_a_withdrawal_returns_the_asset_to_the_vault():
    plan = await AaveVenue().plan(WithdrawIntent(asset="USDC", amount="500000"), _vault())
    step = plan.steps[0]

    assert _uint_arg(step.calldata, 1) == 500_000
    assert _address_arg(step.calldata, 2).lower() == VAULT.lower(), "to"


# ── routing ───────────────────────────────────────────────────────────────


async def test_a_swap_intent_is_refused_with_the_right_venue_named():
    with pytest.raises(UnsupportedIntentError, match="UniswapVenue"):
        await AaveVenue().plan(
            SwapIntent(token_in="USDC", token_out="WETH", pct_of_holdings=0.5), _vault()
        )


def test_the_registry_resolves_aave():
    from venues.registry import VENUES, get_venue

    assert "aave" in VENUES
    assert get_venue("aave").key == "aave"


def test_the_atoken_is_on_the_allowlist_so_a_new_vault_can_hold_it():
    """Reconciliation against what `expand-universe.sh` registered.

    If this fails, either the script has not been run against this deployment or
    the aToken address changed — and every supply would be refused at plan time
    with the share-price warning, which is correct but would look like a bug.
    """
    assert ABAS_USDC.lower() in addresses.allowlist(), (
        "aBasUSDC is not an allowed execute() target — run ./scripts/expand-universe.sh"
    )


def test_the_two_address_tables_agree():
    """`addresses.py` mirrors the Aave addresses so the fallback allowlist can
    name them without importing a venue submodule. Two copies, one truth."""
    from venues.aave import markets

    assert markets.POOL == addresses.AAVE_V3_POOL
    assert markets.ATOKENS[addresses.USDC.lower()] == addresses.ABAS_USDC
    assert markets.ATOKENS[addresses.WETH.lower()] == addresses.ABAS_WETH
