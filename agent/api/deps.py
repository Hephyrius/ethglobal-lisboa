"""Dependency wiring — the only place that knows whether we are live.

Route handlers ask for a `VaultService` or a `GenesisService` and get one. They
never see the mode, the registries or the fallbacks. That is what makes the
fixture-mode endpoint Lane E integrated against in hour 2 the same endpoint that
runs at the demo: only the object behind the port changes.

Everything is cached per process. `reset()` clears the caches for tests that
patch the environment.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from curator_schema.ports import DataSourceRegistry

from ..config import Settings, settings
from ..providers.fixture_data import FixtureDataRegistry
from ..providers.fixture_venue import FixtureVenueRegistry
from ..providers.resolve import ProviderResolution, resolve_provider
from ..service.fixture import FixtureGenesisService, FixtureVaultService
from ..service.ports import GenesisService, VaultService

__all__ = [
    "get_settings",
    "get_data_registry",
    "get_venue_registry",
    "data_resolution",
    "venue_resolution",
    "get_vault_service",
    "get_genesis_service",
    "reset",
]

log = logging.getLogger(__name__)


def get_settings() -> Settings:
    return settings()


# ── the two cross-lane seams ──────────────────────────────────────────────


@lru_cache(maxsize=1)
def data_resolution() -> ProviderResolution:
    """Lane C's registry, or fixtures. Never raises."""
    return resolve_provider(
        get_settings().data_registry_ref,
        FixtureDataRegistry(),
        DataSourceRegistry,
        what="data registry",
    )


@lru_cache(maxsize=1)
def venue_resolution() -> ProviderResolution:
    """Lane D's venues, or fixtures. Never raises.

    No port check here: `curator_schema.ports.Venue` describes a single venue,
    while what a mandate needs is a *lookup* from venue key to venue. The
    registry shape is Lane D's to publish, so this accepts what it finds and the
    venue itself is checked against the port at the point of use.
    """
    return resolve_provider(
        get_settings().venue_registry_ref, FixtureVenueRegistry(), what="venue registry"
    )


def get_data_registry() -> DataSourceRegistry:
    return data_resolution().provider


def get_venue_registry():
    return venue_resolution().provider


# ── application services ──────────────────────────────────────────────────


def _live_services():
    """Import the live services if they exist yet.

    Phases land in order (lane plan §7) and the API ships before the loop does,
    so during the build this module legitimately may not exist. Missing it
    degrades to fixtures with a warning rather than breaking the routes Lane E
    is working against.
    """
    try:
        from ..service.live import LiveGenesisService, LiveVaultService
    except ImportError as exc:  # pragma: no cover - only during the build
        log.warning("AGENT_MODE=live but live services are unavailable (%s); serving fixtures", exc)
        return None
    return LiveVaultService, LiveGenesisService


@lru_cache(maxsize=1)
def get_vault_service() -> VaultService:
    cfg = get_settings()
    if cfg.is_live and (live := _live_services()):
        return live[0](cfg)
    return FixtureVaultService(cfg)


@lru_cache(maxsize=1)
def get_genesis_service() -> GenesisService:
    cfg = get_settings()
    if cfg.is_live and (live := _live_services()):
        return live[1](cfg)
    return FixtureGenesisService(cfg)


def reset() -> None:
    """Drop cached settings and services. For tests that patch the environment."""
    settings.cache_clear()
    for cached in (data_resolution, venue_resolution, get_vault_service, get_genesis_service):
        cached.cache_clear()
