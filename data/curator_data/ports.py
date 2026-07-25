"""The lane's view of the frozen `DataSource` seam.

`packages/schema` owns the protocol — it is frozen and this module does not
redefine it, it re-exports it. What lives here is the *convenience* layer a
source author actually writes against, which the frozen protocol deliberately
does not specify.

Writing a new source is: subclass `BaseSource`, set `key`, implement
`fetch`. Nothing else in the package changes except one registration line.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from curator_schema.models import Fact
from curator_schema.ports import DataSource, DataSourceRegistry

__all__ = ["DataSource", "DataSourceRegistry", "BaseSource"]


class BaseSource(ABC):
    """Optional base class for a `DataSource`.

    The frozen protocol is structural, so a source need not inherit from this —
    any object with `key` and `async fetch` satisfies it. This exists to carry
    the two obligations that are easy to forget:

      1. `close()` — sources own HTTP clients and the registry must be able to
         release them without knowing what a source is made of.
      2. `describe()` — the MCP server and the genesis UI both need to tell a
         human what a source key means. Without this, "messari" is an opaque
         string in a checkbox list.

    Failure contract (from the frozen port, restated because it is the rule
    most likely to be broken): `fetch` must not raise for *expected* failure —
    a timeout, a rate limit, a missing market. Return what you have. The
    registry does catch exceptions, but a source that raises on a missing
    market loses the facts it could have returned alongside it.
    """

    #: Registry key. Named in `Mandate.permitted_data_sources`, shown in the
    #: genesis UI, and stamped onto every Fact as provenance — so it is
    #: user-visible and effectively permanent once shipped.
    key: str = ""

    #: One line, human-facing. Shown wherever a user picks data sources.
    description: str = ""

    def __init__(self) -> None:
        self._notes: list[str] = []

    @abstractmethod
    async def fetch(self, assets: list[str]) -> list[Fact]:
        """Facts relevant to `assets` (symbols from the mandate)."""
        raise NotImplementedError

    # ── partial-failure channel ───────────────────────────────────────────
    #
    # The frozen port models a source as all-or-nothing: return facts, or raise
    # and be recorded in `MarketSnapshot.errors`. Real sources are not
    # all-or-nothing — this one queries five protocols and any one of them can
    # be down. Returning the other four silently would tell the model it saw
    # the whole market when it did not, which is the single most dangerous
    # failure mode we have: the agent holds a key and acts on this.
    #
    # So a source may record notes about what it could not fetch. The registry
    # looks for `drain_notes` and folds each into `errors[]`. This is additive —
    # `key` + `fetch` still satisfies the frozen protocol, and a source that
    # ignores this mechanism behaves exactly as before.

    def note(self, message: str) -> None:
        """Record a partial failure to surface in `MarketSnapshot.errors`."""
        self._notes.append(message)

    def drain_notes(self) -> list[str]:
        """Return and clear notes. Called by the registry after each fetch."""
        notes, self._notes = self._notes, []
        return notes

    async def close(self) -> None:
        """Release held resources. Safe to call more than once."""
        return None

    def describe(self) -> dict[str, str]:
        return {"key": self.key, "description": self.description}

    def __repr__(self) -> str:  # pragma: no cover - debugging affordance
        return f"<{type(self).__name__} key={self.key!r}>"
