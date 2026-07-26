"""What the vault is earning right now, as opposed to what it has earned.

## Why this is not the performance summary

`PerformanceSummary.annualized_return_pct` is the vault's *realised* return, and
it is deliberately `None` until the series spans at least a day — annualising
forty minutes of a two-point series is a meaningless number rather than a small
one, and the summary refuses to print one.

That is correct and it leaves a real hole: on a fresh deployment, and for the
whole of a demo, **every yield figure on the vault page is blank** even though
the vault is visibly earning. A depositor looking at 20,000 USDC supplied to
Aave wants to know the rate on it, and that rate is knowable immediately — it
just is not a fact about our history.

So this is the forward-looking figure: the APY of the positions the vault holds
*now*, from the same live yield facts the agent reads when it decides. No
history required, so it is populated on the first tick rather than the second
day.

## How a holding is matched to a rate

A supplied position shows up as a receipt token — `aBasUSDC` carrying
`represents: "USDC"` and `committed_to_venue: "aave"`. That pair is the match
key: the protocol says which market, the underlying says which asset. A holding
with no `committed_to_venue` is idle and earns nothing, which is a real answer
and reported as `0.0` rather than omitted — idle capital earning nothing is the
single most decision-relevant fact on the page.

**A position we cannot find a rate for is `None`, never `0.0`.** The two are
completely different claims: one says "this earns nothing", the other says "we
do not know what this earns", and showing the first when we mean the second
understates the vault to its own depositors.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from curator_schema import Fact, VaultState

__all__ = ["PositionYield", "VaultYield", "compute_vault_yield"]

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PositionYield:
    token: str
    symbol: str
    #: The underlying a receipt token represents, or the symbol itself.
    represents: str
    #: Which protocol the position is with. None means idle in the vault.
    venue: str | None
    value_in_asset: int
    #: Fraction, so 0.0351 is 3.51% — the `apy_fraction` convention.
    #: None means no rate was found, which is not the same as zero.
    apy: float | None
    #: The fact this rate came from, so the UI can show provenance rather than
    #: an unsourced number. Same discipline as the decision feed.
    source: str | None
    fact_id: str | None


@dataclass(frozen=True)
class VaultYield:
    vault: str
    positions: list[PositionYield]
    #: Value-weighted across positions whose rate is known. Idle capital counts
    #: at 0%, because a blended yield that silently excluded it would overstate
    #: what the vault earns — the whole point of the idle-capital work.
    weighted_apy: float | None
    #: Share of the book earning a known rate. A blended figure over 30% of the
    #: book is not the vault's yield, and the reader has to be able to see that.
    coverage: float


def _matches(fact: Fact, *, venue: str, underlying: str) -> bool:
    """Whether a yield fact describes this position's market.

    Matched on protocol *and* asset. Protocol alone would happily price a USDC
    position off the WETH market on the same protocol, which is a plausible
    number and the wrong one.
    """
    subject = fact.subject
    protocol = (subject.protocol or "").lower()
    if not protocol or venue.lower() not in protocol:
        return False

    token = (subject.token or "").lower()
    market = (subject.market or "").lower()
    want = underlying.lower()
    return want == token or want in market


def compute_vault_yield(state: VaultState, facts: list[Fact]) -> VaultYield:
    """Blend the current rate on each holding. Never raises."""
    yields = [f for f in facts if f.kind == "yield" and f.unit == "apy_fraction"]

    positions: list[PositionYield] = []
    for holding in state.holdings:
        try:
            value = int(holding.value_in_asset)
        except (TypeError, ValueError):
            value = 0
        if value <= 0:
            # A zero balance is an asset the agent chose not to hold. It belongs
            # in the mandate, not in a statement of what is earning.
            continue

        venue = getattr(holding, "committed_to_venue", None)
        represents = getattr(holding, "represents", None) or holding.symbol

        apy: float | None = None
        source: str | None = None
        fact_id: str | None = None

        if venue is None:
            # Idle. A real rate, and the one worth surfacing.
            apy = 0.0
        else:
            match = next(
                (f for f in yields if _matches(f, venue=venue, underlying=represents)), None
            )
            if match is not None:
                apy, source, fact_id = match.value, match.source, match.id
            else:
                log.info(
                    "no yield fact for %s on %s; reporting unknown rather than zero",
                    represents,
                    venue,
                )

        positions.append(
            PositionYield(
                token=holding.token,
                symbol=holding.symbol,
                represents=represents,
                venue=venue,
                value_in_asset=value,
                apy=apy,
                source=source,
                fact_id=fact_id,
            )
        )

    known = [p for p in positions if p.apy is not None]
    total = sum(p.value_in_asset for p in positions)
    covered = sum(p.value_in_asset for p in known)

    weighted = (
        sum(p.apy * p.value_in_asset for p in known if p.apy is not None) / covered
        if covered > 0
        else None
    )

    return VaultYield(
        vault=state.address,
        positions=sorted(positions, key=lambda p: p.value_in_asset, reverse=True),
        weighted_apy=weighted,
        coverage=(covered / total) if total > 0 else 0.0,
    )
