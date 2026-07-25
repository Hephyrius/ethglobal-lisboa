"""Turning an observed `VaultState` into a `PerformancePoint`.

One function doing one conversion, in its own module because the *when* matters
and is worth stating once: this is called from the decision cycle on every tick
and from the sampler in between, and both hand it the same `VaultState` the
agent itself reasoned over. The chart and the agent therefore see identical
numbers by construction rather than by agreement.

## Why `share_price` is copied verbatim rather than recomputed

`VaultState.share_price` comes from the vault's own `convertToAssets(1e18)` and
carries the 6-decimal convention (request #27: a price of 1.0025 is `1002506`,
not `1e18`). Recomputing it here from `total_assets / total_supply` would drop
the virtual-share offset that ERC-4626 rounding depends on, and produce a curve
that disagrees with the contract in the fourth decimal — the kind of discrepancy
that is invisible until someone compares the chart to a withdrawal.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from curator_schema import AllocationSlice, PerformancePoint, VaultState

from ..clock import utcnow

__all__ = ["point_from_state"]


def point_from_state(
    state: VaultState,
    *,
    at: datetime | None = None,
    source: Literal["tick", "sampler", "backfill"] = "tick",
) -> PerformancePoint:
    """One observation, from the state the agent was given.

    `at` overrides the clock so the backfill can stamp a point with the block's
    own timestamp rather than the moment it was reconstructed. Getting that
    wrong would pile the entire reconstructed history onto a single instant and
    produce a vertical line where the curve should be.
    """
    return PerformancePoint(
        timestamp=at or utcnow(),
        block_number=state.block_number,
        share_price=state.share_price,
        total_assets=state.total_assets,
        total_supply=state.total_supply,
        allocation=[
            AllocationSlice(
                symbol=holding.symbol,
                value_in_asset=holding.value_in_asset,
                committed_to_venue=holding.committed_to_venue,
            )
            for holding in state.holdings
            # A holding with no valuation cannot be plotted as a share of the
            # vault. Dropping it is right: guessing a value would put a wrong
            # slice in the allocation chart, and the missing slice is visible
            # as the difference between the stack and total_assets.
            if holding.value_in_asset is not None
        ],
        source=source,
    )
