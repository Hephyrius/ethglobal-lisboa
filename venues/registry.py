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
    from .config import VenueConfig
    from .uniswap.venue import UniswapVenue

    # Carry the slippage bound from the environment into the adapter. Without
    # this the Uniswap API applies its own 250 bps default and the harness
    # rejects every plan against a tighter mandate ceiling — see cross-lane
    # requests 26 and 32. Set UNISWAP_SLIPPAGE_BPS to the mandate's
    # max_slippage_bps.
    config = VenueConfig.from_env()
    return UniswapVenue(config=config, default_slippage_bps=config.uniswap_slippage_bps)


def _aqua() -> Venue:
    from .aqua.venue import AquaVenue

    return AquaVenue()


def _aave() -> Venue:
    from .aave.venue import AaveVenue

    return AaveVenue()


_FACTORIES: Final[dict[str, Callable[[], Venue]]] = {
    "uniswap": _uniswap,
    "aqua": _aqua,
    # Added in Wave 1. One module plus this line — the same extension shape the
    # data registry uses, exercised on a third real provider. The three venues
    # are deliberately different in kind: Uniswap rotates what the vault holds,
    # Aqua earns fees on what it already holds, Aave earns interest on it.
    "aave": _aave,
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
