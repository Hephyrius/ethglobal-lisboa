"""Registry behaviour — the extensibility and degradation guarantees.

The first test here is the one the master build plan names in Lane C's
Definition of Done: *a dummy second source registers and merges without
touching any existing source*. It is written to fail loudly if anyone ever
makes the registry aware of a specific provider.
"""

from __future__ import annotations

import asyncio

import pytest
from curator_schema.models import Fact, MarketSnapshot
from curator_schema.ports import DataSource, DataSourceRegistry

from curator_data.config import Settings
from curator_data.facts import FactBuilder
from curator_data.ports import BaseSource
from curator_data.registry import Registry

SETTINGS = Settings(source_timeout_s=1.0)


class StubSource(BaseSource):
    """A source that exists only in this test file."""

    def __init__(self, key: str, facts: list[Fact] | None = None):
        super().__init__()
        self.key = key
        self.description = f"stub {key}"
        self._facts = facts or []
        self.calls: list[list[str]] = []
        self.closed = False

    async def fetch(self, assets: list[str]) -> list[Fact]:
        self.calls.append(list(assets))
        return list(self._facts)

    async def close(self) -> None:
        self.closed = True


def _fact(source: str, protocol: str, apy: float) -> Fact:
    builder = FactBuilder(source)
    return builder.apy_from_fraction(builder.subject(protocol=protocol, market="USDC"), apy)


# ── the Definition-of-Done test ───────────────────────────────────────────


async def test_a_brand_new_source_registers_and_merges_without_touching_existing_ones():
    """Adding a provider must be one file plus one registration line.

    `Chainlink` below is defined entirely inside this test — the registry has
    never heard of it, no shipped module mentions it, and nothing in
    curator_data was edited to make this work. If this test ever needs a change
    elsewhere in the package to pass, the extension point has regressed.
    """

    class Chainlink(BaseSource):
        key = "chainlink"
        description = "price feeds"

        async def fetch(self, assets: list[str]) -> list[Fact]:
            builder = FactBuilder(self.key)
            return [builder.usd("price", builder.subject(token=a), 1.0) for a in assets]

    incumbent = StubSource("messari", [_fact("messari", "aave-v3", 0.04)])
    registry = Registry(
        {"messari": lambda _s: incumbent, "chainlink": lambda _s: Chainlink()}, SETTINGS
    )

    snapshot = await registry.snapshot(["messari", "chainlink"], ["USDC", "WETH"])

    # Both contributions present, each carrying its own provenance.
    assert snapshot.errors == []
    assert {f.source for f in snapshot.facts} == {"messari", "chainlink"}
    assert {f.kind for f in snapshot.facts} == {"yield", "price"}
    assert len(snapshot.facts) == 3  # 1 yield + 2 prices

    # The incumbent was not modified, reconfigured or even aware of the newcomer.
    assert incumbent.calls == [["USDC", "WETH"]]

    # And the merged result still satisfies the frozen schema.
    MarketSnapshot.model_validate(snapshot.model_dump(mode="json"))


async def test_registry_satisfies_the_frozen_port():
    registry = Registry({}, SETTINGS)
    assert isinstance(registry, DataSourceRegistry)
    assert isinstance(StubSource("x"), DataSource)


# ── access control ────────────────────────────────────────────────────────


async def test_only_sources_named_in_the_mandate_are_consulted():
    """`permitted_data_sources` IS the access-control mechanism."""
    permitted = StubSource("messari", [_fact("messari", "aave-v3", 0.04)])
    forbidden = StubSource("private_feed", [_fact("private_feed", "secret", 0.99)])
    registry = Registry(
        {"messari": lambda _s: permitted, "private_feed": lambda _s: forbidden}, SETTINGS
    )

    snapshot = await registry.snapshot(["messari"], ["USDC"])

    assert forbidden.calls == []
    assert {f.source for f in snapshot.facts} == {"messari"}


async def test_available_lists_registered_keys():
    registry = Registry({"b": lambda _s: StubSource("b"), "a": lambda _s: StubSource("a")})
    assert registry.available() == ["a", "b"]


# ── capability lookup ─────────────────────────────────────────────────────


