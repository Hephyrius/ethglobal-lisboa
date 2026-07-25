"""P1 — the three failure modes that made every tick look broken.

Aggregated over the 36 actions in `.agent-state/actions/*.jsonl` before this
work, a snapshot carried on average two `errors[]` entries, and 70 of the 73
total were one of:

  * `USDC is a quote token on this venue` (35) — a category mistake
  * `uniswap-v3: no response within 6s` / `gateway timed out` (35) — a protocol
    we had already given up on, retried every tick
  * `RuntimeError: Event loop is closed` (2) — a real bug

The first two are not failures and must not be reported as such, because the
curator prompt renders `errors[]` as *data you could not read*. The third is,
and it is the one that could take out a tick outright.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
from curator_data.http import LoopBoundClient
from curator_data.ports import BaseSource
from curator_data.registry import Registry
from curator_data.sources.messari import MessariSource
from curator_data.sources.protocols import Protocol

# ── the two channels reach the snapshot separately ────────────────────────


class _TwoChannelSource(BaseSource):
    key = "twochannel"

    async def fetch(self, assets):
        self.note("this actually broke")
        self.remark("this is merely worth knowing")
        return []


async def test_notes_and_errors_land_in_different_places():
    registry = Registry({"twochannel": lambda _s: _TwoChannelSource()})
    snapshot = await registry.snapshot(["twochannel"], ["USDC"])

    assert [e.message for e in snapshot.errors] == ["this actually broke"]
    assert [n.message for n in snapshot.notes] == ["this is merely worth knowing"]
    assert snapshot.notes[0].source == "twochannel"


class _LegacySource:
    """A duck-typed source with neither drain method — the frozen port's
    minimum, and what a third party writing against `DataSource` produces."""

    key = "legacy"

    async def fetch(self, assets):
        return []


async def test_a_source_with_neither_drain_method_still_works():
    """`drain_remarks` is optional, exactly as `drain_notes` always was.

    The one-line-to-add-a-source claim in the registry docstring depends on
    this: a source is `key` plus `fetch`, and everything else is opt-in.
    """
    registry = Registry({"legacy": lambda _s: _LegacySource()})
    snapshot = await registry.snapshot(["legacy"], ["USDC"])
    assert snapshot.errors == []
    assert snapshot.notes == []


# ── circuit breaker ───────────────────────────────────────────────────────


class _DeadGateway:
    """A subgraph that never answers — uniswap-v3's observed behaviour."""

    def __init__(self) -> None:
        self.calls = 0

    async def query(self, subgraph_id, document, variables=None):
        self.calls += 1
        raise TimeoutError("no response within 6s")

    async def aclose(self):
        return None


def _messari_over(gateway) -> MessariSource:
    protocol = Protocol(
        key="uniswap-v3",
        subgraph_id="FUbEPQw1oMghy39fwWBFY5fE6MXPXZQtjncQy2cXdrNS",
        family="dex-amm",
        label="Uniswap V3",
    )
    from curator_data.config import Settings

    return MessariSource(
        Settings(graph_api_key="test-key"), gateway=gateway, protocols=[protocol]
    )


async def test_a_chronically_failing_protocol_stops_being_called():
    """35 consecutive retries is not resilience; it is 210 seconds of nothing."""
    gateway = _DeadGateway()
    source = _messari_over(gateway)

    for _ in range(source.BREAKER_TRIPS_AFTER):
        await source.fetch(["USDC"])
    assert gateway.calls == source.BREAKER_TRIPS_AFTER
    assert len(source.drain_notes()) == source.BREAKER_TRIPS_AFTER

    # Breaker open: the next fetches cost no request at all.
    await source.fetch(["USDC"])
    await source.fetch(["USDC"])
    assert gateway.calls == source.BREAKER_TRIPS_AFTER, "a tripped breaker still made a request"

    # And the skip is context, not a claimed data gap.
    assert source.drain_notes() == []
    assert any("skipped without a request" in r for r in source.drain_remarks())


async def test_the_breaker_probes_so_a_recovered_subgraph_comes_back():
    """A breaker with no probe is just an outage we inflicted on ourselves."""
    gateway = _DeadGateway()
    source = _messari_over(gateway)

    for _ in range(source.BREAKER_TRIPS_AFTER):
        await source.fetch(["USDC"])
    tripped_at = gateway.calls

    for _ in range(source.BREAKER_PROBE_EVERY):
        await source.fetch(["USDC"])

    assert gateway.calls == tripped_at + 1, "the breaker never probed"


class _FlakyGateway(_DeadGateway):
    """Fails until `heal()`, then answers with an empty but valid result."""

    def __init__(self) -> None:
        super().__init__()
        self.healed = False

    async def query(self, subgraph_id, document, variables=None):
        self.calls += 1
        if not self.healed:
            raise TimeoutError("no response within 6s")
        return {"liquidityPools": []}


async def test_recovery_clears_the_breaker():
    gateway = _FlakyGateway()
    source = _messari_over(gateway)
    for _ in range(source.BREAKER_TRIPS_AFTER):
        await source.fetch(["USDC"])

    gateway.healed = True
    for _ in range(source.BREAKER_PROBE_EVERY):
        await source.fetch(["USDC"])
    source.drain_notes(), source.drain_remarks()

    before = gateway.calls
    await source.fetch(["USDC"])
    assert gateway.calls == before + 1, "a recovered protocol is still being skipped"


# ── the event-loop bug ────────────────────────────────────────────────────


async def _client_id(bound: LoopBoundClient) -> int:
    return id(bound.get_client())


def test_a_client_is_rebuilt_when_the_event_loop_changes():
    """The `RuntimeError: Event loop is closed` reproduction, made deterministic.

    `curator_data.default:registry` is a module-level singleton that caches
    source instances, and each source caches an `httpx.AsyncClient` whose
    transport is bound to the loop that first used it. Anything calling
    `asyncio.run` more than once in a process — the CLI, the MCP server, this
    test suite — gets a client bound to a loop that no longer exists.
    """
    built: list[httpx.AsyncClient] = []

    def factory() -> httpx.AsyncClient:
        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
        built.append(client)
        return client

    bound = LoopBoundClient(factory)

    first = asyncio.run(_client_id(bound))
    second = asyncio.run(_client_id(bound))

    assert first != second, "the client survived a loop change and would raise on use"
    assert len(built) == 2


def test_an_injected_client_is_never_swapped_out():
    """Tests inject a MockTransport client; rebuilding it would silently
    un-mock the source and start making real requests."""
    injected = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    bound = LoopBoundClient(lambda: pytest.fail("should not build"))
    bound.adopt(injected)

    assert asyncio.run(_client_id(bound)) == id(injected)
    assert asyncio.run(_client_id(bound)) == id(injected)
