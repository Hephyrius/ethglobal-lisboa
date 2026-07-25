"""`UniswapVenue` — the taker side, implementing the frozen `Venue` port.

Role in the system: Uniswap **rotates what the vault holds**. When the agent
decides "volatility spiked, move to stables", this is the path that acts on it.
That is deliberately distinct from Aqua, which *holds* a market-making position
and cannot change composition — an Aqua maker is passive by construction. The
two venues do not overlap, which is what keeps the 1inch integration from
reading as cosmetic (initiate_plan.md §7).
"""

from __future__ import annotations

from typing import Final

from curator_schema.models import ExecutionPlan, SwapIntent, VaultState, VenueIntent

from ..addresses import decimals_for, resolve_token
from ..config import VenueConfig
from ..errors import UnsupportedIntentError, VenueError
from .client import QuoteRequest, UniswapClient
from .plan import build_plan

VENUE_KEY: Final[str] = "uniswap"


class UniswapVenue:
    """Implements `curator_schema.ports.Venue`.

    Holds no state beyond its client, so one instance is safe to share across
    ticks and across vaults.
    """

    key: str = VENUE_KEY

    def __init__(
        self,
        client: UniswapClient | None = None,
        *,
        config: VenueConfig | None = None,
        default_slippage_bps: int | None = None,
    ) -> None:
        self._config = config or VenueConfig.from_env()
        self._client = client
        self._default_slippage_bps = default_slippage_bps

    @property
    def client(self) -> UniswapClient:
        if self._client is None:
            self._client = UniswapClient.from_config(self._config)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()

    async def plan(self, intent: VenueIntent, vault: VaultState) -> ExecutionPlan:
        """Quote the swap, then turn it into vault-executable calldata.

        Raises `UnsupportedIntentError` for a non-swap intent — an Aqua intent
        routed here is a wiring bug in the caller and should be loud.
        """
        if not isinstance(intent, SwapIntent):
            raise UnsupportedIntentError(
                f"UniswapVenue serves swap intents; got {type(intent).__name__}. "
                f"Route ship/dock intents to AquaVenue."
            )

        token_in = resolve_token(intent.token_in)
        token_out = resolve_token(intent.token_out)
        amount = self._resolve_amount(intent, vault, token_in)

        request = QuoteRequest(
            token_in=token_in,
            token_out=token_out,
            amount=amount,
            swapper=vault.address,
            slippage_bps=self._default_slippage_bps,
        )

        quote_response = await self.client.quote(request)
        swap_response = await self.client.swap(quote_response["quote"])
        return build_plan(quote_response, swap_response)

    def _resolve_amount(
        self, intent: SwapIntent, vault: VaultState, token_in: str
    ) -> int:
        """`amount_in` wins; otherwise `pct_of_holdings` against what the vault
        actually holds.

        The percentage form exists because a model reliably produces "sell 30%"
        and unreliably produces a correct uint256 in base units. Resolving it
        against real holdings — never against a model-supplied balance — is
        what keeps a hallucinated number from becoming a real trade.
        """
        if intent.amount_in is not None:
            return int(intent.amount_in)

        if intent.pct_of_holdings is None:
            raise VenueError(
                "SwapIntent must set either amount_in or pct_of_holdings; got neither"
            )

        holding = next(
            (h for h in vault.holdings if h.token.lower() == token_in.lower()), None
        )
        if holding is None:
            raise VenueError(
                f"vault {vault.address} holds no {intent.token_in} ({token_in}), "
                f"so pct_of_holdings cannot be resolved"
            )

        amount = int(int(holding.balance) * intent.pct_of_holdings)
        if amount <= 0:
            raise VenueError(
                f"{intent.pct_of_holdings:.4f} of {holding.balance} "
                f"{intent.token_in} rounds to zero — nothing to swap"
            )
        return amount

    @staticmethod
    def decimals(token: str) -> int | None:
        """Convenience for callers formatting amounts. None means unknown —
        do not default to 18."""
        return decimals_for(resolve_token(token))
