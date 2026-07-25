"""Binding to the real Lane C and Lane D packages.

`test_providers.py` proves the late-binding *mechanism* against stand-ins. This
proves it against what those lanes actually published, which is the only version
of the claim that matters at integration time.

Skipped rather than failed when a lane is absent: this suite must stay runnable
from a fresh clone where only `/agent` has been installed, and a neighbouring
lane mid-edit is a normal state during the build — that is the whole reason the
harness binds late.

Nothing here needs a network, a credential or a chain. Lane C's sources degrade
into `MarketSnapshot.errors` without `GRAPH_API_KEY`, which is exactly the
behaviour the decision loop is built to survive, so it is asserted rather than
worked around.
"""

from __future__ import annotations

import json

import pytest
from curator_schema.ports import DataSourceRegistry, Venue

from agent import fixtures
from agent.chain.stub import StubVaultClient
from agent.config import Settings
from agent.loop.cycle import DecisionCycle
from agent.loop.engine import LlmDecisionEngine
from agent.loop.planning import _lookup_venue
from agent.loop.store import ActionJournal
from agent.mandate.store import MandateStore
from agent.model.backends.scripted import ScriptedBackend
from agent.providers.resolve import resolve_provider

VAULT = "0x1111111111111111111111111111111111111111"

#: The refs a deployment sets. Documented in agent/README.md and .env.example.
DATA_REF = "curator_data:build_registry"
VENUE_REF = "venues:get_venue"


@pytest.fixture(scope="module")
def lane_c():
    pytest.importorskip("curator_data", reason="Lane C not installed")
    resolution = resolve_provider(DATA_REF, None, DataSourceRegistry, what="data registry")
    if resolution.is_fixture:
        pytest.skip(f"Lane C did not bind: {resolution.error}")
    return resolution.provider


@pytest.fixture(scope="module")
def lane_d():
    pytest.importorskip("venues", reason="Lane D not installed")
    resolution = resolve_provider(VENUE_REF, None, what="venue registry")
    if resolution.is_fixture:
        pytest.skip(f"Lane D did not bind: {resolution.error}")
    return resolution.provider


# ── Lane C ────────────────────────────────────────────────────────────────


def test_lane_c_registry_satisfies_the_frozen_port(lane_c):
    assert isinstance(lane_c, DataSourceRegistry)


def test_lane_c_offers_the_sources_a_mandate_names(lane_c):
    """The mandate's `permitted_data_sources` are registry keys.

    A mandate naming a source the registry never registered produces an agent
    that is silently blind to a data class it believes it has.
    """
    available = set(lane_c.available())
    granted = set(fixtures.mandate().permitted_data_sources)
    assert granted <= available, (
        f"the golden mandate names unregistered sources: {granted - available}"
    )


async def test_lane_c_degrades_into_errors_without_a_credential(lane_c):
    """A dead or unconfigured source must not raise — the port requires it."""
    snapshot = await lane_c.snapshot(["messari", "token_api"], ["USDC", "WETH"])
    assert snapshot.taken_at is not None
    # Either facts came back (a key is present) or the failure was reported.
    assert snapshot.facts or snapshot.errors


async def test_lane_c_never_returns_a_source_the_mandate_did_not_grant(lane_c):
    snapshot = await lane_c.snapshot(["messari"], ["USDC"])
    assert {fact.source for fact in snapshot.facts} <= {"messari"}


# ── Lane D ────────────────────────────────────────────────────────────────


def test_lane_d_venues_satisfy_the_frozen_port(lane_d):
    for key in fixtures.mandate().permitted_venues:
        venue = _lookup_venue(lane_d, key)
        assert venue is not None, f"the golden mandate permits {key} but no adapter resolved"
        assert isinstance(venue, Venue), f"{key} does not satisfy the Venue port"


def test_an_unknown_venue_key_resolves_to_nothing_rather_than_raising(lane_d):
    """Reported as a missing adapter, not as another lane's exception type."""
    assert _lookup_venue(lane_d, "not-a-venue") is None


# ── both, through a real decision cycle ───────────────────────────────────


async def test_a_cycle_runs_against_both_real_lanes(tmp_path, lane_c, lane_d):
    """The vertical slice with only the model substituted.

    The decision holds and cites nothing, which is legal against an empty
    snapshot — so this asserts the *wiring* without needing a Graph key. A
    non-hold decision citing facts would be correctly rejected when Lane C has
    no credential, and that rejection is tested in `test_validation.py`.
    """
    settings = Settings(state_dir=tmp_path)
    mandates = MandateStore(tmp_path)
    mandates.save(VAULT, fixtures.mandate())
    journal = ActionJournal(tmp_path)

    hold = json.dumps(
        {
            "action": "hold",
            "reasoning": "No market data could be read this tick, so I am not sizing a "
            "position on guesswork.",
            "facts_used": [],
            "confidence": 0.4,
        }
    )

    cycle = DecisionCycle(
        engine=LlmDecisionEngine(ScriptedBackend([hold])),
        registry=lane_c,
        venues=lane_d,
        vault_client=StubVaultClient(),
        mandates=mandates,
        journal=journal,
        settings=settings,
    )

    action = await cycle.run(VAULT)

    assert action.status == "held"
    assert action.snapshot is not None, "the feed must show what the agent consulted"
    assert journal.count(VAULT) == 1
