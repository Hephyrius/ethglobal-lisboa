"""Late binding to Lanes C and D.

This lane's central claim is that Lane C's data registry and Lane D's venues each
cost it **one environment variable and zero code changes**, and that a
neighbouring lane which is missing, half-built or broken degrades this one to
fixtures instead of taking the API down. That claim is load-bearing during a
24-hour build with five instances pushing concurrently, so it is tested rather
than asserted in a README.

Mirrors the dummy-source test in Lane C's own definition of done, one level up:
there it proves a new *source* needs no existing source touched; here it proves a
new *registry* needs no harness code touched.
"""

from __future__ import annotations

from curator_schema.ports import DataSourceRegistry

from agent.providers.fixture_data import FixtureDataRegistry
from agent.providers.resolve import resolve_provider, resolve_ref

FIXTURE = FixtureDataRegistry()


# ── resolving a real provider ─────────────────────────────────────────────


def test_a_class_ref_is_instantiated():
    """A lane may publish `registry = Registry()` or the class itself."""
    resolved = resolve_ref("agent.providers.fixture_data:FixtureDataRegistry")
    assert isinstance(resolved, FixtureDataRegistry)


def test_a_resolved_provider_is_used_instead_of_the_fallback():
    resolution = resolve_provider(
        "agent.providers.fixture_data:FixtureDataRegistry", FIXTURE, DataSourceRegistry
    )
    assert not resolution.is_fixture
    assert resolution.error is None
    assert resolution.label == "agent.providers.fixture_data:FixtureDataRegistry"
    assert isinstance(resolution.provider, DataSourceRegistry)


def test_no_ref_means_fixtures_without_complaint():
    """Fixture mode is the default, not a failure."""
    resolution = resolve_provider(None, FIXTURE, DataSourceRegistry)
    assert resolution.is_fixture
    assert resolution.error is None
    assert resolution.label == "fixture"


# ── every way a neighbouring lane can be broken ───────────────────────────


def test_a_missing_module_degrades_instead_of_raising():
    """Lane C not written yet, or mid-rename. The API must keep serving."""
    resolution = resolve_provider("data.not_written_yet:registry", FIXTURE, DataSourceRegistry)
    assert resolution.is_fixture
    assert "ModuleNotFoundError" in resolution.error
    assert resolution.provider is FIXTURE


def test_a_missing_attribute_degrades():
    resolution = resolve_provider(
        "agent.providers.fixture_data:no_such_name", FIXTURE, DataSourceRegistry
    )
    assert resolution.is_fixture
    assert "AttributeError" in resolution.error


def test_a_malformed_ref_degrades():
    resolution = resolve_provider("data.registry", FIXTURE, DataSourceRegistry)
    assert resolution.is_fixture
    assert "ValueError" in resolution.error


def test_a_provider_that_does_not_satisfy_the_port_is_refused():
    """Caught at startup with a clear message, not at the first tick.

    `agent.clock:utcnow` resolves fine and returns a datetime — which has neither
    `available()` nor `snapshot()`. Accepting it would produce an AttributeError
    deep inside a decision cycle instead of a warning at boot.
    """
    resolution = resolve_provider("agent.clock:utcnow", FIXTURE, DataSourceRegistry)
    assert resolution.is_fixture
    assert "DataSourceRegistry" in resolution.error


def test_an_import_that_raises_degrades():
    """A neighbouring lane with a syntax or import-time error at the moment we
    look must not be able to take this API down."""
    resolution = resolve_provider("agent.tests.broken_provider:registry", FIXTURE, None)
    assert resolution.is_fixture
    assert resolution.error


# ── the health endpoint tells the truth about all of this ─────────────────


def test_health_shows_a_live_run_that_fell_back_to_fixtures(monkeypatch):
    """The failure this exists to prevent: a demo quietly serving fixture numbers."""
    from fastapi.testclient import TestClient

    from agent.api import deps
    from agent.api.app import create_app

    monkeypatch.setenv("AGENT_MODE", "live")
    monkeypatch.setenv("AGENT_DATA_REGISTRY", "data.not_written_yet:registry")
    deps.reset()
    try:
        body = TestClient(create_app()).get("/health").json()
        assert body["mode"] == "live"
        assert body["status"] == "degraded"
        assert "data.not_written_yet:registry" in body["data_registry"]
    finally:
        deps.reset()


def test_health_is_ok_when_the_configured_provider_resolves(monkeypatch):
    from fastapi.testclient import TestClient

    from agent.api import deps
    from agent.api.app import create_app

    monkeypatch.setenv("AGENT_MODE", "live")
    monkeypatch.setenv("AGENT_DATA_REGISTRY", "agent.providers.fixture_data:FixtureDataRegistry")
    monkeypatch.setenv("AGENT_VENUE_REGISTRY", "agent.providers.fixture_venue:FixtureVenueRegistry")
    deps.reset()
    try:
        body = TestClient(create_app()).get("/health").json()
        assert body["status"] == "ok"
        assert body["data_registry"].endswith("FixtureDataRegistry")
    finally:
        deps.reset()


# ── the mandate is what selects sources, not code ─────────────────────────


async def test_only_the_sources_the_mandate_names_are_consulted():
    """`permitted_data_sources` IS the access-control mechanism.

    The harness never names a source in code and cannot tell Messari from
    Chainlink — granting one is a mandate edit.
    """
    registry = FixtureDataRegistry()
    assert set(registry.available()) >= {"messari", "token_api"}

    snapshot = await registry.snapshot(["messari"], ["USDC", "WETH"])
    assert {fact.source for fact in snapshot.facts} == {"messari"}


async def test_an_unknown_source_degrades_the_snapshot_rather_than_raising():
    """A mandate may name a source that no longer exists. The tick must survive."""
    snapshot = await FixtureDataRegistry().snapshot(["messari", "chainlink"], ["USDC"])
    assert snapshot.facts, "the sources that do work must still contribute"
    assert any(error.source == "chainlink" for error in snapshot.errors)
