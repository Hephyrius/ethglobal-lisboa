"""The registration table.

**This is the extension point.** Adding a data provider — Chainlink, Pyth,
DefiLlama, an internal risk model — is:

  1. Write `sources/yourthing.py`: subclass `BaseSource`, set `key`, implement
     `async fetch(assets) -> list[Fact]`.
  2. Add one line to `SOURCE_FACTORIES` below.
  3. Name the key in a mandate's `permitted_data_sources`.

No other file in this repository changes. Not the registry, not the snapshot
schema, not the agent, not the dApp. That property is the entire reason the
data layer is built the way it is, and `tests/test_registry.py` asserts it by
registering a source that exists only inside the test.

Factories, not instances: a source is constructed only when a mandate actually
names it, so a provider whose credential is absent costs nothing until someone
asks for it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from ..config import Settings
from ..ports import DataSource
from .messari import make_messari_source
from .token_api import make_token_api_source

SourceFactory = Callable[[Settings], DataSource]

#: key → factory. The keys here are what a mandate names, what the genesis UI
#: offers, and what `Fact.source` carries as provenance. They are user-visible
#: and effectively permanent once shipped — rename with care.
SOURCE_FACTORIES: Mapping[str, SourceFactory] = {
    "messari": make_messari_source,
    "token_api": make_token_api_source,
    # "chainlink": make_chainlink_source,   ← a future provider is this line
}


def available_sources() -> list[str]:
    """Registered keys, sorted. The grantable set at genesis."""
    return sorted(SOURCE_FACTORIES)


__all__ = ["SOURCE_FACTORIES", "SourceFactory", "available_sources"]
