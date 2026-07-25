"""Venue lookup by key.

`Mandate.permitted_venues` names venues as strings ("uniswap", "aqua"), exactly
as `permitted_data_sources` names data sources. Lane B resolves those names
through here instead of importing an adapter directly, so a third venue is a
new module plus one line in `_FACTORIES` — the same extension shape Lane C's
data registry uses, for the same reason.

Adapters are constructed lazily. Building a `UniswapVenue` reads the API key,
and a mandate that never names Uniswap should not require one to be present.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:  # avoids importing every adapter (and its deps) at module load
    from curator_schema.ports import Venue


def _uniswap() -> Venue:
    from .uniswap.venue import UniswapVenue

    return UniswapVenue()


def _aqua() -> Venue:
    from .aqua.venue import AquaVenue

    return AquaVenue()


_FACTORIES: Final[dict[str, Callable[[], Venue]]] = {
    "uniswap": _uniswap,
    "aqua": _aqua,
}

#: Registered keys, for the genesis UI and for validating a mandate.
VENUES: Final[tuple[str, ...]] = tuple(_FACTORIES)

_CACHE: dict[str, Venue] = {}


class UnknownVenueError(KeyError):
    """A mandate named a venue with no adapter."""


def get_venue(key: str, *, cached: bool = True) -> Venue:
    """Resolve a mandate's venue key to a live adapter.

    Cached by default so one client connection pool is reused across ticks;
    pass `cached=False` for an isolated instance (tests, or a second config).
    """
    normalised = key.strip().lower()
    if cached and normalised in _CACHE:
        return _CACHE[normalised]

    try:
        factory = _FACTORIES[normalised]
    except KeyError:
        raise UnknownVenueError(
            f"no venue adapter for {key!r}; registered: {sorted(_FACTORIES)}"
        ) from None

    venue = factory()
    if cached:
        _CACHE[normalised] = venue
    return venue
