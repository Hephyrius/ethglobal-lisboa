"""`MorphoVenue` — supplying into MetaMorpho, implementing the frozen `Venue` port.

The fourth venue, and the second place idle capital can earn. It reuses
`SupplyIntent`/`WithdrawIntent` unchanged — those shapes were designed to be
venue-agnostic and this is the test of that claim.

## Against the other three

**Uniswap rotates what the vault holds. Aqua earns fees on it. Aave and Morpho
earn interest on it.** Aave and Morpho differ in where the yield comes from: an
Aave supply earns the pool's utilisation-driven rate directly, while a
MetaMorpho vault is *curated* — a third party allocates across Morpho Blue
markets, so the vault is taking that curator's risk selection as well as the
underlying markets'. Worth saying out loud in a project about curation: here we
are the depositor into someone else's curated vault.

## Custody, and why this one needed a new contract when Aave did not

The underlying moves and the vault holds an ERC-4626 share. That is the same
*shape* as Aave's aToken, with one decisive difference: **an aToken rebases 1:1,
a 4626 share appreciates.** The underlying's Chainlink feed is therefore correct
for an aToken and *wrong* for this — measured on Base, wrong by 760 bps today
and worse every block.

So this venue is gated on `ERC4626PriceFeed` (this lane's own Foundry project)
being deployed and registered as the share token's valuation. Until then
`_assert_valued` refuses to build a plan, because supplying into a token the
vault cannot value makes `totalAssets()` fall by the amount supplied and nothing
errors.
"""

from __future__ import annotations

import logging
from typing import Final

from curator_schema.models import (
    ExecutionPlan,
    ExecutionStep,
    SupplyIntent,
    VaultState,
    VenueIntent,
    WithdrawIntent,
)

from .. import addresses
from ..abi import ERC20_APPROVE, encode_call
from ..errors import PlanValidationError, UnsupportedIntentError, VenueError
from .markets import VAULTS, MetaMorphoVault, deposit, redeem, vault_for_asset, withdraw

VENUE_KEY: Final[str] = "morpho"

log = logging.getLogger(__name__)


