"""Exceptions crossing the venue boundary.

Lane B's decision loop catches these to record a failed `AgentAction` rather
than dying mid-tick, so they are part of this lane's public interface and are
documented in README.md.
"""

from __future__ import annotations


class VenueError(Exception):
    """Base for every failure a venue adapter raises. Catch this to keep the
    decision loop alive when a venue cannot produce a plan."""


class VenueAPIError(VenueError):
    """An upstream HTTP API refused or failed the request."""

    def __init__(
        self,
        venue: str,
        status: int,
        *,
        code: str | None = None,
        detail: str | None = None,
    ) -> None:
        self.venue = venue
        self.status = status
        self.code = code
        self.detail = detail
        parts = [f"{venue} API returned HTTP {status}"]
        if code:
            parts.append(f"({code})")
        if detail:
            parts.append(f": {detail}")
        super().__init__(" ".join(parts))


class NoRouteError(VenueError):
    """The venue has no route for this trade. An ordinary market condition, not
    a bug — the harness should record a held/failed action and move on."""


class UnsupportedIntentError(VenueError):
    """This adapter cannot serve the given intent kind. Raised rather than
    silently returning an empty plan, which would look like success."""


class PlanValidationError(VenueError):
    """A plan was built that would revert on-chain — typically a step target
    outside the vault allowlist. Caught here so the failure names the seam
    instead of surfacing as an opaque revert at execution time."""