class Capable(BaseSource):
    def __init__(self, key: str, provides: tuple[str, ...]):
        super().__init__()
        self.key = key
        self.provides = provides

    async def fetch(self, assets: list[str]) -> list[Fact]:
        return []


async def test_sources_are_selected_by_capability_not_by_name():
    """A new price source must join price queries with no edit elsewhere."""
    registry = Registry(
        {
            "market_feed": lambda _s: Capable("market_feed", ("yield", "tvl")),
            "price_feed": lambda _s: Capable("price_feed", ("price",)),
            "newcomer": lambda _s: Capable("newcomer", ("price",)),
        },
        SETTINGS,
    )

    assert registry.sources_providing("price") == ["newcomer", "price_feed"]
    assert registry.sources_providing("yield") == ["market_feed"]


async def test_a_source_declaring_no_capability_is_consulted_anyway():
    """Unknown capability must not silently drop a granted source."""
    registry = Registry({"mystery": lambda _s: StubSource("mystery")}, SETTINGS)
    assert registry.sources_providing("price") == ["mystery"]


async def test_capability_lookup_with_no_kinds_returns_everything():
    registry = Registry({"a": lambda _s: Capable("a", ("price",))}, SETTINGS)
    assert registry.sources_providing() == ["a"]


async def test_mandate_permissions_still_win_over_capability():
    """Capable but not granted means not consulted."""
    from curator_data.queries import snapshot_for

    granted = StubSource("granted", [_fact("granted", "aave-v3", 0.04)])
    ungranted = StubSource("ungranted", [_fact("ungranted", "other", 0.09)])
    registry = Registry(
        {"granted": lambda _s: granted, "ungranted": lambda _s: ungranted}, SETTINGS
    )

    snapshot = await snapshot_for(
        ["USDC"], kinds=("yield",), permitted=["granted"], registry=registry
    )

    assert ungranted.calls == []
    assert {f.source for f in snapshot.facts} == {"granted"}


# ── degradation: a source must never crash the decision loop ──────────────


async def test_unknown_source_key_degrades_into_errors():
    registry = Registry({"messari": lambda _s: StubSource("messari")}, SETTINGS)

    snapshot = await registry.snapshot(["messari", "typo_source"], ["USDC"])

    assert [e.source for e in snapshot.errors] == ["typo_source"]
    assert "unknown data source" in snapshot.errors[0].message
    # The available set is named, so the fix is obvious from the message alone.
    assert "messari" in snapshot.errors[0].message


async def test_raising_source_degrades_and_the_others_still_return():
    class Exploding(BaseSource):
        key = "boom"

        async def fetch(self, assets: list[str]) -> list[Fact]:
            raise ConnectionError("gateway went away")

    healthy = StubSource("messari", [_fact("messari", "aave-v3", 0.04)])
    registry = Registry({"messari": lambda _s: healthy, "boom": lambda _s: Exploding()}, SETTINGS)

    snapshot = await registry.snapshot(["messari", "boom"], ["USDC"])

    assert len(snapshot.facts) == 1  # the healthy source still contributed
    assert [e.source for e in snapshot.errors] == ["boom"]
    assert "gateway went away" in snapshot.errors[0].message


async def test_hanging_source_times_out_rather_than_blocking_forever():
    class Hanging(BaseSource):
        key = "slow"

        async def fetch(self, assets: list[str]) -> list[Fact]:
            await asyncio.sleep(30)
            return []

    healthy = StubSource("messari", [_fact("messari", "aave-v3", 0.04)])
    registry = Registry(
        {"messari": lambda _s: healthy, "slow": lambda _s: Hanging()},
        Settings(source_timeout_s=0.05),
    )

    snapshot = await registry.snapshot(["messari", "slow"], ["USDC"])

    assert len(snapshot.facts) == 1
    assert [e.source for e in snapshot.errors] == ["slow"]
    assert "timed out" in snapshot.errors[0].message


async def test_source_that_fails_to_construct_is_reported_not_raised():
    def broken(_settings):
        raise ValueError("missing credential")

    registry = Registry({"broken": broken}, SETTINGS)
    snapshot = await registry.snapshot(["broken"], ["USDC"])

    assert snapshot.facts == []
    assert "could not initialise" in snapshot.errors[0].message


