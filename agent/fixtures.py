"""Typed access to the shared golden fixtures.

`packages/schema/fixtures/` is the contract every lane develops against (master
plan §9 rule 2). Loading them through the pydantic models rather than as raw
dicts means a fixture that drifts from the frozen schema fails here, loudly, at
the point of use — instead of being served to Lane E as a plausible-looking
payload that its zod parser then rejects in the browser.

Each loader returns a fresh deep copy, so a caller mutating a snapshot cannot
corrupt another request's view of it.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path

from curator_schema import (
    AgentAction,
    AllocationDecision,
    ExecutionPlan,
    Mandate,
    MarketSnapshot,
    VaultState,
)
from pydantic import BaseModel

from .config import FIXTURES_DIR

__all__ = [
    "mandate",
    "market_snapshot",
    "allocation_decision",
    "execution_plan",
    "agent_action",
    "vault_state",
]

@cache
def _raw(name: str) -> str:
    path: Path = FIXTURES_DIR / f"{name}.json"
    if not path.is_file():
        raise FileNotFoundError(
            f"golden fixture {path} is missing — packages/schema/fixtures is the "
            "shared contract and must be present for fixture mode to serve"
        )
    return path.read_text(encoding="utf-8")


def _load[M: BaseModel](name: str, model: type[M]) -> M:
    return model.model_validate(json.loads(_raw(name)))


def mandate() -> Mandate:
    return _load("mandate", Mandate)


def market_snapshot() -> MarketSnapshot:
    return _load("market-snapshot", MarketSnapshot)


def allocation_decision() -> AllocationDecision:
    return _load("allocation-decision", AllocationDecision)


def execution_plan() -> ExecutionPlan:
    return _load("execution-plan", ExecutionPlan)


def agent_action() -> AgentAction:
    return _load("agent-action", AgentAction)


def vault_state() -> VaultState:
    return _load("vault-state", VaultState)
