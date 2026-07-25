"""Turning an observed `VaultState` into a `PerformancePoint`.

One function doing one conversion, in its own module because the *when* matters
and is worth stating once: this is called from the decision cycle on every tick
and from the sampler in between, and both hand it the same `VaultState` the
agent itself reasoned over. The chart and the agent therefore see identical
numbers by construction rather than by agreement.

## `share_price` is RESCALED here, and getting this wrong cost a 1e12 error

There are two live conventions for "share price" in this system and they differ
by exactly 10^12:

| Source | Value for a price of 0.999653 | Convention |
|---|---|---|
| `VaultState.share_price` (`Web3VaultClient`) | `999653474600000000` | dimensionless ratio × 1e18 |
| `convertToAssets(1e18)` (the contract, and the backfill) | `999653` | **base-asset units** |

`PerformancePoint.share_price` is specified as the second — "assets per whole
share, in BASE-ASSET decimals" (`performance.schema.json`). The first version of
this file copied `VaultState.share_price` through verbatim, with a comment
confidently asserting it already carried that convention. It does not.

The result was a series where backfilled points read `999653` and live points
read `999653474600000000`, and the vault page reported a **return of
99,965,347,459,900%** on a vault that was down 3 bps. 10^18 / 10^6 = 10^12 —
the same discrepancy `VaultStats.tsx` documents from the UI side and cross-lane
request #12 raised from the schema side. It is not a new trap; it is the known
one, walked into from a third direction.

So: convert explicitly, from a named constant, with the arithmetic in one place.
Not with a magnitude heuristic — "if it looks too big, divide" is how a real
1000× move becomes a silent rescale.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Literal

from curator_schema import AllocationSlice, PerformancePoint, VaultState

from ..chain.vault_client import _SHARE_PRICE_SCALE
from ..clock import utcnow

__all__ = ["point_from_state", "share_price_in_asset_units"]

log = logging.getLogger(__name__)


def share_price_in_asset_units(state: VaultState) -> str | None:
    """`VaultState.share_price` (1e18 ratio) → base-asset units.

    `999653474600000000` with a 6-decimal asset becomes `999653`.

    Returns None when the vault has no price to report, which is a real state —
    before the first deposit `total_supply` is 0 and a share of nothing has no
    price. Zero would be a claim that the share is worthless.
    """
    if state.share_price is None:
        return None
    try:
        ratio = int(state.share_price)
    except ValueError:
        log.warning("unparseable share_price %r on %s", state.share_price, state.address)
        return None
    if ratio <= 0:
        return None

    # Multiply before dividing: the other order throws away every digit that
    # matters, since the ratio is O(1e18) and the divisor is 1e18.
    return str(ratio * (10**state.asset_decimals) // _SHARE_PRICE_SCALE)


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
        share_price=share_price_in_asset_units(state),
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
