"""A `Venue` over the golden ExecutionPlan.

Stands in for Lane D until `AGENT_VENUE_REGISTRY` points at the real venues. It
returns the golden plan with the intent's own description attached, so the
decision feed still reads sensibly end-to-end in fixture mode — but the calldata
is the fixture's and must never be submitted to a chain. Live mode is the only
path that produces executable bytes.
"""

from __future__ import annotations

from datetime import timedelta

from curator_schema import ExecutionPlan, VaultState, VenueIntent

from .. import fixtures
from ..clock import utcnow

__all__ = ["FixtureVenue", "FixtureVenueRegistry"]

#: The golden plan carries a fixed `quote_expires_at` of 2026-07-25T14:06:30Z.
#: Since the harness refuses to submit a stale quote, replaying that timestamp
#: would make fixture mode work this morning and silently start rejecting every
#: tick this afternoon. Quotes are re-stamped relative to now, for the same
#: reason the fixture decision feed is.
_QUOTE_TTL = timedelta(seconds=60)


def _describe(intent: VenueIntent) -> str:
    if intent.kind == "swap":
        portion = (
            f"{intent.pct_of_holdings:.0%} of holdings"
            if intent.pct_of_holdings is not None
            else f"{intent.amount_in} base units"
        )
        return f"swap {portion} from {intent.token_in} to {intent.token_out}"
    if intent.kind == "ship":
        return f"ship an Aqua position in {'/'.join(intent.tokens)}"
    return f"dock Aqua strategy {intent.strategy_hash[:10]}…"


class FixtureVenue:
    """One venue's worth of the golden plan."""

    def __init__(self, key: str) -> None:
        self.key = key

    async def plan(self, intent: VenueIntent, vault: VaultState) -> ExecutionPlan:
        golden = fixtures.execution_plan()
        return golden.model_copy(
            update={
                "venue": self.key,
                "expected_effect": _describe(intent),
                "quote_expires_at": utcnow() + _QUOTE_TTL,
            }
        )


class FixtureVenueRegistry:
    """Resolves a venue key to a `Venue`, mirroring how Lane D will publish."""

    def __init__(self) -> None:
        self._venues = {key: FixtureVenue(key) for key in ("uniswap", "aqua")}

    def available(self) -> list[str]:
        return list(self._venues)

    def get(self, key: str) -> FixtureVenue | None:
        return self._venues.get(key)
