"""Trimming a series to a requested window.

Its own module because the edge case is easy to get wrong and expensive when it
is: **an empty window must not silently become an empty chart.**

On an event-spaced series (a pinned fork mines a block only when a transaction
is sent) a vault can legitimately have no observations at all in the last 24
hours while having a perfectly good month of history. Filtering to `[]` and
handing that to `summarize()` produces "no data" on a vault that has plenty —
so a window that would come back empty falls back to the most recent
observations instead, which is the honest answer to "show me the last day" when
the last day contains nothing.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta

from curator_schema import PerformancePoint

from ..clock import to_utc, utcnow

__all__ = ["WINDOWS", "window_points"]

#: Accepted `?window=` values. "all" is the default and always valid.
WINDOWS: dict[str, timedelta | None] = {
    "1h": timedelta(hours=1),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
    "all": None,
}

#: When a window contains nothing, show at least this many recent points rather
#: than an empty chart.
_FALLBACK_POINTS = 24


def window_points(
    points: Sequence[PerformancePoint], window: str = "all"
) -> list[PerformancePoint]:
    """Points inside `window`, oldest first.

    Anchored on **now**, not on the last observation. Anchoring on the last
    observation would make a stale vault's "last 24 hours" mean the 24 hours
    before it stopped updating, which reads as current data and is not.
    """
    ordered = sorted(points, key=lambda p: to_utc(p.timestamp))
    span = WINDOWS.get(window.lower(), None)
    if span is None or not ordered:
        return ordered

    cutoff = utcnow() - span
    inside = [p for p in ordered if to_utc(p.timestamp) >= cutoff]
    if inside:
        return inside

    # Nothing in the window. A vault whose last trade was two days ago still has
    # a history worth showing; returning [] would report it as having none.
    return ordered[-_FALLBACK_POINTS:]
