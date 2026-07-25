"""Graph · Messari standardized subgraphs.

The reason this source is one file rather than one file per protocol: Messari
publishes a *standardized schema per protocol type*, so Aave and Moonwell and
every other lending market answer the identical GraphQL document. The list of
protocols is therefore configuration (`protocols.py`), and this module is the
single adapter that serves all of them.

Two query shapes, matching the two Messari schemas we use:

  * `schema-lending`  → `markets`        → yield, TVL, utilization
  * `schema-dex-amm`  → `liquidityPools` → liquidity

Everything is normalized here, at the adapter boundary, per the frozen schema's
invariant. The trap worth naming: **Messari reports `InterestRate.rate` as a
percentage** (`4.32` meaning 4.32%), while `Fact.unit="apy_fraction"` requires
`0.0432`. `FactBuilder.apy_from_percent` is the only conversion path used here.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from curator_schema.models import Fact

from ..config import Settings
from ..facts import FactBuilder
from ..graph.gateway import GatewayClient
from ..ports import BaseSource
from .protocols import Protocol, enabled_protocols

logger = logging.getLogger(__name__)

# Markets are fetched top-N-by-TVL and filtered on symbol in Python rather than
# with a nested `where: {inputToken_: {...}}` server-side filter. Nested entity
# filters are a newer graph-node feature and support varies by indexer; a query
# that 400s against one protocol would take out that whole protocol. Ordering
# by TVL means the top 100 comfortably contains every market a vault this size
# would consider.
MARKET_LIMIT = 100

LENDING_QUERY = """
query CuratorLendingMarkets($first: Int!) {
  markets(
    first: $first
    orderBy: totalValueLockedUSD
    orderDirection: desc
    where: { isActive: true }
  ) {
    id
    name
    isActive
    inputToken { id symbol decimals }
    totalValueLockedUSD
    totalDepositBalanceUSD
    totalBorrowBalanceUSD
    rates { rate side type }
  }
}
"""

DEX_QUERY = """
query CuratorLiquidityPools($first: Int!) {
  liquidityPools(
    first: $first
    orderBy: totalValueLockedUSD
    orderDirection: desc
  ) {
    id
    name
    inputTokens { id symbol decimals }
    totalValueLockedUSD
  }
}
"""


def _to_float(value: Any) -> float | None:
    """Subgraph BigDecimals arrive as strings; missing data arrives as None."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _supply_apy_percent(rates: list[dict] | None) -> float | None:
    """The lender-side APY, as the percentage Messari reports.

    A market can publish several rates (variable/stable, lender/borrower). The
    vault is a depositor, so only `side == LENDER` is relevant; VARIABLE is
    preferred because that is the rate a supplier actually earns on these
    protocols, with any lender rate as a fallback.
    """
    if not rates:
        return None
    lender = [r for r in rates if str(r.get("side", "")).upper() == "LENDER"]
    if not lender:
        return None
    variable = [r for r in lender if str(r.get("type", "")).upper() == "VARIABLE"]
    chosen = (variable or lender)[0]
    return _to_float(chosen.get("rate"))


