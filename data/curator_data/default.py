"""A ready-made registry instance, for consumers that late-bind by reference.

Lane B's harness resolves its data seam from configuration —
`AGENT_DATA_REGISTRY=<module>:<attribute>` — imports it on first use, and checks
it against the frozen `DataSourceRegistry` Protocol. That mechanism needs an
*instance* at a stable import path, which `build_registry()` (a function) does
not provide.

So the integration point is:

    AGENT_DATA_REGISTRY=curator_data.default:registry

Kept in its own module rather than on `curator_data` itself, because
constructing this reads `.env`. Importing the package should have no side
effect; importing *this* module is an explicit request for the configured
default. Anyone wanting different settings calls `build_registry(settings)`
instead.

Construction is cheap and cannot fail on missing credentials: sources are
built lazily on first use, so an absent `GRAPH_API_KEY` surfaces later as a
`MarketSnapshot.errors` entry rather than an import-time crash. That matters
for a late-binding consumer — a raise here would silently drop them back to
fixture data.
"""

from __future__ import annotations

from .registry import Registry, build_registry

#: The configured registry. Safe to import at any time; holds no connections
#: until a source is actually consulted.
registry: Registry = build_registry()

__all__ = ["registry"]
