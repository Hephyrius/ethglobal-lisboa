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

    #: Which `Fact.kind`s this source can contribute.
    #:
    #: Declared so callers can ask for a *capability* rather than naming a
    #: provider: "who has prices?" resolves through the registry instead of
    #: through a hardcoded list somewhere else in the codebase. That is what
    #: keeps "adding a source is one line" true — a new price source starts
    #: serving price queries the moment it is registered, with no second edit.
    #:
    #: An empty tuple means "unknown", and such a source is consulted for every
    #: capability. Erring toward including it costs one call that returns
    #: nothing; erring the other way silently drops a source the user granted.
    provides: tuple[str, ...] = ()

    def __init__(self) -> None:
        self._notes: list[str] = []
        self._remarks: list[str] = []

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
        """Record a partial **failure** to surface in `MarketSnapshot.errors`.

        Only for something that was supposed to work and did not. If you are
        reaching for this to explain a deliberate skip or a question the source
        was never able to answer, use `remark` — see below.
        """
        self._notes.append(message)

    def drain_notes(self) -> list[str]:
        """Return and clear notes. Called by the registry after each fetch."""
        notes, self._notes = self._notes, []
        return notes

    # ── context channel ───────────────────────────────────────────────────
    #
    # `note` and `remark` were one channel until the journal was counted. Of the
    # 36 recorded ticks, 35 reported "USDC is a quote token on this venue" and
    # 35 reported a subgraph skipped by a deliberate timeout budget — as errors.
    # The curator prompt renders `errors[]` under the heading *Data you could
    # NOT read this tick. Reason about this explicitly*, so every single tick
    # opened by telling the agent that half its data layer was broken when it
    # was working exactly as designed.
    #
    # A source that cannot answer a question it was never able to answer has not
    # failed. Neither has one we chose not to wait for. Both are worth saying;
    # neither is a gap in the agent's view of the market.

    def remark(self, message: str) -> None:
        """Record non-failure context, surfaced in `MarketSnapshot.notes`."""
        self._remarks.append(message)

    def drain_remarks(self) -> list[str]:
        """Return and clear remarks. Called by the registry after each fetch."""
        remarks, self._remarks = self._remarks, []
        return remarks

    async def close(self) -> None:
        """Release held resources. Safe to call more than once."""
        return None

    def describe(self) -> dict[str, str]:
        return {
            "key": self.key,
            "description": self.description,
            "provides": ", ".join(self.provides),
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging affordance
        return f"<{type(self).__name__} key={self.key!r}>"
