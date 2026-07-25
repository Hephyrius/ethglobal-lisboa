"""Market-level views over a `MarketSnapshot`.

`MarketSnapshot` is a flat list of facts because that is what keeps it
source-agnostic — but "flat list of facts" is not how a human or an LLM thinks
about a lending market. This module pivots facts back into rows without
putting a provider-shaped type back into the frozen schema.

Deliberately the *only* place that pivot exists. The MCP server, the CLI and
anything else that wants a table share it, so the reusable product an outside
agent installs runs the same code as our demo path.

Pivoting is a pure function of a snapshot, so it works identically on live
gateway data and on `packages/schema/fixtures/market-snapshot.json`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median

from curator_schema.models import Fact, MarketSnapshot

from .config import Settings
from .registry import Registry, build_registry

#: Capabilities, expressed as `Fact.kind`s from the frozen schema — never as
#: provider names. `snapshot_for` resolves these through the registry, so a
#: newly registered source that declares `provides = ("price",)` starts serving
#: price queries with no edit to this file. Naming providers here instead would
#: quietly make "adding a source is one line" false.
MARKET_KINDS: tuple[str, ...] = ("yield", "tvl", "utilization", "liquidity")
PRICE_KINDS: tuple[str, ...] = ("price",)


@dataclass
class MarketRow:
    """One lending market, assembled from the facts that describe it."""

    protocol: str
    market: str
    chain: str = "base"
    supply_apy: float | None = None
    tvl_usd: float | None = None
    utilization: float | None = None
    #: Ids of the facts this row was built from. Carried through so a caller
    #: can cite them — `AllocationDecision.facts_used` expects exactly these,
    #: and it is how the dApp draws data → reasoning → transaction.
    fact_ids: list[str] = field(default_factory=list)
    #: Provenance, plural: a row can legitimately merge facts from two sources.
    sources: list[str] = field(default_factory=list)

    @property
    def supply_apy_pct(self) -> float | None:
        """APY as a percentage, for display only. Never for arithmetic."""
        return None if self.supply_apy is None else self.supply_apy * 100.0

    def to_dict(self) -> dict:
        return {
            "protocol": self.protocol,
            "market": self.market,
            "chain": self.chain,
            "supply_apy": self.supply_apy,
            "supply_apy_pct": self.supply_apy_pct,
            "tvl_usd": self.tvl_usd,
            "utilization": self.utilization,
            "fact_ids": self.fact_ids,
            "sources": self.sources,
        }


@dataclass
class PoolRow:
    """One DEX pool's liquidity."""

    protocol: str
    pair: list[str]
    chain: str = "base"
    liquidity_usd: float | None = None
    fact_ids: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "protocol": self.protocol,
            "pair": self.pair,
            "chain": self.chain,
            "liquidity_usd": self.liquidity_usd,
            "fact_ids": self.fact_ids,
            "sources": self.sources,
        }


def _record(row_sources: list[str], fact: Fact) -> None:
    if fact.source not in row_sources:
        row_sources.append(fact.source)


def pivot_markets(snapshot: MarketSnapshot) -> list[MarketRow]:
    """Group lending facts into one row per (protocol, market).

    Sorted by APY descending, with unknown APYs last — the ordering every
    consumer wants first, applied once here rather than in each of them.
    """
    rows: dict[tuple[str, str], MarketRow] = {}

    for fact in snapshot.facts:
        if fact.kind not in ("yield", "tvl", "utilization"):
            continue
        protocol = fact.subject.protocol
        if not protocol:
            continue
        market = fact.subject.market or fact.subject.token or "—"
        row = rows.setdefault(
            (protocol, market),
            MarketRow(protocol=protocol, market=market, chain=fact.subject.chain),
        )
        row.fact_ids.append(fact.id)
        _record(row.sources, fact)

        if fact.kind == "yield" and fact.unit == "apy_fraction":
            row.supply_apy = fact.value
        elif fact.kind == "tvl" and fact.unit == "usd":
            row.tvl_usd = fact.value
        elif fact.kind == "utilization" and fact.unit == "ratio":
            row.utilization = fact.value

    return sorted(
        rows.values(),
        key=lambda r: (r.supply_apy is None, -(r.supply_apy or 0.0), r.protocol),
    )


