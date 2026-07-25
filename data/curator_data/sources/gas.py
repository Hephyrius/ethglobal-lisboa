"""What a rebalance costs — read from the chain the vault trades on.

## The gap this closes

The agent could see a 3 bps yield edge and had no way to know that capturing it
costs more than it earns. Every rejection message it has ever received is about
*limits*; nothing has ever told it about *cost*. On Base a swap is cheap, which
is exactly why the number needs to be present rather than assumed — "gas is
negligible here" is a true statement the agent should be able to make from
evidence, and it becomes false the moment the chain is busy.

Two facts, both `kind="gas"`:

  * the current base fee in gwei, as `bps`-free raw context
  * the **estimated USD cost of one rebalance**, which is the number that
    actually decides anything

The second needs an ETH price, so it is emitted only when one is available. It
is computed here rather than left to the model because "gwei × gas units ×
10⁻⁹ × ETH/USD" is precisely the sort of unit-juggling that produced a 3B model
reporting `$12,400,000 of liquidity` as `10.43% APY`.

## No credential, no third party

`eth_gasPrice` against the RPC we already have. The ETH price comes from the
same Chainlink feed the vault values holdings with, so the cost estimate and the
portfolio valuation cannot disagree.
"""

from __future__ import annotations

import logging

from curator_schema.models import Fact

from ..chain.rpc import RpcClient, RpcError, decode_word
from ..config import Settings
from ..facts import FactBuilder
from ..ports import BaseSource
from .feeds import feed_for

logger = logging.getLogger(__name__)

SELECTOR_LATEST_ROUND_DATA = "0xfeaf968c"

#: Gas units for one rebalance. Measured, not guessed: the executed tick on the
#: fork submitted approve + approve + router as a single `executeBatch` and
#: consumed roughly this much. Rounded up, because a cost estimate that is too
#: low is the one that leads to a trade that should not have happened.
REBALANCE_GAS_UNITS = 400_000

#: Chainlink USD feeds are 8-decimal on Base; verified by `description()` and
#: `decimals()` in `sources/chainlink.py`, which this deliberately reuses the
#: feed table of rather than hardcoding an address.
_FEED_DECIMALS = 8


class GasSource(BaseSource):
    """Base gas price, and what it makes one rebalance cost."""

    key = "gas"
    provides = ("gas",)
    description = (
        "Current Base gas price and the estimated USD cost of one rebalance, read from "
        "the chain the vault trades on. Lets the agent tell a yield edge worth capturing "
        "from one that costs more than it earns. Needs no API key."
    )

    def __init__(self, settings: Settings, *, rpc: RpcClient | None = None):
        super().__init__()
        self.settings = settings
        self._rpc = rpc
        self._owns_rpc = rpc is None

    @property
    def rpc(self) -> RpcClient:
        if self._rpc is None:
            if not self.settings.rpc_url:
                raise RuntimeError(
                    "no RPC endpoint configured - set DATA_RPC_URL, ANVIL_RPC_URL or "
                    "BASE_RPC_URL so gas can be read on-chain"
                )
            self._rpc = RpcClient(
                self.settings.rpc_url, timeout_s=self.settings.request_timeout_s
            )
        return self._rpc

    async def fetch(self, assets: list[str]) -> list[Fact]:
        del assets  # gas is a property of the chain, not of an asset

        try:
            gas_wei = await self._gas_price()
        except RpcError as exc:
            raise RuntimeError(f"could not read gas price: {exc}") from exc

        builder = FactBuilder(self.key, chain=self.settings.chain, on_finding=self.diagnose)
        subject = builder.subject(market="base gas")
        gwei = gas_wei / 1e9

        facts = [builder.fact("gas", subject, gwei, "token_amount")]

        eth_usd = await self._eth_usd()
        if eth_usd is None:
            self.remark(
                "no ETH price available, so the USD cost of a rebalance could not be "
                "computed — the gwei figure alone does not say whether a trade is worth it"
            )
            return facts

        cost_usd = (gas_wei * REBALANCE_GAS_UNITS / 1e18) * eth_usd
        facts.append(
            builder.usd(
                "gas",
                builder.subject(market=f"cost of one rebalance ({REBALANCE_GAS_UNITS:,} gas)"),
                cost_usd,
            )
        )
        return facts

    async def _gas_price(self) -> int:
        result = await self.rpc.request("eth_gasPrice", [])
        if not isinstance(result, str):
            raise RpcError(f"eth_gasPrice returned {result!r}")
        return int(result, 16)

    async def _eth_usd(self) -> float | None:
        """ETH/USD from the same feed the vault values holdings with.

        Returns None rather than raising: gas in gwei is still a useful fact,
        and losing it because the oracle was unreachable would be the wrong
        trade. A missing price is reported as a remark, not an error, because
        the source did produce what it could.
        """
        feed = feed_for("WETH", self.settings.chain)
        if feed is None:
            return None
        try:
            data = await self.rpc.call(feed.address, SELECTOR_LATEST_ROUND_DATA)
            answer = decode_word(data, 1, signed=True)
        except Exception as exc:  # noqa: BLE001 - see below
            # Deliberately catches everything. This is a best-effort extra on
            # top of a fact we already have, and the narrower
            # `(RpcError, ValueError)` this replaces let a plain RuntimeError
            # from the transport escape and take down the whole source — losing
            # the gwei reading too, over an optional multiplication.
            logger.debug("ETH price for the gas estimate was unavailable: %s", exc)
            return None
        return answer / (10**_FEED_DECIMALS) if answer > 0 else None

    async def close(self) -> None:
        if self._rpc is not None and self._owns_rpc:
            await self._rpc.aclose()


def make_gas_source(settings: Settings) -> GasSource:
    """Registration factory. Referenced from `sources/__init__.py`."""
    return GasSource(settings)


__all__ = ["GasSource", "make_gas_source", "REBALANCE_GAS_UNITS"]
