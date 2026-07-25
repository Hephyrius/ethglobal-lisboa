"""A synthetic share-price curve for fixture mode.

Lane E has to build a chart, headline return figures, a drawdown badge and an
allocation stack before any vault has real history. This is what they build
against.

## Why it is not a straight line up

A chart component developed against a monotonic series never exercises its
negative-return colour, its drawdown marker, or an axis that has to cross a
starting value. All three would then appear for the first time in front of a
judge. So this curve rises, falls ~2.4% over a stretch in the middle, and
recovers to end up — which is a plausible week for a conservative yield vault
and a much more demanding thing to render.

## Why it is deterministic

No randomness and no clock beyond `utcnow()` for the end anchor, so two
screenshots of fixture mode look the same and a UI regression is visible as a
difference rather than dismissed as noise.

The numbers are shaped like a real vault's and are **not** claimed to be real
anywhere: the mode badge already reads `FIXTURES`, which is the honest signal.
"""

from __future__ import annotations

import math
from datetime import timedelta

from curator_schema import AllocationSlice, PerformancePoint

from ..clock import utcnow

__all__ = ["fixture_curve"]

#: One observation every 30 minutes for a week. Dense enough that the risk
#: figures clear `MIN_OBSERVATIONS_FOR_RISK` and the chart has a real shape.
_INTERVAL = timedelta(minutes=30)
_OBSERVATIONS = 336  # 7 days

_ASSET_DECIMALS = 6
_START_ASSETS = 10_000 * 10**_ASSET_DECIMALS

#: Share price path in basis points of return from inception, sampled at the
#: fractions of the series below. Interpolated linearly between them.
#:
#: Shape: a steady climb, a drawdown of ~240 bps across the middle third (the
#: kind a WETH position produces on a bad afternoon), then a recovery to +180.
_KNOTS: tuple[tuple[float, float], ...] = (
    (0.00, 0.0),
    (0.18, 62.0),
    (0.34, 95.0),
    (0.46, -40.0),
    (0.55, -145.0),
    (0.66, -58.0),
    (0.80, 74.0),
    (0.92, 148.0),
    (1.00, 180.0),
)


#: Tick-to-tick wobble, in bps of price, added on top of the knot path.
#:
#: Without it the curve is piecewise linear, per-observation variance is
#: essentially zero, and the derived volatility comes out near 0% — which makes
#: the risk-adjusted figure explode and the chart look like a bank statement
#: rather than a vault. 8 bps per half-hourly observation lands annualized
#: volatility in the low teens, which is where a conservative USDC/WETH book
#: actually sits.
#:
#: Generated from a golden-angle sinusoid rather than `random`: deterministic,
#: no seed to thread through, and non-repeating over the length of the series.
_WOBBLE_BPS = 8.0


def _wobble_bps(index: int) -> float:
    return _WOBBLE_BPS * math.sin(index * 2.399963229728653)


def _return_bps_at(fraction: float) -> float:
    """Linear interpolation between the knots above."""
    for (x0, y0), (x1, y1) in zip(_KNOTS, _KNOTS[1:], strict=False):
        if fraction <= x1:
            span = x1 - x0
            weight = 0.0 if span == 0 else (fraction - x0) / span
            return y0 + (y1 - y0) * weight
    return _KNOTS[-1][1]


def fixture_curve(vault: str) -> list[PerformancePoint]:
    """A week of half-hourly observations, oldest first."""
    del vault  # the curve is the same for every fixture vault, deliberately

    end = utcnow()
    points: list[PerformancePoint] = []

    for index in range(_OBSERVATIONS):
        fraction = index / (_OBSERVATIONS - 1)
        at = end - _INTERVAL * (_OBSERVATIONS - 1 - index)
        multiplier = 1.0 + (_return_bps_at(fraction) + _wobble_bps(index)) / 10_000

        share_price = int(round(10**_ASSET_DECIMALS * multiplier))
        total_assets = int(round(_START_ASSETS * multiplier))

        # A book that rotates: WETH weight rises into the drawdown and is cut
        # afterwards, so the allocation chart has something to show and the two
        # charts tell a consistent story.
        weth_weight = 0.20 + 0.30 * max(0.0, min(1.0, fraction * 1.4 - 0.1))
        weth_value = int(total_assets * weth_weight)

        points.append(
            PerformancePoint(
                timestamp=at,
                block_number=49_000_000 + index * 30,
                share_price=str(share_price),
                total_assets=str(total_assets),
                total_supply=str(_START_ASSETS * 10**12),  # 18-dec shares, fixed supply
                allocation=[
                    AllocationSlice(
                        symbol="USDC", value_in_asset=str(total_assets - weth_value)
                    ),
                    AllocationSlice(
                        symbol="WETH",
                        value_in_asset=str(weth_value),
                        committed_to_venue="aqua" if fraction > 0.6 else None,
                    ),
                ],
                source="sampler",
            )
        )
    return points
