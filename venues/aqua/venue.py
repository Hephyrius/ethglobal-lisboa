"""`AquaVenue` — the maker side, implementing the frozen `Venue` port.

Role in the system: Aqua **holds** the position. Uniswap rotates *what* the
vault holds; Aqua earns on what it already holds by posting it as passive
liquidity. An Aqua maker cannot decide to change its composition — that is
structural, and it is why both venues are needed and why neither is decorative.

The custody argument, which is the whole reason 1inch is load-bearing here:
Aqua is a shared-liquidity *registry*. It tracks
`balances[maker][app][strategyHash][token]` on-chain while the tokens stay in
the maker's wallet. The vault is the maker. So a live market-making position
opens and closes without a single token leaving the vault, `totalAssets()`
keeps working off plain `balanceOf`, and our locked Pattern 1 custody decision
survives intact. A conventional AMM LP position could not do this.
"""

from __future__ import annotations

import hashlib
from typing import Final

from curator_schema.models import (
    AquaDockIntent,
    AquaShipIntent,
    ExecutionPlan,
    VaultState,
    VenueIntent,
)

from .. import addresses
from ..config import VenueConfig
from ..errors import UnsupportedIntentError, VenueError
from ..rpc import RpcClient
from ..uniswap.plan import assert_targets_allowlisted
from .calldata import approve_step, dock_step, ship_step
from .program import ProgramBuilder

VENUE_KEY: Final[str] = "aqua"

#: Maker fee charged on fills, in basis points, when the intent does not say.
#: 30 bps matches a standard 0.3% AMM tier — a defensible default for a
#: constant-product position rather than an invented number.
DEFAULT_FEE_BPS: Final[int] = 30


class AquaVenue:
    """Implements `curator_schema.ports.Venue`."""

    key: str = VENUE_KEY

    def __init__(
        self,
        *,
        config: VenueConfig | None = None,
        rpc: RpcClient | None = None,
        builder: ProgramBuilder | None = None,
        default_fee_bps: int = DEFAULT_FEE_BPS,
    ) -> None:
        self._config = config or VenueConfig.from_env()
        self._rpc = rpc
        self._builder = builder
        self._default_fee_bps = default_fee_bps

    @property
    def rpc(self) -> RpcClient:
        if self._rpc is None:
            self._rpc = RpcClient(self._config.rpc_url)
        return self._rpc

    @property
    def builder(self) -> ProgramBuilder:
        if self._builder is None:
            self._builder = ProgramBuilder(self.rpc)
        return self._builder

    async def aclose(self) -> None:
        if self._rpc is not None:
            await self._rpc.aclose()

    async def plan(self, intent: VenueIntent, vault: VaultState) -> ExecutionPlan:
        if isinstance(intent, AquaShipIntent):
            return await self._plan_ship(intent, vault)
        if isinstance(intent, AquaDockIntent):
            return self._plan_dock(intent, vault)
        raise UnsupportedIntentError(
            f"AquaVenue serves ship/dock intents; got {type(intent).__name__}. "
            f"Route swap intents to UniswapVenue."
        )

    # ── ship ──────────────────────────────────────────────────────────────

    async def _plan_ship(self, intent: AquaShipIntent, vault: VaultState) -> ExecutionPlan:
        if len(intent.tokens) != len(intent.amounts):
            raise VenueError(
                f"ship intent has {len(intent.tokens)} tokens but "
                f"{len(intent.amounts)} amounts; they must be index-aligned"
            )
        if len(intent.tokens) != 2:
            # XYCSwap is a two-token constant-product curve. Reject a third
            # token loudly rather than silently dropping it.
            raise VenueError(
                f"the XYC strategy is a two-token curve; got {len(intent.tokens)} tokens"
            )

        resolved = [addresses.resolve_token(t) for t in intent.tokens]
        requested = {
            token.lower(): int(amount)
            for token, amount in zip(resolved, intent.amounts, strict=True)
        }
        fee_bps = (intent.program.fee_bps if intent.program else None) or self._default_fee_bps
        salt = self._salt_for(vault, resolved, fee_bps)

        strategy = await self.builder.build_strategy(
            vault.address, resolved[0], resolved[1], fee_bps=fee_bps, salt=salt
        )

        # The contract sorted the tokens; re-pair the amounts to that order so
        # a ship() can never associate an amount with the wrong token.
        ordered_tokens = [strategy.token_a, strategy.token_b]
        ordered_amounts = [requested[t.lower()] for t in ordered_tokens]

        steps = [
            approve_step(token, amount)
            for token, amount in zip(ordered_tokens, ordered_amounts, strict=True)
        ]
        steps.append(ship_step(strategy.strategy, ordered_tokens, ordered_amounts))

        plan = ExecutionPlan(
            venue=VENUE_KEY,
            steps=steps,
            expected_effect=(
                f"ship a {fee_bps / 100:g}% constant-product position into Aqua "
                f"({strategy.strategy_hash[:10]}…) — tokens stay in the vault"
            ),
            # No router quote and no price impact: a maker posts liquidity and
            # waits. Leaving these unset is the honest answer, and it keeps the
            # harness from comparing a meaningless number against the mandate.
            expected_slippage_bps=0,
        )
        assert_targets_allowlisted(plan)
        return plan

    # ── dock ──────────────────────────────────────────────────────────────

    def _plan_dock(self, intent: AquaDockIntent, vault: VaultState) -> ExecutionPlan:
        tokens = self._tokens_for_strategy(intent.strategy_hash, vault)
        plan = ExecutionPlan(
            venue=VENUE_KEY,
            steps=[dock_step(intent.strategy_hash, tokens)],
            expected_effect=(
                f"dock Aqua strategy {intent.strategy_hash[:10]}… — "
                f"clears virtual balances, moves no capital"
            ),
            expected_slippage_bps=0,
        )
        assert_targets_allowlisted(plan)
        return plan

    def _tokens_for_strategy(self, strategy_hash: str, vault: VaultState) -> list[str]:
        """`dock()` needs the strategy's token list, which the intent does not
        carry. Recover it from the vault state the harness already holds."""
        for strategy in vault.aqua_strategies:
            if strategy.strategy_hash.lower() == strategy_hash.lower():
                if strategy.tokens:
                    return list(strategy.tokens)
                break
        raise VenueError(
            f"cannot dock {strategy_hash}: no matching entry with a token list in "
            f"VaultState.aqua_strategies. The harness must record tokens at ship() "
            f"time — see venues/README.md."
        )

    # ── helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _salt_for(vault: VaultState, tokens: list[str], fee_bps: int) -> int:
        """Derive the strategy salt deterministically.

        A random salt would mean the same intent produced a different strategy
        hash on every call, so a retried tick would open a second position
        instead of being idempotent. Deriving it from vault state keeps a
        rebuild reproducible while still letting a genuinely new position (new
        fee, new pair, new block) hash differently.
        """
        parts = [vault.address.lower(), *sorted(t.lower() for t in tokens), str(fee_bps)]
        if vault.block_number is not None:
            parts.append(str(vault.block_number))
        return int.from_bytes(hashlib.sha256("|".join(parts).encode()).digest(), "big")
