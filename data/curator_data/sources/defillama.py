"""DefiLlama — yields across every Base protocol, in one unauthenticated call.

## What this is for, and what it deliberately is not

Before this, the agent compared Aave against Moonwell and called it a
multi-protocol comparison. Two protocols is not a market. `https://yields.llama.fi/pools`
returns every tracked pool on every chain, and the Base slice alone covers
dozens of protocols — Aerodrome, Morpho, Compound, Fluid, Extra, Seamless and
more — with APY and TVL for each, for free and with no credential.

**This is breadth, not depth, and the distinction is load-bearing.** The
Messari and Aave subgraph sources stay the sources of record: they are
verifiable, they are queried per-protocol against indexed chain state, and they
are what The Graph integration actually is. DefiLlama is a third-party
aggregator that reports numbers it computed from someone else's data, so its
facts carry `confidence` below the subgraph sources' and the prompt is told to
prefer a subgraph when the two disagree.

Registering it as an ordinary source rather than special-casing it is the point:
the registry does not know that one of its providers is an aggregator, and the
mandate can grant or withhold it exactly like any other key.

## Filtering, and why the thresholds are not decoration

The unfiltered Base slice is hundreds of pools, most of them dust farms with
four-figure TVL and five-figure APY. Handing those to a small model is not
giving it more information, it is inviting it to chase the largest number on the
page into a pool it cannot exit. So:

  * TVL floor — a pool the vault could not enter without being most of it
  * APY ceiling — above this the number is a farm emission or a bug, not a yield
  * top-N by TVL — the deepest markets, which is where a vault this size lives
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from curator_schema.models import Fact

from ..config import Settings
from ..facts import FactBuilder
from ..http import LoopBoundClient
from ..ports import BaseSource

logger = logging.getLogger(__name__)

POOLS_URL = "https://yields.llama.fi/pools"

#: DefiLlama's name for Base.
CHAIN_NAME = "Base"

#: Pools below this are not investable for a vault of any size — entering one
#: would make the vault most of the pool, and exiting would move the price.
MIN_TVL_USD = 1_000_000.0

#: Above this an "APY" is a token emission, a bootstrapping incentive, or an
#: indexing error. Dropped rather than clamped: clamping reports a made-up
#: number as real, and this feeds an agent that allocates by comparing yields.
MAX_PLAUSIBLE_APY = 1.0  # 100%

#: Deepest N pools kept, after filtering.
TOP_N = 25

#: Below the subgraph sources on purpose. A number computed by an aggregator
#: from someone else's indexer is a weaker claim than one read from an indexed
#: subgraph, and `Fact.confidence` is where that belongs.
AGGREGATOR_CONFIDENCE = 0.7


class DefiLlamaSource(BaseSource):
    """Yields and TVL for the deepest Base pools, from a free aggregator."""

    key = "defillama"
    provides = ("yield", "tvl")
    description = (
        "Yields and TVL across every protocol DefiLlama tracks on Base — dozens, in one "
        "unauthenticated request. Breadth to complement the subgraph sources' depth: an "
        "aggregator's numbers, so its facts carry lower confidence than an indexed subgraph's."
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
        wanted = {a.strip().upper() for a in assets if a and a.strip()}

        try:
            response = await self.client.get(POOLS_URL, headers={"Accept": "application/json"})
        except httpx.HTTPError as exc:
            raise RuntimeError(f"DefiLlama unreachable: {type(exc).__name__}: {exc}") from exc

        if response.status_code >= 400:
            raise RuntimeError(f"DefiLlama returned HTTP {response.status_code}")

        try:
            body: Any = response.json()
        except ValueError as exc:
            raise RuntimeError("DefiLlama returned non-JSON") from exc

        rows = body.get("data") if isinstance(body, dict) else None
        if not rows:
            raise RuntimeError("DefiLlama returned no pools")

        candidates = [row for row in rows if self._is_relevant(row, wanted)]
        candidates.sort(key=lambda row: float(row.get("tvlUsd") or 0), reverse=True)
        kept = candidates[:TOP_N]

        if len(candidates) > TOP_N:
            # Never truncate silently. A model told "here is the market" when it
            # was shown a quarter of it will reason confidently about a subset.
            self.remark(
                f"{len(candidates)} Base pools matched; showing the {TOP_N} deepest by TVL"
            )

        builder = FactBuilder(self.key, chain=self.settings.chain)
        facts: list[Fact] = []
        for row in kept:
            facts.extend(self._facts_for(row, builder))

        if not facts:
            self.remark(
                f"no Base pool above ${MIN_TVL_USD:,.0f} TVL matched "
                f"{sorted(wanted) if wanted else 'any asset'}"
            )
        return facts

    def _is_relevant(self, row: dict, wanted: set[str]) -> bool:
        if row.get("chain") != CHAIN_NAME:
            return False

        tvl = row.get("tvlUsd")
        if not isinstance(tvl, int | float) or tvl < MIN_TVL_USD:
            return False

        if not wanted:
            return True

        # `symbol` is the pool's composition — "USDC", "WETH-USDC", "CBBTC".
        # A pool counts if it contains any asset the mandate permits; a vault
        # that may hold USDC has a legitimate interest in a USDC pair.
        symbol = str(row.get("symbol") or "").upper()
        legs = {leg.strip() for leg in symbol.replace("/", "-").split("-") if leg.strip()}
        return bool(legs & wanted)

    def _facts_for(self, row: dict, builder: FactBuilder) -> list[Fact]:
        protocol = str(row.get("project") or "unknown")
        market = str(row.get("symbol") or "")
        subject = builder.subject(protocol=protocol, market=market)

        facts: list[Fact] = []

        if (yield_fact := self._yield_fact(row, subject, builder)) is not None:
            facts.append(yield_fact)

        tvl = row.get("tvlUsd")
        if isinstance(tvl, int | float) and tvl > 0:
            facts.append(
                builder.usd("tvl", subject, float(tvl), confidence=AGGREGATOR_CONFIDENCE)
            )

        return facts

    def _yield_fact(self, row: dict, subject, builder: FactBuilder) -> Fact | None:
        """`apyBase` if there is one, and never a headline that is mostly emissions.

        This is the most important judgement in the file. The first live run
        surfaced `aerodrome-slipstream USDC-CBBTC at 91.14%` and
        `extra-finance USDC-AERO at 20.65%` above `aave-v3 USDC at 3.50%`, and
        an agent told to pursue yield would read that as Aave being 26x worse.

        It is not. Those headline figures are `apy = apyBase + apyReward`, and
        the reward leg is a token emission — a bet on the emitted token's price,
        with a different risk profile and an expiry date, not interest. Handing
        a small model a column where "yield" silently means two different things
        is the same failure as letting it read pool depth as an APY.

        So the fact is `apyBase` where DefiLlama reports one. An arbitrary cap
        was the alternative and it is worse: it would encode a guess about what
        counts as too good, and it would still show a 40% emission farm as a
        yield. This uses the distinction the data already carries.
        """
        base = row.get("apyBase")
        total = row.get("apy")
        protocol = subject.protocol or "unknown"
        market = subject.market or ""

        if isinstance(base, int | float):
            fraction = float(base) / 100.0  # DefiLlama reports percent
            if isinstance(total, int | float) and total - base > 1.0:
                self.remark(
                    f"{protocol} {market}: reporting its {base:.2f}% base yield, not the "
                    f"{total:.2f}% headline — the difference is token emissions, which is a "
                    f"bet on the emitted token rather than interest"
                )
        elif isinstance(total, int | float):
            # No split available. Use the headline but say so, rather than
            # dropping a real pool or presenting emissions as interest.
            fraction = float(total) / 100.0
            self.remark(
                f"{protocol} {market}: {total:.2f}% is a headline APY with no base/reward "
                f"split published, so it may include token emissions"
            )
        else:
            return None

        if fraction <= 0:
            return None
        if fraction > MAX_PLAUSIBLE_APY:
            self.remark(
                f"{protocol} {market} reports {fraction:.0%} — dropped as an indexing error "
                f"rather than shown as a yield"
            )
            return None

        return builder.apy_from_fraction(subject, fraction, confidence=AGGREGATOR_CONFIDENCE)

    async def close(self) -> None:
        if self._owns_client:
            await self._http.aclose()


def make_defillama_source(settings: Settings) -> DefiLlamaSource:
    """Registration factory. Referenced from `sources/__init__.py`."""
    return DefiLlamaSource(settings)


__all__ = ["DefiLlamaSource", "make_defillama_source", "MIN_TVL_USD", "TOP_N"]
