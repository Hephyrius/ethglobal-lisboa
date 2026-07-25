"""Keeps the JSON Schemas and the pydantic mirror from drifting apart.

Splitting the stack across Python and TypeScript means every shape is
declared three times (JSON Schema, pydantic, zod). That is the accepted cost
of the split; this test is the mitigation. Every golden fixture must validate
against BOTH the JSON Schema and the pydantic model, so a change to one that
isn't mirrored in the other fails here rather than at integration time.

Run:  uv run pytest packages/schema/python -q
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from curator_schema import (
    AgentAction,
    AllocationDecision,
    ExecutionPlan,
    Mandate,
    MarketSnapshot,
    VaultState,
)
from schema_registry import FIXTURE_DIR, errors_against

# fixture stem -> (schema filename, pydantic model)
CASES = {
    "mandate": ("mandate.schema.json", Mandate),
    "market-snapshot": ("market-snapshot.schema.json", MarketSnapshot),
    "allocation-decision": ("allocation-decision.schema.json", AllocationDecision),
    "execution-plan": ("execution-plan.schema.json", ExecutionPlan),
    "vault-state": ("vault-state.schema.json", VaultState),
    "agent-action": ("agent-action.schema.json", AgentAction),
}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("stem", sorted(CASES))
def test_fixture_matches_json_schema(stem: str) -> None:
    schema_name, _ = CASES[stem]
    errors = errors_against(schema_name, _load(FIXTURE_DIR / f"{stem}.json"))
    assert not errors, errors


@pytest.mark.parametrize("stem", sorted(CASES))
def test_fixture_matches_pydantic(stem: str) -> None:
    _, model = CASES[stem]
    model.model_validate(_load(FIXTURE_DIR / f"{stem}.json"))


@pytest.mark.parametrize("stem", sorted(CASES))
def test_pydantic_roundtrip_is_stable(stem: str) -> None:
    """Serializing a parsed fixture must still satisfy the JSON Schema.

    Catches the sneaky failure where pydantic accepts input but emits
    something the schema rejects — e.g. a datetime that serializes to a
    format the JSON Schema's `format: date-time` won't take.
    """
    schema_name, model = CASES[stem]
    obj = model.model_validate(_load(FIXTURE_DIR / f"{stem}.json"))
    emitted = json.loads(obj.model_dump_json(exclude_none=True))
    errors = errors_against(schema_name, emitted)
    assert not errors, errors


def test_every_fixture_is_covered() -> None:
    """A new fixture with no case here would silently go unchecked."""
    on_disk = {p.stem for p in FIXTURE_DIR.glob("*.json")}
    assert on_disk == set(CASES), f"uncovered fixtures: {on_disk ^ set(CASES)}"


def test_snapshot_facts_carry_provenance() -> None:
    """Provenance is the whole point of the source-agnostic snapshot design:
    the UI shows where each number came from, and a source that forgets to
    stamp itself breaks that."""
    snap = MarketSnapshot.model_validate(_load(FIXTURE_DIR / "market-snapshot.json"))
    assert snap.facts, "fixture should exercise the merge path"
    assert all(f.source for f in snap.facts)
    assert len({f.id for f in snap.facts}) == len(snap.facts), "fact ids must be unique"


def test_decision_only_references_real_facts() -> None:
    """AllocationDecision.facts_used is how the UI links reasoning to data —
    and how we catch a model citing facts it was never given."""
    snap = MarketSnapshot.model_validate(_load(FIXTURE_DIR / "market-snapshot.json"))
    decision = AllocationDecision.model_validate(_load(FIXTURE_DIR / "allocation-decision.json"))
    assert set(decision.facts_used) <= {f.id for f in snap.facts}


def test_target_weights_sum_to_one() -> None:
    decision = AllocationDecision.model_validate(_load(FIXTURE_DIR / "allocation-decision.json"))
    assert decision.target_allocations is not None
    assert abs(sum(a.weight for a in decision.target_allocations) - 1.0) < 0.01