class MessariSource(BaseSource):
    """Lending yields, TVL, utilization and DEX liquidity from Messari subgraphs."""

    key = "messari"
    description = (
        "Lending market yields, TVL and utilization plus DEX pool liquidity, via "
        "Messari standardized subgraphs on The Graph. One query shape spans every "
        "protocol, so the protocol list is configuration."
    )

    def __init__(
        self,
        settings: Settings,
        *,
        gateway: GatewayClient | None = None,
        protocols: list[Protocol] | None = None,
    ):
        super().__init__()
        self.settings = settings
        self._gateway = gateway or GatewayClient(settings)
        self._owns_gateway = gateway is None
        self._protocols = protocols if protocols is not None else enabled_protocols(
            chain=settings.chain
        )

    @property
    def protocols(self) -> list[Protocol]:
        return list(self._protocols)

    async def fetch(self, assets: list[str]) -> list[Fact]:
        """Query every configured protocol concurrently and merge the facts.

        One protocol failing costs only that protocol: the failure becomes a
        note (surfaced in `MarketSnapshot.errors`) and the rest still return.
        The agent must never be told it saw the whole market when a protocol
        was silently missing.
        """
        wanted = {a.strip().upper() for a in assets if a and a.strip()}
        if not self._protocols:
            self.note("no protocols configured for chain " + self.settings.chain)
            return []

        # A missing credential is a whole-source condition, not a per-protocol
        # one. Checking it once turns N identical "no API key" notes into a
        # single actionable error.
        if not self.settings.graph_api_key:
            raise RuntimeError(
                "GRAPH_API_KEY is not set - get one free at https://thegraph.com/studio "
                "-> API Keys and put it in .env"
            )

        results = await asyncio.gather(
            *(self._fetch_protocol(p, wanted) for p in self._protocols),
            return_exceptions=True,
        )

        facts: list[Fact] = []
        for protocol, result in zip(self._protocols, results):
            if isinstance(result, BaseException):
                self.note(f"{protocol.key}: {type(result).__name__}: {result}")
                continue
            facts.extend(result)
        return facts

    async def _fetch_protocol(self, protocol: Protocol, wanted: set[str]) -> list[Fact]:
        builder = FactBuilder(self.key, chain=protocol.chain)
        if protocol.family == "lending":
            data = await self._gateway.query(
                protocol.subgraph_id, LENDING_QUERY, {"first": MARKET_LIMIT}
            )
            return self._lending_facts(protocol, data.get("markets") or [], wanted, builder)

        data = await self._gateway.query(
            protocol.subgraph_id, DEX_QUERY, {"first": MARKET_LIMIT}
        )
        return self._dex_facts(protocol, data.get("liquidityPools") or [], wanted, builder)

    # ── lending ───────────────────────────────────────────────────────────

    def _lending_facts(
        self,
        protocol: Protocol,
        markets: list[dict],
        wanted: set[str],
        builder: FactBuilder,
    ) -> list[Fact]:
        facts: list[Fact] = []
        matched = 0
        for market in markets:
            token = market.get("inputToken") or {}
            symbol = str(token.get("symbol") or "").upper()
            if wanted and symbol not in wanted:
                continue
            matched += 1
            subject = builder.subject(protocol=protocol.key, market=symbol or None)

            apy_percent = _supply_apy_percent(market.get("rates"))
            if apy_percent is not None:
                facts.append(builder.apy_from_percent(subject, apy_percent))

            tvl = _to_float(market.get("totalValueLockedUSD"))
            if tvl is not None:
                facts.append(builder.usd("tvl", subject, tvl))

            utilization = self._utilization(market)
            if utilization is not None:
                facts.append(builder.ratio("utilization", subject, utilization))

        if wanted and not matched:
            self.note(
                f"{protocol.key}: no active market for {sorted(wanted)} in the top "
                f"{MARKET_LIMIT} by TVL"
            )
        return facts

    @staticmethod
    def _utilization(market: dict) -> float | None:
        """Borrowed / supplied, the standard lending utilization ratio.

        Derived rather than read: Messari's lending schema publishes the two
        balances but not the ratio, and utilization is what actually tells the
        agent whether a headline APY is stable or about to move.
        """
        deposits = _to_float(market.get("totalDepositBalanceUSD"))
        borrows = _to_float(market.get("totalBorrowBalanceUSD"))
        if deposits is None or borrows is None or deposits <= 0:
            return None
        return max(0.0, min(borrows / deposits, 1.0))

    # ── dex ───────────────────────────────────────────────────────────────

    def _dex_facts(
        self,
        protocol: Protocol,
        pools: list[dict],
        wanted: set[str],
        builder: FactBuilder,
    ) -> list[Fact]:
        facts: list[Fact] = []
        for pool in pools:
            symbols = [
                str((t or {}).get("symbol") or "").upper() for t in pool.get("inputTokens") or []
            ]
            # Only pools the vault could actually make a market in: every leg
            # must be an asset the mandate permits.
            if wanted and not (len(symbols) >= 2 and all(s in wanted for s in symbols)):
                continue

            tvl = _to_float(pool.get("totalValueLockedUSD"))
            if tvl is None:
                continue
            subject = builder.subject(protocol=protocol.key, pair=symbols[:2])
            facts.append(builder.usd("liquidity", subject, tvl))
        return facts

    async def close(self) -> None:
        if self._owns_gateway:
            await self._gateway.aclose()


def make_messari_source(settings: Settings) -> MessariSource:
    """Registration factory. Referenced from `sources/__init__.py`."""
    return MessariSource(settings)


__all__ = ["MessariSource", "make_messari_source", "LENDING_QUERY", "DEX_QUERY"]
