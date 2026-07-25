"""Morpho Blue on Base, via Morpho's own API.

The gap the Wave 2 feedback names: Morpho is one of Base's largest lending
markets and the obvious hole next to Aave and Moonwell.

## Why not a subgraph, when this lane's whole story is The Graph

Because the Graph route for Morpho on Base does not work, and checking beat
assuming. There is **exactly one** Morpho Base subgraph on the decentralised
network (`71ZTy1ve…`, found by querying The Graph's own network subgraph for
all 4,000 active subgraphs). It answers the standardized schema, and it indexes
a dead deployment: its largest market by TVL holds **$448**, with names like
`MINITIMEBOTALPHAXXXXXXXXXXXXXX`, while Morpho on Base actually holds ~$1.4bn.
That was verified twice, a wave apart, and recorded in `protocols.py` so nobody
re-adds it.

So this source uses `blue-api.morpho.org` — first-party, free, no token gate,
no credential — on the same terms as `defillama`, `feargreed` and `gas`. The
Graph remains the source of record for Aave and Moonwell; this is a protocol
that The Graph does not usefully cover on this chain, and saying so plainly is
better than shipping $448 of fake markets to keep a story tidy.

## What live data forced

`supplyApy` is the interest. `netSupplyApy` adds rewards and subtracts fees, so
it is the *headline* — the same base-versus-headline trap DefiLlama taught this
lane. We report the base and remark when the two differ.

**The market that justifies the plausibility guard**, read live on 2026-07-25:

    USDC/HERMES   supply APY 297,892.52%   supplied $54,552,553   utilization 1.00

$54M really is supplied, and the rate really is what the API returns: a runaway
interest curve on a market pinned at full utilization. An agent told "USDC
yields 297,892% on Morpho" would move the entire book into a position it could
not exit, because at utilization 1.00 every supplied dollar is already lent out.

**The whole market is dropped, not merely its rate.** Reporting a $54M size for
a market whose yield is impossible would still present it as a real venue, and
size is exactly what an agent uses to judge whether a market is safe to enter.

The other thing live data forced: Morpho Blue permits **many markets per pair**,
differing only by LLTV, oracle or rate model. `USDC/HERMES` appeared 24 times in
one response. Only the deepest market for each pair is reported — an agent
choosing where to supply wants the best market for a pair, not every variant.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from curator_schema.models import Fact

from ..config import Settings
from ..diagnostics import (
    OTHERS_UNAFFECTED,
    explain_exception,
)
from ..facts import FactBuilder
from ..http import LoopBoundClient
from ..plausibility import implausible_apy, implausible_usd, is_fully_utilized
from ..ports import BaseSource

logger = logging.getLogger(__name__)

API_URL = "https://blue-api.morpho.org/graphql"

#: Base mainnet. The API takes numeric chain ids, not names.
CHAIN_IDS: dict[str, int] = {"base": 8453}

#: Markets fetched, ordered by size. Deep enough to cover anything a vault of
#: this size would consider, shallow enough to stay one fast request.
MARKET_LIMIT = 50

#: Below this a market is too thin to enter without becoming most of it.
MIN_SUPPLY_USD = 1_000_000.0

MARKETS_QUERY = """
query CuratorMorphoMarkets($first: Int!, $chainIds: [Int!]) {
  markets(
    first: $first
    orderBy: SupplyAssetsUsd
    orderDirection: Desc
    where: { chainId_in: $chainIds }
  ) {
    items {
      marketId
      loanAsset { symbol decimals }
      collateralAsset { symbol }
      state { supplyApy netSupplyApy supplyAssetsUsd utilization }
    }
  }
}
"""


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class MorphoSource(BaseSource):
    """Supply yields, TVL and utilization for Morpho Blue markets."""

    key = "morpho"
    provides = ("yield", "tvl", "utilization")
    description = (
        "Morpho Blue lending markets on Base - supply APY, size and utilization, from "
        "Morpho's own API. Needs no credential. Covers the largest lending market on "
        "the chain, which The Graph does not usefully index here."
    )

    def __init__(self, settings: Settings, *, client: httpx.AsyncClient | None = None):
        super().__init__()
        self.settings = settings
        self._owns_client = client is None
        self._http = LoopBoundClient(
            lambda: httpx.AsyncClient(timeout=settings.request_timeout_s)
        )
        self._http.adopt(client)

    @property
    def client(self) -> httpx.AsyncClient:
        return self._http.get_client()

    async def fetch(self, assets: list[str]) -> list[Fact]:
        chain_id = CHAIN_IDS.get(self.settings.chain)
        if chain_id is None:
            self.diagnose(
                self.settings.chain,
                "Morpho Blue is not configured for this chain",
                "no Morpho markets are in this snapshot; add the chain id to "
                "curator_data/sources/morpho.py",
                failure=False,
            )
            return []

        wanted = {a.strip().upper() for a in assets if a and a.strip()}
        items = await self._markets(chain_id)
        if items is None:
            return []

        builder = FactBuilder(self.key, chain=self.settings.chain, on_finding=self.diagnose)
        facts: list[Fact] = []
        matched = 0
        #: pair -> deepest market for that pair. Morpho Blue permits many
        #: markets per pair; the agent wants the best one, not all of them.
        best: dict[str, dict[str, Any]] = {}
        #: Pairs already reported as implausible, so 24 clones say it once.
        dropped: set[str] = set()

        for market in items:
            loan = (market.get("loanAsset") or {}).get("symbol")
            if not loan:
                continue
            loan = loan.upper()
            # The vault supplies the LOAN asset and is exposed to the
            # collateral only through liquidation quality, so the mandate's
            # allowed assets are matched against the loan side.
            if wanted and loan not in wanted:
                continue

            state = market.get("state") or {}
            supplied = _to_float(state.get("supplyAssetsUsd"))
            if supplied is None or supplied < MIN_SUPPLY_USD or implausible_usd(supplied):
                continue

            collateral = (market.get("collateralAsset") or {}).get("symbol") or "idle"
            market_name = f"{loan}/{collateral}"
            utilization = _to_float(state.get("utilization"))
            base = _to_float(state.get("supplyApy"))
            net = _to_float(state.get("netSupplyApy"))

            if implausible_apy(base):
                # See the module docstring: HERMES is a real market with $54M
                # in it. The WHOLE market is skipped rather than just its
                # yield — reporting the size of a market whose rate is
                # impossible invites the agent to treat it as a real option.
                if market_name not in dropped:
                    dropped.add(market_name)
                    self.diagnose(
                        market_name,
                        f"reports a {base:.0%} supply APY on ${supplied:,.0f} supplied"
                        + (
                            f" at {utilization:.0%} utilization"
                            if utilization is not None
                            else ""
                        ),
                        "the whole market is dropped, not just the rate - no deposit earns "
                        "that, and its size would otherwise read as a real opportunity",
                        failure=False,
                    )
                continue

            # Morpho Blue lets the same pair exist many times over, differing
            # only by LLTV, oracle or rate model — live, USDC/HERMES appeared
            # 24 times. An agent choosing where to supply wants the best market
            # for a pair, not every variant of it, so keep the deepest.
            existing = best.get(market_name)
            if existing is not None and existing["supplied"] >= supplied:
                continue
            best[market_name] = {
                "supplied": supplied,
                "base": base,
                "net": net,
                "utilization": utilization,
            }

        for market_name, row in best.items():
            subject = builder.subject(protocol=self.key, market=market_name)
            matched += 1
            supplied = row["supplied"]
            base, net, utilization = row["base"], row["net"], row["utilization"]

            if base is not None and base > 0:
                facts.append(builder.apy_from_fraction(subject, base))
                if net is not None and abs(net - base) > 0.001:
                    self.diagnose(
                        market_name,
                        f"reporting its {base:.2%} supply APY, not the {net:.2%} net figure",
                        "the difference is rewards and fees, which are not interest earned",
                        failure=False,
                    )

            facts.append(builder.usd("tvl", subject, supplied))

            if utilization is not None:
                facts.append(builder.ratio("utilization", subject, min(utilization, 1.0)))
                if is_fully_utilized(utilization):
                    self.diagnose(
                        market_name,
                        f"utilization is {utilization:.0%}",
                        "every supplied dollar is lent out, so a withdrawal waits for a "
                        "borrower to repay - treat this position as hard to exit",
                        failure=False,
                    )

        if wanted and not matched:
            self.diagnose(
                "market universe",
                f"no Morpho market above ${MIN_SUPPLY_USD:,.0f} lends {sorted(wanted)}",
                "Morpho is not an option for these assets this tick",
                failure=False,
            )
        return facts

    async def _markets(self, chain_id: int) -> list[dict] | None:
        """The market list, or None with a diagnosis explaining why not."""
        try:
            response = await self.client.post(
                API_URL,
                json={
                    "query": MARKETS_QUERY,
                    "variables": {"first": MARKET_LIMIT, "chainIds": [chain_id]},
                },
                headers={"Content-Type": "application/json", "Accept": "application/json"},
            )
        except Exception as exc:  # noqa: BLE001 - a stray error must not kill the source
            # `Exception`, not a tuple of the two types that came to mind: a
            # stray RuntimeError took the gas source down for exactly that
            # reason in Wave 1.
            self.diagnose("Morpho API", explain_exception(exc), OTHERS_UNAFFECTED)
            return None

        if response.status_code >= 400:
            self.diagnose(
                "Morpho API", f"HTTP {response.status_code}", OTHERS_UNAFFECTED
            )
            return None

        try:
            body = response.json()
        except ValueError:
            self.diagnose("Morpho API", "the response was not JSON", OTHERS_UNAFFECTED)
            return None

        if body.get("errors"):
            first = (body["errors"] or [{}])[0].get("message", "unknown")
            self.diagnose("Morpho API", f"GraphQL error: {first}", OTHERS_UNAFFECTED)
            return None

        items = ((body.get("data") or {}).get("markets") or {}).get("items")
        if not items:
            self.diagnose(
                "Morpho API", "returned no markets", OTHERS_UNAFFECTED, failure=False
            )
            return None
        return list(items)

    async def close(self) -> None:
        if self._owns_client:
            await self._http.aclose()


def make_morpho_source(settings: Settings) -> MorphoSource:
    """Registration factory. Referenced from `sources/__init__.py`."""
    return MorphoSource(settings)


__all__ = ["MorphoSource", "make_morpho_source", "MARKETS_QUERY", "MIN_SUPPLY_USD"]