class MorphoVenue:
    """Implements `curator_schema.ports.Venue` for MetaMorpho vaults on Base."""

    key: str = VENUE_KEY

    def __init__(self, vault_key: str | None = None) -> None:
        #: Which MetaMorpho vault this adapter supplies into. Injectable so a
        #: mandate could eventually name one; defaults to the deepest book.
        self._vault_key = vault_key

    async def plan(self, intent: VenueIntent, vault: VaultState) -> ExecutionPlan:
        if isinstance(intent, SupplyIntent):
            return self._plan_supply(intent, vault)
        if isinstance(intent, WithdrawIntent):
            return self._plan_withdraw(intent, vault)
        raise UnsupportedIntentError(
            f"MorphoVenue serves supply/withdraw intents; got {type(intent).__name__}. "
            f"Route swaps to UniswapVenue and ship/dock to AquaVenue."
        )

    # ── supply ────────────────────────────────────────────────────────────

    def _plan_supply(self, intent: SupplyIntent, vault: VaultState) -> ExecutionPlan:
        target = self._target(intent.asset)
        amount = self._amount_to_supply(intent, target, vault)
        if amount <= 0:
            raise VenueError(
                f"nothing to supply: the vault holds no {intent.asset}, or the requested "
                f"fraction rounds to zero"
            )

        self._assert_valued(target)

        symbol = intent.asset.upper()
        human = self._human(amount, target.asset)

        plan = ExecutionPlan(
            venue=VENUE_KEY,
            steps=[
                # Re-emitted every plan, as with the other venues: a redundant
                # approve costs gas and always succeeds, a missing one reverts
                # the whole atomic batch.
                ExecutionStep(
                    target=target.asset,
                    value="0",
                    calldata=encode_call(ERC20_APPROVE, target.address, amount),
                    why=f"approve {target.description} to take {human} {symbol}",
                ),
                ExecutionStep(
                    target=target.address,
                    value="0",
                    # receiver is the VAULT — the shares must land with the
                    # custodian, not with the agent that authorised the call.
                    calldata=deposit(amount, vault.address),
                    why=f"deposit {human} {symbol} into {target.description}",
                ),
            ],
            expected_effect=(
                f"supply {human} {symbol} into {target.description} via Morpho; the vault "
                f"receives ERC-4626 shares it holds itself and earns the curated rate"
            ),
            # Not a trade: no route, no counterparty, no price impact.
            expected_slippage_bps=0,
        )
        self._assert_targets(plan)
        return plan

    # ── withdraw ──────────────────────────────────────────────────────────

    def _plan_withdraw(self, intent: WithdrawIntent, vault: VaultState) -> ExecutionPlan:
        target = self._target(intent.asset)
        symbol = intent.asset.upper()

        if intent.amount is not None:
            amount = int(intent.amount)
            calldata = withdraw(amount, vault.address, vault.address)
            human = f"{self._human(amount, target.asset)} of"
        else:
            # Full exit must be expressed in SHARES, not assets. ERC-4626 has no
            # uint256.max sentinel, and an asset figure computed off-chain is
            # already stale when the transaction mines — leaving dust behind or
            # reverting. Shares do not accrue; their value does.
            shares = self._share_balance(target, vault)
            calldata = redeem(shares, vault.address, vault.address)
            human = "all of"

        plan = ExecutionPlan(
            venue=VENUE_KEY,
            steps=[
                ExecutionStep(
                    target=target.address,
                    value="0",
                    calldata=calldata,
                    why=f"redeem {human} the vault's {target.description} position",
                )
            ],
            expected_effect=f"withdraw {human} the vault's {symbol} from {target.description}",
            expected_slippage_bps=0,
        )
        self._assert_targets(plan)
        return plan

    # ── checks ────────────────────────────────────────────────────────────

    def _target(self, asset: str) -> MetaMorphoVault:
        if self._vault_key is not None:
            try:
                return VAULTS[self._vault_key]
            except KeyError:
                raise VenueError(
                    f"unknown MetaMorpho vault {self._vault_key!r}; "
                    f"known: {sorted(VAULTS)}"
                ) from None

        target = vault_for_asset(asset)
        if target is None:
            raise VenueError(
                f"no MetaMorpho vault is configured for {asset} on Base. Add one to "
                f"venues/morpho/markets.py after confirming on-chain that asset() is "
                f"the token you think it is."
            )
        return target

    def _amount_to_supply(
        self, intent: SupplyIntent, target: MetaMorphoVault, vault: VaultState
    ) -> int:
        if intent.amount is not None:
            return int(intent.amount)
        if intent.pct_of_holdings is None:
            raise VenueError(
                "a supply needs either `amount` or `pct_of_holdings`; neither was set"
            )

        held = next(
            (h for h in vault.holdings if h.token.lower() == target.asset.lower()), None
        )
        if held is None:
            raise VenueError(
                f"the vault holds no {intent.asset}, so there is no balance to take "
                f"{intent.pct_of_holdings:.0%} of"
            )
        return int(int(held.balance) * intent.pct_of_holdings)

    @staticmethod
    def _share_balance(target: MetaMorphoVault, vault: VaultState) -> int:
        held = next(
            (h for h in vault.holdings if h.token.lower() == target.address.lower()), None
        )
        if held is None or int(held.balance) <= 0:
            raise VenueError(
                f"the vault holds no {target.description} shares, so there is nothing to "
                f"redeem. A full exit is expressed in shares; populate "
                f"VaultState.holdings with the share balance."
            )
        return int(held.balance)

    @staticmethod
    def _assert_valued(target: MetaMorphoVault) -> None:
        """Refuse to supply into a vault that cannot value the share it gets back.

        The same guard Aave carries, and here it is doing more work: an aToken
        can be valued by the underlying's existing Chainlink feed, whereas a
        MetaMorpho share needs `ERC4626PriceFeed` deployed and registered. Until
        that lands the correct behaviour is to refuse loudly, because the failure
        it prevents is a silent share-price collapse.
        """
        if target.address.lower() not in addresses.allowlist():
            raise PlanValidationError(
                f"this deployment cannot value {target.description} shares "
                f"({target.address}): the share token is not in the deployment "
                f"manifest's allowlist, so no vault here has a valuation registered "
                f"for it. Supplying anyway would make totalAssets() drop by the amount "
                f"supplied and collapse the share price. Fix: deploy "
                f"ERC4626PriceFeed(vault={target.address}, assetFeed={target.asset_feed}) "
                f"from venues/aqua/solidity, register it with "
                f"VaultFactory.setDefaultValuation, then create a NEW vault — per-vault "
                f"valuations are immutable."
            )

    @staticmethod
    def _assert_targets(plan: ExecutionPlan) -> None:
        allowed = addresses.allowlist()
        for index, step in enumerate(plan.steps):
            if step.target.lower() not in allowed:
                raise PlanValidationError(
                    f"step {index} targets {step.target}, which is not on the vault "
                    f"allowlist. The MetaMorpho vault and its share token both need "
                    f"registering before this venue can be used."
                )

    @staticmethod
    def _human(amount: int, asset: str) -> str:
        decimals = addresses.decimals_for(asset)
        if decimals is None:
            return str(amount)
        return f"{amount / 10**decimals:,.6f}".rstrip("0").rstrip(".")

    async def aclose(self) -> None:
        """Nothing held open — every plan here is static calldata."""
        return None
