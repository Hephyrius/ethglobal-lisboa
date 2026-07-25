"""Bounds on what a market number can credibly be.

Permissionless chains index permissionless markets, and anyone can create one
whose numbers are nonsense. Three real readings from live sources:

    Uniswap V3 Base   WETH/SLUG        TVL $130,563,280,368,069,680,230,825,984
    Morpho Base       USDC/HERMES      supply APY 297,892.52%, utilization 1.00
    Aerodrome         USDC-CBBTC       "91.14% APY", of which 68% was emissions

None of these is a bug in our code. Each is a real number a real protocol
really reports, and each would be read by an agent as the best opportunity on
the board. The HERMES market is the sharpest: $54M supplied, utilization pinned
at exactly 1.00, so a curator that chased that yield could not have exited.

The guards live here rather than in each source because three sources now need
the same two thresholds, and a bound that differs by source is worse than no
bound — it makes the same market plausible or not depending on who reported it.

**Dropped, never clamped.** Clamping 297,892% to 100% reports a fabricated
number as real. A missing fact makes an agent say "I could not price this";
a clamped one makes it say something false with confidence.
"""

from __future__ import annotations

#: Above this, an "APY" is a token emission, a bootstrapping incentive, a
#: runaway interest-rate curve on a market at full utilization, or an indexing
#: error. It is never interest a depositor can expect to earn.
MAX_PLAUSIBLE_APY = 1.0  # 100%

#: Ceiling on any USD figure. Total DeFi TVL is order $1e11, so anything above
#: this is a token that mispriced itself rather than an unusually large market.
MAX_PLAUSIBLE_USD = 1e11

#: A market at or above this cannot reliably be exited: every supplied dollar
#: is lent out, so a withdrawal waits for a borrower to repay. Not a bound that
#: drops the fact — utilization *is* the signal — but sources flag it, because
#: a high headline rate at full utilization is the shape of a trap.
FULL_UTILIZATION = 0.995


def implausible_apy(fraction: float | None) -> bool:
    """True if this cannot be a real deposit yield. `fraction`, not percent."""
    return fraction is not None and (fraction < 0 or fraction > MAX_PLAUSIBLE_APY)


def implausible_usd(value: float | None) -> bool:
    """True if this USD figure is fabricated rather than merely large."""
    return value is not None and (value < 0 or value > MAX_PLAUSIBLE_USD)


def is_fully_utilized(utilization: float | None) -> bool:
    """True if the market has no idle liquidity to withdraw against."""
    return utilization is not None and utilization >= FULL_UTILIZATION


__all__ = [
    "MAX_PLAUSIBLE_APY",
    "MAX_PLAUSIBLE_USD",
    "FULL_UTILIZATION",
    "implausible_apy",
    "implausible_usd",
    "is_fully_utilized",
]
