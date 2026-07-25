"""`AaveVenue` — supplying and redeeming, implementing the frozen `Venue` port.

The third venue, and the one that closes the loop the data layer had been
talking to itself about. Across the first 36 ticks the `aave` data source
contributed 204 facts about lending yields, and no intent type could act on any
of them: the agent read "Aave pays 3.5% on USDC" and its only possible response
was a Uniswap swap between USDC and WETH.

Role, against the other two: **Uniswap rotates what the vault holds. Aqua earns
fees on what it already holds. Aave earns interest on what it already holds.**
The last two differ in where the risk sits — an Aqua maker is exposed to being
filled at its own quoted curve, an Aave supplier to utilization and to the
protocol.

## Custody

`supply(asset, amount, onBehalfOf, referralCode)` with `onBehalfOf` **always the
vault**. The vault receives the aToken and holds it; nothing is delegated and no
third party can withdraw. That keeps Pattern 1 intact in substance, though not
in the same way Aqua does — here the underlying really does move to the Aave
pool and the vault holds a claim, rather than the tokens staying put.

## The valuation trap, which would have destroyed the share price

Supply USDC and the vault's USDC balance falls while an `aBasUSDC` balance
appears. `CuratedVault.totalAssets()` counts the base asset plus *registered*
valued tokens — so with aBasUSDC unregistered, `totalAssets()` drops by exactly
the amount supplied and the share price collapses the first time the agent earns
any interest at all.

No new contract was needed. An aToken is a 1:1 rebasing claim on its underlying,
so it is correctly valued by the **underlying's own Chainlink feed**, and
`scripts/expand-universe.sh` registers `aBasUSDC → USDC/USD` and
`aBasWETH → ETH/USD` as factory defaults. Both aToken addresses were confirmed
two ways on the fork: `UNDERLYING_ASSET_ADDRESS()` and
`Pool.getReserveData(asset)[8]`.

**Existing vaults cannot lend.** Valuations are immutable per vault by design,
so only vaults created after that script ran can hold an aToken safely. This
adapter therefore refuses to build a plan whose aToken is not on the target
vault's allowlist — a loud refusal beats a silent share-price collapse.
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
from .markets import ATOKENS, POOL, aave_pool_supply, aave_pool_withdraw

VENUE_KEY: Final[str] = "aave"

#: `type(uint256).max` — how Aave expresses "withdraw everything".
#:
#: Load-bearing rather than a convenience. An aToken balance grows every block,
#: so any concrete amount computed off-chain is already stale by the time the
#: transaction mines: asking for the exact balance leaves dust behind, and
#: asking for a hair more reverts. The sentinel makes a full exit exact.
UINT256_MAX: Final[int] = (1 << 256) - 1

log = logging.getLogger(__name__)


class AaveVenue:
    """Implements `curator_schema.ports.Venue` for Aave v3 on Base."""

    key: str = VENUE_KEY

    async def plan(self, intent: VenueIntent, vault: VaultState) -> ExecutionPlan:
        if isinstance(intent, SupplyIntent):
            return self._plan_supply(intent, vault)
        if isinstance(intent, WithdrawIntent):
            return self._plan_withdraw(intent, vault)
        raise UnsupportedIntentError(
            f"AaveVenue serves supply/withdraw intents; got {type(intent).__name__}. "
            f"Route swaps to UniswapVenue and ship/dock to AquaVenue."
        )

    # ── supply ────────────────────────────────────────────────────────────

    def _plan_supply(self, intent: SupplyIntent, vault: VaultState) -> ExecutionPlan:
        asset = addresses.resolve_token(intent.asset)
        amount = self._amount_to_supply(intent, asset, vault)
        if amount <= 0:
            raise VenueError(
                f"nothing to supply: the vault holds no {intent.asset}, or the requested "
                f"fraction rounds to zero"
            )

        self._assert_valued(asset, vault)

        symbol = intent.asset.upper()
        human = self._human(amount, asset)

        plan = ExecutionPlan(
            venue=VENUE_KEY,
            steps=[
                # Re-emitted every plan rather than checked first, matching the
                # Uniswap adapter: a redundant approve costs gas and always
                # succeeds, a missing one reverts the whole atomic batch.
                ExecutionStep(
                    target=asset,
                    value="0",
                    calldata=encode_call(ERC20_APPROVE, POOL, amount),
                    why=f"approve the Aave pool to take {human} {symbol}",
                ),
                ExecutionStep(
                    target=POOL,
                    value="0",
                    # onBehalfOf is the VAULT. Anything else hands the position
                    # to someone who is not the custodian.
                    calldata=aave_pool_supply(asset, amount, vault.address),
                    why=f"supply {human} {symbol} to Aave v3 and receive the aToken",
                ),
            ],
            expected_effect=(
                f"supply {human} {symbol} into Aave v3; the vault receives aTokens it "
                f"holds itself and earns the supply rate"
            ),
            # A supply is not a trade. There is no route, no price impact and no
            # counterparty — reporting 0 rather than None says that positively,
            # and it keeps the mandate's slippage ceiling from being compared
            # against an absent value.
            expected_slippage_bps=0,
        )
        self._assert_targets(plan, vault)
        return plan

    # ── withdraw ──────────────────────────────────────────────────────────

    def _plan_withdraw(self, intent: WithdrawIntent, vault: VaultState) -> ExecutionPlan:
        asset = addresses.resolve_token(intent.asset)
        amount = int(intent.amount) if intent.amount is not None else UINT256_MAX
        symbol = intent.asset.upper()
        human = "all of it" if amount == UINT256_MAX else f"{self._human(amount, asset)} of"

        plan = ExecutionPlan(
            venue=VENUE_KEY,
            steps=[
                ExecutionStep(
                    target=POOL,
                    value="0",
                    # `to` is the vault: redeemed underlying comes home, it does
                    # not go to the agent's key.
                    calldata=aave_pool_withdraw(asset, amount, vault.address),
                    why=f"withdraw {human} the vault's supplied {symbol} from Aave v3",
                )
            ],
            expected_effect=f"redeem {human} the vault's Aave {symbol} position",
            expected_slippage_bps=0,
        )
        self._assert_targets(plan, vault)
        return plan

    # ── checks ────────────────────────────────────────────────────────────

    def _amount_to_supply(self, intent: SupplyIntent, asset: str, vault: VaultState) -> int:
        if intent.amount is not None:
            return int(intent.amount)
        if intent.pct_of_holdings is None:
            raise VenueError(
                "a supply needs either `amount` or `pct_of_holdings`; neither was set"
            )

        held = next(
            (h for h in vault.holdings if h.token.lower() == asset.lower()),
            None,
        )
        if held is None:
            raise VenueError(
                f"the vault holds no {intent.asset}, so there is no balance to take "
                f"{intent.pct_of_holdings:.0%} of"
            )
        return int(int(held.balance) * intent.pct_of_holdings)

    def _assert_valued(self, asset: str, vault: VaultState) -> None:
        """Refuse to supply into a vault that cannot value the aToken it gets back.

        The failure this prevents is silent and severe: `totalAssets()` counts
        only registered valued tokens, so supplying into a vault that does not
        know the aToken makes its reported worth **fall by the amount supplied**.
        Every depositor's share price drops, and nothing errors.

        Vault valuations are immutable after `initialize`, so this is a property
        of when the vault was created — vaults minted before
        `scripts/expand-universe.sh` ran genuinely cannot lend.

        **What is actually checked, stated precisely:** `addresses.allowlist()`
        reads the *deployment manifest*, which records what a vault created from
        the current factory defaults will allow. It is a deployment-wide answer,
        not a per-vault one, so it catches "this deployment has never registered
        aTokens" — the case that matters — and does not catch an individual old
        vault on a deployment that has since been widened. Reading the vault's
        own `allowedTargets()` would be exact but costs an RPC round trip on
        every plan; if lending on mixed-age vaults becomes routine, that is the
        upgrade. For now the vault's own `execute()` reverts on
        `TargetNotAllowed`, which fails closed rather than silently.
        """
        atoken = ATOKENS.get(asset.lower())
        if atoken is None:
            raise VenueError(
                f"no Aave aToken is recorded for {asset} on Base; add it to "
                f"venues/aave/markets.py after confirming it two ways — "
                f"UNDERLYING_ASSET_ADDRESS() and Pool.getReserveData(asset)[8]"
            )

        if atoken.lower() not in addresses.allowlist():
            raise PlanValidationError(
                f"this deployment cannot value {atoken} (the aToken for {asset}): it is "
                f"not in the deployment manifest's execute() allowlist, so no vault here "
                f"has a Chainlink valuation registered for it. Supplying anyway would "
                f"make totalAssets() drop by the amount supplied and collapse the share "
                f"price. Run scripts/expand-universe.sh, then create a new vault — "
                f"per-vault valuations are immutable, so existing vaults stay as they are."
            )

    @staticmethod
    def _assert_targets(plan: ExecutionPlan, vault: VaultState) -> None:
        """Fail here, with the seam named, rather than as an opaque revert."""
        del vault  # allowlist() reads the deployed manifest, not per-vault state
        allowed = addresses.allowlist()
        for index, step in enumerate(plan.steps):
            if step.target.lower() not in allowed:
                raise PlanValidationError(
                    f"step {index} targets {step.target}, which is not on the vault "
                    f"allowlist. Run scripts/expand-universe.sh to register the Aave "
                    f"pool and aTokens as factory defaults, then deploy a fresh vault."
                )

    @staticmethod
    def _human(amount: int, asset: str) -> str:
        decimals = addresses.decimals_for(asset)
        if decimals is None:
            return str(amount)
        return f"{amount / 10**decimals:,.6f}".rstrip("0").rstrip(".")

    async def aclose(self) -> None:
        """Nothing held open — every plan here is built from static calldata."""
        return None
