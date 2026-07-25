"""The MCP server: four tools over live DeFi market data from The Graph.

Design rules this server follows, because they are what separate reusable
tooling from a demo endpoint:

  * **Every tool answers a question an agent actually asks.** Not "run this
    GraphQL" — an agent that could write the GraphQL would not need the tool.
    `compare_protocols("USDC")` is the unit of thought.
  * **Provenance travels with every number.** Each response carries `fact_ids`
    and `sources`, so a caller can cite what it saw and a reviewer can check it.
  * **Degradation is reported, never hidden.** `errors` is present on every
    response. A tool that silently returns 2 protocols when 3 were configured
    teaches the model that the market is smaller than it is.
  * **No knowledge of any particular consumer.** This server does not import,
    reference or assume the vault-curation agent that happens to be its first
    user.

Transport is stdio, which is what MCP clients launch by default.
"""

from __future__ import annotations

import logging
import os

from mcp.server.fastmcp import FastMCP

from curator_data.config import Settings
from curator_data.queries import (
    MARKET_KINDS,
    PRICE_KINDS,
    errors_as_dicts,
    pivot_markets,
    pivot_pools,
    prices,
    snapshot_for,
)
from curator_data.sources.protocols import ALL as ALL_PROTOCOLS
from curator_data.sources.tokens import known_symbols

logger = logging.getLogger(__name__)

#: Used when a caller names no assets. Broad enough to be useful on Base,
#: small enough to keep a response readable.
DEFAULT_ASSETS = ["USDC", "WETH"]

INSTRUCTIONS = """\
Live DeFi market data on Base from The Graph.

Use `compare_protocols` to pick where to put an asset, `get_market_yields` for one
asset's rates across every protocol, `list_markets` for a broad survey, and
`get_token_price` for spot USD prices.

Every response includes `fact_ids` and `sources`. Cite them when you explain a
decision. Every response also includes `errors`: if it is non-empty, some data
could not be fetched and your view is partial — say so rather than treating the
result as the whole market.

APYs are returned twice: `supply_apy` as a fraction (0.0432) for arithmetic, and
`supply_apy_pct` (4.32) for display. Do not mix them up.
"""


def build_server(settings: Settings | None = None) -> FastMCP:
    """Construct the server. Separated from `main` so tests can drive it."""
    resolved = settings or Settings.from_env()
    mcp = FastMCP("curator", instructions=INSTRUCTIONS)

    @mcp.tool()
    async def list_markets(assets: list[str] | None = None) -> dict:
        """Survey lending markets across every configured protocol.

        Args:
            assets: Token symbols to include, e.g. ["USDC", "WETH"]. Omit for a
                default set. Filtering happens by symbol, case-insensitive.

        Returns markets sorted by supply APY (highest first), each with TVL,
        utilization, and the fact ids backing it.
        """
        symbols = [a.upper() for a in (assets or DEFAULT_ASSETS)]
        snapshot = await snapshot_for(symbols, kinds=MARKET_KINDS, settings=resolved)
        return {
            "markets": [row.to_dict() for row in pivot_markets(snapshot)],
            "pools": [row.to_dict() for row in pivot_pools(snapshot)],
            "assets": symbols,
            "taken_at": snapshot.taken_at.isoformat(),
            "errors": errors_as_dicts(snapshot),
        }

    @mcp.tool()
    async def get_market_yields(asset: str) -> dict:
        """Supply APYs for one asset across every protocol that lists it.

        Args:
            asset: Token symbol, e.g. "USDC".

        Use this when you know the asset and want to know what it earns and
        where. Rates are current supply-side (lender) APYs.
        """
        symbol = asset.strip().upper()
        snapshot = await snapshot_for([symbol], kinds=MARKET_KINDS, settings=resolved)
        rows = [r for r in pivot_markets(snapshot) if r.market.upper() == symbol]
        return {
            "asset": symbol,
            "yields": [
                {
                    "protocol": r.protocol,
                    "supply_apy": r.supply_apy,
                    "supply_apy_pct": r.supply_apy_pct,
                    "tvl_usd": r.tvl_usd,
                    "utilization": r.utilization,
                    "fact_ids": r.fact_ids,
                    "sources": r.sources,
                }
                for r in rows
            ],
            "taken_at": snapshot.taken_at.isoformat(),
            "errors": errors_as_dicts(snapshot),
        }

    @mcp.tool()
    async def compare_protocols(asset: str) -> dict:
        """Rank protocols for supplying one asset, with the tradeoffs stated.

        Args:
            asset: Token symbol, e.g. "USDC".

        Returns the same rows as `get_market_yields` plus `best_apy` and
        `deepest_tvl`, which are frequently different protocols — that gap is
        the actual decision, so it is surfaced rather than left to be inferred.
        High utilization means a headline APY is less stable and withdrawals
        may be constrained.
        """
        symbol = asset.strip().upper()
        snapshot = await snapshot_for([symbol], kinds=MARKET_KINDS, settings=resolved)
        rows = [r for r in pivot_markets(snapshot) if r.market.upper() == symbol]

        with_apy = [r for r in rows if r.supply_apy is not None]
        with_tvl = [r for r in rows if r.tvl_usd is not None]
        best = max(with_apy, key=lambda r: r.supply_apy or 0.0, default=None)
        deepest = max(with_tvl, key=lambda r: r.tvl_usd or 0.0, default=None)

        return {
            "asset": symbol,
            "protocols": [r.to_dict() for r in rows],
            "best_apy": None if best is None else best.protocol,
            "deepest_tvl": None if deepest is None else deepest.protocol,
            "note": (
                "Highest APY and deepest liquidity are often different protocols. "
                "Utilization above ~0.9 means the rate is volatile and exits can be "
                "constrained."
            ),
            "taken_at": snapshot.taken_at.isoformat(),
            "errors": errors_as_dicts(snapshot),
        }

    @mcp.tool()
    async def get_token_price(symbol: str) -> dict:
        """Spot USD price for a token.

        Args:
            symbol: Token symbol, e.g. "WETH".

        Only symbols with a known contract address on the configured chain can
        be priced; `known_symbols` in the response lists them.
        """
        token = symbol.strip().upper()
        snapshot = await snapshot_for([token], kinds=PRICE_KINDS, settings=resolved)
        found = prices(snapshot).get(token)
        return {
            "symbol": token,
            "price": found,
            "known_symbols": known_symbols(resolved.chain),
            "taken_at": snapshot.taken_at.isoformat(),
            "errors": errors_as_dicts(snapshot),
        }

    @mcp.resource("curator://protocols")
    def protocols() -> str:
        """The configured protocol set — what this server can currently see."""
        lines = [
            "# Configured protocols",
            "",
            "| key | label | family | chain | enabled |",
            "|---|---|---|---|---|",
        ]
        lines += [
            f"| {p.key} | {p.label} | {p.family} | {p.chain} | {'yes' if p.enabled else 'no'} |"
            for p in ALL_PROTOCOLS
        ]
        return "\n".join(lines)

    return mcp


def main() -> None:
    """Console-script entry point: `curator-mcp` / `uvx curator-mcp`."""
    logging.basicConfig(
        level=os.getenv("CURATOR_MCP_LOG_LEVEL", "WARNING").upper(),
        # stderr: stdout is the MCP transport and anything else on it is a
        # protocol violation that shows up as a client-side parse error.
        format="%(levelname)s %(name)s: %(message)s",
    )
    build_server().run()


if __name__ == "__main__":  # pragma: no cover
    main()