async def test_partial_failure_notes_reach_the_snapshot():
    """A source that fetched 1 of 2 protocols must say so."""

    class Partial(BaseSource):
        key = "messari"

        async def fetch(self, assets: list[str]) -> list[Fact]:
            self.note("moonwell: HTTP 502")
            return [_fact("messari", "aave-v3", 0.04)]

    registry = Registry({"messari": lambda _s: Partial()}, SETTINGS)
    snapshot = await registry.snapshot(["messari"], ["USDC"])

    assert len(snapshot.facts) == 1
    assert [e.message for e in snapshot.errors] == ["moonwell: HTTP 502"]


async def test_notes_are_drained_even_when_the_source_then_raises():
    class PartialThenFails(BaseSource):
        key = "messari"

        async def fetch(self, assets: list[str]) -> list[Fact]:
            self.note("moonwell: HTTP 502")
            raise ConnectionError("and then everything died")

    registry = Registry({"messari": lambda _s: PartialThenFails()}, SETTINGS)
    snapshot = await registry.snapshot(["messari"], ["USDC"])

    messages = [e.message for e in snapshot.errors]
    assert "moonwell: HTTP 502" in messages
    assert any("everything died" in m for m in messages)


# ── provenance ────────────────────────────────────────────────────────────


async def test_mislabelled_provenance_is_corrected_and_reported():
    """A source attributing facts to someone else is a bug we must not hide."""
    liar = StubSource("messari", [_fact("token_api", "aave-v3", 0.04)])
    registry = Registry({"messari": lambda _s: liar}, SETTINGS)

    snapshot = await registry.snapshot(["messari"], ["USDC"])

    assert [f.source for f in snapshot.facts] == ["messari"]  # corrected
    assert any("wrong provenance" in e.message for e in snapshot.errors)  # and reported


async def test_fact_ids_are_unique_within_a_snapshot():
    """`AllocationDecision.facts_used` points at these; duplicates make a
    citation ambiguous."""
    duplicate = _fact("messari", "aave-v3", 0.04)
    source = StubSource("messari", [duplicate, duplicate.model_copy()])
    registry = Registry({"messari": lambda _s: source}, SETTINGS)

    snapshot = await registry.snapshot(["messari"], ["USDC"])

    ids = [f.id for f in snapshot.facts]
    assert len(ids) == len(set(ids))


# ── plumbing ──────────────────────────────────────────────────────────────


async def test_duplicate_source_keys_are_requested_once():
    source = StubSource("messari")
    registry = Registry({"messari": lambda _s: source}, SETTINGS)
    await registry.snapshot(["messari", "messari"], ["USDC"])
    assert len(source.calls) == 1


async def test_sources_are_constructed_once_and_reused_across_snapshots():
    built = []

    def factory(_settings):
        source = StubSource("messari")
        built.append(source)
        return source

    registry = Registry({"messari": factory}, SETTINGS)
    await registry.snapshot(["messari"], ["USDC"])
    await registry.snapshot(["messari"], ["USDC"])

    assert len(built) == 1  # connection pools survive across ticks


async def test_aclose_closes_every_instantiated_source():
    source = StubSource("messari")
    registry = Registry({"messari": lambda _s: source}, SETTINGS)
    await registry.snapshot(["messari"], ["USDC"])
    await registry.aclose()
    assert source.closed is True


async def test_runtime_registration_adds_a_source():
    registry = Registry({}, SETTINGS)
    registry.register("late", lambda _s: StubSource("late", [_fact("late", "x", 0.01)]))

    assert registry.available() == ["late"]
    snapshot = await registry.snapshot(["late"], ["USDC"])
    assert len(snapshot.facts) == 1


async def test_register_rejects_an_empty_key():
    with pytest.raises(ValueError):
        Registry({}, SETTINGS).register("", lambda _s: StubSource("x"))


async def test_empty_snapshot_is_still_valid():
    """No sources named is legal — the agent simply sees nothing."""
    snapshot = await Registry({}, SETTINGS).snapshot([], ["USDC"])
    assert snapshot.facts == []
    assert snapshot.errors == []
    MarketSnapshot.model_validate(snapshot.model_dump(mode="json"))