def pivot_pools(snapshot: MarketSnapshot) -> list[PoolRow]:
    """Group liquidity facts into one row per (protocol, pair)."""
    rows: dict[tuple[str, str], PoolRow] = {}
    for fact in snapshot.facts:
        if fact.kind != "liquidity":
            continue
        protocol = fact.subject.protocol or "—"
        pair = list(fact.subject.pair or [])
        key = (protocol, "/".join(pair))
        row = rows.setdefault(
            key, PoolRow(protocol=protocol, pair=pair, chain=fact.subject.chain)
        )
        row.fact_ids.append(fact.id)
        _record(row.sources, fact)
        if fact.unit == "usd":
            row.liquidity_usd = fact.value
    return sorted(rows.values(), key=lambda r: -(r.liquidity_usd or 0.0))


#: Relative spread between independent price sources beyond which they are
#: treated as disagreeing. Chainlink (oracle) and the Token API (executed dex
#: swaps) measure price by mechanically unrelated means, so they should track
#: closely on a liquid asset — live they were 0.06% apart. A gap materially
#: wider than that is a signal in itself: a stale oracle, a manipulated pool,
#: or a genuinely dislocated market. All three are things a curator should act
#: on rather than average away.
PRICE_DISAGREEMENT_PCT = 1.0


def prices(snapshot: MarketSnapshot) -> dict[str, dict]:
    """symbol → consensus price plus every independent observation of it.

    Deliberately not "last source wins". Two sources pricing the same asset by
    different mechanisms is the point of registering both, and collapsing them
    to one number throws away the only cross-check the agent has.

    `price_usd` is the median so a single bad source cannot set it; the
    individual readings stay in `observations` so a caller can show its work,
    and `disagreement` flags when they are far enough apart to be worth saying
    out loud.
    """
    grouped: dict[str, list[Fact]] = {}
    for fact in snapshot.facts:
        if fact.kind != "price" or fact.unit != "usd":
            continue
        symbol = (fact.subject.token or "").upper()
        if symbol:
            grouped.setdefault(symbol, []).append(fact)

    out: dict[str, dict] = {}
    for symbol, facts in grouped.items():
        # Stable ordering so the "primary" reading never flips between runs.
        facts = sorted(facts, key=lambda f: f.source)
        values = [f.value for f in facts]
        consensus = median(values)
        spread_pct = (
            (max(values) - min(values)) / consensus * 100.0 if consensus and len(values) > 1
            else 0.0
        )
        out[symbol] = {
            "symbol": symbol,
            "price_usd": consensus,
            # Kept for consumers written against the single-source shape.
            "fact_id": facts[0].id,
            "source": facts[0].source,
            "observed_at": facts[0].observed_at.isoformat(),
            "confidence": facts[0].confidence,
            "sources": [f.source for f in facts],
            "observations": [
                {
                    "source": f.source,
                    "price_usd": f.value,
                    "fact_id": f.id,
                    "observed_at": f.observed_at.isoformat(),
                }
                for f in facts
            ],
            "spread_pct": spread_pct,
            "disagreement": spread_pct > PRICE_DISAGREEMENT_PCT,
        }
    return out


def errors_as_dicts(snapshot: MarketSnapshot) -> list[dict]:
    """Degradation, surfaced rather than swallowed.

    Every caller must be able to show what could not be fetched. An agent that
    treats a partial snapshot as complete is the failure mode this whole layer
    is shaped to avoid.
    """
    return [{"source": e.source, "message": e.message} for e in snapshot.errors]


# ── async convenience: take a snapshot and pivot it in one call ───────────


async def snapshot_for(
    assets: list[str],
    *,
    kinds: tuple[str, ...] | list[str] = MARKET_KINDS,
    permitted: list[str] | None = None,
    settings: Settings | None = None,
    registry: Registry | None = None,
) -> MarketSnapshot:
    """Snapshot from whichever sources can supply `kinds`.

    `permitted` is the mandate's `permitted_data_sources`. When given it is
    intersected with the capability lookup, so access control still wins: a
    source that could answer but was not granted is never consulted. When
    omitted — the MCP server's case, where there is no mandate — every capable
    registered source is used.
    """
    own = registry is None
    reg = registry or build_registry(settings)
    try:
        capable = reg.sources_providing(*kinds)
        selected = [k for k in capable if k in set(permitted)] if permitted else capable
        return await reg.snapshot(selected, list(assets))
    finally:
        if own:
            await reg.aclose()


__all__ = [
    "MarketRow",
    "PoolRow",
    "pivot_markets",
    "pivot_pools",
    "prices",
    "errors_as_dicts",
    "snapshot_for",
    "MARKET_KINDS",
    "PRICE_KINDS",
]
