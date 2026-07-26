"""R3 — the agent reasons over live data.

Asks the running agent for a decision on a real vault and checks the result is *grounded*: schema
valid, and every fact it cites is one it was actually given.

`held` is a PASS here. Whether the agent trades is R4's question; this rung asks only whether it
reasoned over live Graph data. Conflating the two is how a data problem gets diagnosed as an
execution problem.

    uv run pytest tests/e2e -k slice_decide -v

Slow by nature: a tick pays a model round trip plus live subgraph queries, ~35-60s warm and far
longer if ollama has evicted the model. `scripts/preflight.sh` warns about exactly that.
"""

from __future__ import annotations

import httpx
import pytest
from curator_schema import AgentAction

TICK_TIMEOUT = 420.0  # generous: cold model load can exceed 120s


@pytest.fixture(scope="module")
def demo_vault(curated_vault: str) -> str:
    """The shared curated vault — read and tick only, never mutated by this module.

    Uses a shared vault deliberately: a tick needs holdings worth reasoning about, and R2's fresh
    vault holds a single asset with nothing to compare. A tick may execute, so this is the one place
    the suite can touch shared state — which is why nothing here asserts on balances.

    It used to read `deployments["demoVault"]`, which is the one vault on the deployment that can
    never be ticked — see `curated_vault` in conftest for why. Every assertion below then skipped on
    the missing snapshot, so this rung reported *"the agent reasons over live data"* as five skips
    rather than as a failure, on every fresh fork.
    """
    return curated_vault


@pytest.fixture(scope="module")
def action(api: str, demo_vault: str) -> AgentAction:
    with httpx.Client(timeout=TICK_TIMEOUT) as client:
        response = client.post(f"{api}/vault/{demo_vault}/tick")
    assert response.status_code == 200, response.text
    return AgentAction.model_validate(response.json())


def test_tick_returns_a_schema_valid_action(action: AgentAction, demo_vault: str):
    assert action.vault.lower() == demo_vault.lower()
    assert action.status in {"executed", "held", "rejected", "failed", "pending"}


def test_the_agent_saw_live_market_data(action: AgentAction):
    """Live Graph data on the demo path is a submission gate — The Graph disqualifies mocked data.

    Tolerates partial failure: a source that dies lands in `snapshot.errors` by design. What is not
    tolerable is a snapshot with neither facts nor errors, which means nothing was consulted at all.
    """
    if action.snapshot is None:
        pytest.skip(f"status={action.status} carried no snapshot")

    snapshot = action.snapshot
    assert snapshot.facts or snapshot.errors, "agent consulted nothing"

    if snapshot.facts:
        sources = {fact.source for fact in snapshot.facts}
        assert sources, "facts carry no provenance — the UI cannot show where a number came from"


def test_multi_protocol_comparison_is_actually_in_play(action: AgentAction):
    """The Graph composability argument, asserted rather than assumed.

    The golden mandate grants `aave` alongside `messari` so the agent can compare a high yield on a
    thin market against a low yield on a deep one. If only one lending protocol ever reports, that
    comparison is rhetoric — so this fails loudly rather than passing quietly.
    """
    if action.snapshot is None or not action.snapshot.facts:
        pytest.skip("no facts to compare")

    protocols = {
        fact.subject.protocol
        for fact in action.snapshot.facts
        if fact.kind == "yield" and fact.subject.protocol
    }
    assert len(protocols) >= 2, (
        f"only {protocols or 'no'} protocol(s) reported yields — the multi-protocol comparison "
        "the mandate is built around is not happening"
    )


def test_every_cited_fact_was_actually_provided(action: AgentAction):
    """Grounding: `facts_used` must reference ids from the snapshot the model was given.

    This is what lets the dApp draw data → reasoning → transaction, and what catches a model citing
    evidence it invented. Note it checks ids, not values — Lane B found the model quoting a real
    fact id with a fabricated number, which no id check can catch.
    """
    if action.decision is None:
        pytest.skip(f"status={action.status} carried no decision")
    if action.snapshot is None:
        pytest.skip("no snapshot to ground against")

    available = {fact.id for fact in action.snapshot.facts}
    invented = set(action.decision.facts_used) - available
    assert not invented, f"decision cites facts it was never given: {sorted(invented)}"


def test_the_decision_is_legible(action: AgentAction):
    """The feed renders `reasoning` verbatim — it is the product, not a debug field."""
    if action.decision is None:
        pytest.skip(f"status={action.status} carried no decision")
    assert action.decision.reasoning.strip(), "empty reasoning would render as a blank feed entry"


def test_a_rejected_decision_still_records_why(action: AgentAction):
    """Rejections are kept deliberately — they are the evidence the validation layer does work.

    A rejection with no explanation is indistinguishable from a crash, both in the feed and when
    debugging a demo that suddenly stops trading.
    """
    if action.status != "rejected":
        pytest.skip("decision was not rejected")
    assert action.error, "rejected action carries no error"
