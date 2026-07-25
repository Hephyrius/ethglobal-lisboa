"""A `DataSourceRegistry` over the golden MarketSnapshot.

Stands in for Lane C until `AGENT_DATA_REGISTRY` points at the real registry.
It is a faithful implementation of the port rather than a stub that returns a
constant: it honours `source_keys` as access control and records unknown keys in
`errors`, so the decision loop exercises the same code paths it will in live
mode — including the "a source I was granted said nothing" case, which is
exactly the case a model must reason around.
"""

from __future__ import annotations

from curator_schema import Fact, MarketSnapshot, SourceError

from .. import fixtures
from ..clock import utcnow

__all__ = ["FixtureDataRegistry"]


class FixtureDataRegistry:
    """Serves the golden snapshot, filtered to the mandate's permitted sources."""

    def available(self) -> list[str]:
        seen: list[str] = []
        for fact in fixtures.market_snapshot().facts:
            if fact.source not in seen:
                seen.append(fact.source)
        return seen

    async def snapshot(self, source_keys: list[str], assets: list[str]) -> MarketSnapshot:
        golden = fixtures.market_snapshot()
        known = set(self.available())
        granted = set(source_keys)

        # The mandate's permitted_data_sources IS the access control mechanism:
        # a source not named there is never consulted, even though the fixture
        # holds its facts.
        facts: list[Fact] = [f for f in golden.facts if f.source in granted]

        errors: list[SourceError] = [e for e in golden.errors if e.source in granted]
        errors += [
            SourceError(source=key, message=f"unknown data source {key!r}; not registered")
            for key in source_keys
            if key not in known
        ]

        return MarketSnapshot(taken_at=utcnow(), facts=facts, errors=errors)
