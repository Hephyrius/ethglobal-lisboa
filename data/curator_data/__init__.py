"""Market data for the curator agent.

The public surface is deliberately small: build a registry, ask it for a
snapshot. Everything else is an implementation detail of some source.

    from curator_data import build_registry

    registry = build_registry()
    snapshot = await registry.snapshot(["messari", "token_api"], ["USDC", "WETH"])

No name in this package's public API refers to a data provider. Sources are
addressed by registry key, and those keys come from the mandate.
"""

from .facts import FactBuilder
from .registry import Registry, build_registry
from .sources import SOURCE_FACTORIES, available_sources

__all__ = [
    "Registry",
    "build_registry",
    "available_sources",
    "SOURCE_FACTORIES",
    "FactBuilder",
]
