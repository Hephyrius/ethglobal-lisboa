"""Lane D — venue adapters.

Two execution paths, deliberately non-overlapping:

* **Uniswap** (taker) rotates *what the vault holds*.
* **1inch Aqua + SwapVM** (maker) *holds* a market-making position, with tokens
  never leaving the vault.

Both implement the frozen `curator_schema.ports.Venue` protocol and emit
`ExecutionPlan` objects. Neither ever touches `contracts/` — the vault exposes
one generic allowlisted `execute(target, value, data)` and never learns what a
venue is, which is the seam that lets Lanes A and D build independently.

See README.md for the integration surface.
"""

from .capabilities import (
    VenueCapability,
    capabilities,
    capability,
    manifest,
    probe,
)
from .errors import (
    NoRouteError,
    PlanValidationError,
    UnsupportedIntentError,
    VenueAPIError,
    VenueError,
)
from .registry import VENUES, get_venue

__all__ = [
    "VENUES",
    "get_venue",
    "VenueCapability",
    "capabilities",
    "capability",
    "manifest",
    "probe",
    "VenueError",
    "VenueAPIError",
    "NoRouteError",
    "UnsupportedIntentError",
    "PlanValidationError",
]
