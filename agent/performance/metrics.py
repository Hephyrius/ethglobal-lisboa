"""Risk figures from a share-price series.

Derived on every request and never stored, so a metric cannot drift from the
series it claims to describe.

## The rule that governs every function here

**Return `None`, never `0.0`, when the series cannot support the figure.**

A volatility of `0.0%` and "we have three data points" render identically in a
UI and mean opposite things. The first is a claim that the vault does not move;
the second is an admission that we do not know yet. A depositor deciding whether
to trust an autonomous agent with money is exactly the reader who must not be
shown the first when we mean the second — so the type is `float | None` and the
UI is expected to print "not enough history".

## Annualization on an event-spaced series

On a pinned anvil fork a block is mined only when a transaction is sent, so
observations are minutes apart during a demo and hours apart overnight. Treating
consecutive observations as equally spaced would make a busy ten minutes look
like ten periods of the same length as an idle night.

So the annualization factor is computed from the **actual elapsed time** the
series spans, not from a count of points. That is the honest reading, and it
also means a two-hour demo does not report an annualized volatility derived from
pretending each tick was a trading day.

The figures are still fragile over short windows, which is what
`MIN_OBSERVATIONS_FOR_RISK` is for.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from datetime import timedelta

from curator_schema import PerformancePoint, PerformanceSummary

__all__ = ["summarize", "MIN_OBSERVATIONS_FOR_RISK"]

#: Below this, volatility and anything derived from it is reported as None.
#:
#: Not a statistical threshold — no small number is one. It is the point below
#: which a figure is more misleading than absent. Eight observations is roughly
#: one demo's worth of ticks, which is also honestly about the least that should
#: ever be shown to someone as a risk number.
MIN_OBSERVATIONS_FOR_RISK = 8

#: Below this the series has no measurable span and even a simple return is
#: meaningless (you need two prices to have a return at all).
MIN_OBSERVATIONS_FOR_RETURN = 2

_SECONDS_PER_YEAR = 365.25 * 24 * 3600

#: Ignore a window shorter than this when annualizing. Two observations one
#: second apart would otherwise scale a rounding error by ~3x10^7.
_MIN_SPAN_SECONDS = 60.0

#: Anything annualized needs at least this much observed span, or it is None.
#:
#: Compounding is arithmetically fine over any span and *honest* over almost
#: none of them. A two-hour demo that earns +0.1% annualizes to +54%, which is
#: not a projection anybody made — it is a rounding artifact wearing a
#: percentage sign, and it would be the largest number on the vault page.
#: Volatility has the same problem in the other direction, and the
#: return-over-volatility ratio inherits both.
#:
#: A day is the shortest span over which the extrapolation is merely optimistic
#: rather than absurd. Below it the UI shows "not enough history", which is true.
_MIN_SPAN_FOR_ANNUALIZATION = 24 * 3600.0


def _price(point: PerformancePoint) -> float | None:
    """Share price as a float, or None if the vault had no shares yet.

    Precision is fine here: a share price is O(1) in base-asset units, so the
    integer is ~10^6 for a 6-decimal asset and nowhere near float64's limit.
    The decimal-string convention exists for *balances*, which really can
    exceed it.
    """
    if point.share_price is None:
        return None
    try:
        value = float(point.share_price)
    except ValueError:
        return None
    return value if value > 0 else None


#: A step larger than this between consecutive observations is not a return.
#:
#: A share price is a slow-moving O(1) quantity. Even a catastrophic vault does
#: not lose 99% between two blocks, and nothing legitimate gains 100×. What does
#: produce a jump like that is a **unit mistake** — and one already happened:
#: live points were recorded as a 1e18-scaled ratio while backfilled points used
#: base-asset units, and the vault page reported a return of
#: 99,965,347,459,900% on a vault that was down 3 bps.
#:
#: That bug is fixed at the source (`recorder.share_price_in_asset_units`). This
#: is the backstop, because the failure mode is silent, catastrophic in
#: presentation, and the series is assembled from three writers — a tick, a
#: sampler and a chain backfill — any of which could drift again.
_IMPLAUSIBLE_STEP = 100.0


def _priced(points: Sequence[PerformancePoint]) -> list[tuple[PerformancePoint, float]]:
    """Points that actually have a price, oldest first, on one consistent scale.

    Where an implausible step is found, the series is **truncated to the most
    recent consistent run** rather than repaired. Two reasons: the newest points
    are the ones a reader is asking about, and guessing a rescale factor would
    turn a visible bug into an invisible one.
    """
    out = [(p, price) for p in points if (price := _price(p)) is not None]
    out.sort(key=lambda pair: pair[0].timestamp)
    if len(out) < 2:
        return out

    cut = 0
    for index in range(1, len(out)):
        previous, current = out[index - 1][1], out[index][1]
        ratio = max(current / previous, previous / current)
        if ratio >= _IMPLAUSIBLE_STEP:
            logging.getLogger(__name__).warning(
                "share price jumped %.3gx between %s and %s — a unit mismatch, not a "
                "return; dropping everything before it",
                ratio,
                out[index - 1][0].timestamp,
                out[index][0].timestamp,
            )
            cut = index
    return out[cut:]


def _return_over(
    priced: list[tuple[PerformancePoint, float]], window: timedelta
) -> float | None:
    """Return from the oldest observation inside `window` to the newest.

    Anchored on the oldest point *within* the window rather than the point
    nearest the window's start edge. An event-spaced series often has nothing
    near the edge, and silently reaching outside the window to find one would
    report a 7-day return computed over 30 days.
    """
    if len(priced) < MIN_OBSERVATIONS_FOR_RETURN:
        return None

    cutoff = priced[-1][0].timestamp - window
    inside = [pair for pair in priced if pair[0].timestamp >= cutoff]
    if len(inside) < MIN_OBSERVATIONS_FOR_RETURN:
        return None

    start, end = inside[0][1], inside[-1][1]
    return (end - start) / start


def _max_drawdown(priced: list[tuple[PerformancePoint, float]]) -> float | None:
    """Largest peak-to-trough fall, as a positive fraction.

    The number a depositor actually feels, and the one a headline return hides:
    a vault that ends the day +2% having been -15% at lunch is not the same
    product as one that crept up all day.
    """
    if len(priced) < MIN_OBSERVATIONS_FOR_RETURN:
        return None

    peak = priced[0][1]
    worst = 0.0
    for _, price in priced:
        peak = max(peak, price)
        worst = max(worst, (peak - price) / peak)
    return worst


def _log_returns(priced: list[tuple[PerformancePoint, float]]) -> list[float]:
    return [
        math.log(curr / prev)
        for (_, prev), (_, curr) in zip(priced, priced[1:], strict=False)
        if prev > 0 and curr > 0
    ]


def _span_seconds(priced: list[tuple[PerformancePoint, float]]) -> float:
    return (priced[-1][0].timestamp - priced[0][0].timestamp).total_seconds()


def _annualized_return(priced: list[tuple[PerformancePoint, float]]) -> float | None:
    """Compound the observed return out to a year over the real elapsed span."""
    if len(priced) < MIN_OBSERVATIONS_FOR_RETURN:
        return None
    span = _span_seconds(priced)
    if span < max(_MIN_SPAN_SECONDS, _MIN_SPAN_FOR_ANNUALIZATION):
        return None

    total = priced[-1][1] / priced[0][1]
    if total <= 0:
        return None
    periods = _SECONDS_PER_YEAR / span
    try:
        # Guard the exponent: a 5-minute span implies ~10^5 periods, and a 1%
        # move compounded that many times overflows to inf and renders as a
        # nonsense headline number rather than an honest refusal.
        if abs(math.log(total) * periods) > 20:
            return None
        return total**periods - 1
    except (OverflowError, ValueError):
        return None


def _annualized_volatility(priced: list[tuple[PerformancePoint, float]]) -> float | None:
    """Stdev of log returns, scaled by the real observation frequency."""
    if len(priced) < MIN_OBSERVATIONS_FOR_RISK:
        return None
    returns = _log_returns(priced)
    if len(returns) < MIN_OBSERVATIONS_FOR_RISK - 1:
        return None

    span = _span_seconds(priced)
    if span < max(_MIN_SPAN_SECONDS, _MIN_SPAN_FOR_ANNUALIZATION):
        return None

    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    per_observation = math.sqrt(variance)

    # Observations per year, from the real spacing rather than a period count.
    observations_per_year = _SECONDS_PER_YEAR / (span / len(returns))
    return per_observation * math.sqrt(observations_per_year)


def summarize(vault: str, points: Sequence[PerformancePoint]) -> PerformanceSummary:
    """Every figure the vault page shows, or None where we cannot honestly say."""
    del vault  # kept in the signature so callers read as summarize(vault, points)

    if not points:
        return PerformanceSummary(observations=0)

    ordered = sorted(points, key=lambda p: p.timestamp)
    priced = _priced(ordered)
    latest = ordered[-1]

    base = {
        "observations": len(ordered),
        "first_at": ordered[0].timestamp,
        "last_at": latest.timestamp,
        "share_price": latest.share_price,
        "total_assets": latest.total_assets,
    }

    if len(priced) < MIN_OBSERVATIONS_FOR_RETURN:
        # One priced point is a position, not a performance.
        return PerformanceSummary(**base)

    total_return = (priced[-1][1] - priced[0][1]) / priced[0][1]
    annualized = _annualized_return(priced)
    volatility = _annualized_volatility(priced)

    risk_adjusted = None
    if annualized is not None and volatility is not None and volatility > 1e-9:
        risk_adjusted = annualized / volatility

    return PerformanceSummary(
        **base,
        return_pct=total_return,
        return_24h_pct=_return_over(priced, timedelta(hours=24)),
        return_7d_pct=_return_over(priced, timedelta(days=7)),
        annualized_return_pct=annualized,
        volatility_pct=volatility,
        max_drawdown_pct=_max_drawdown(priced),
        risk_adjusted_return=risk_adjusted,
    )
