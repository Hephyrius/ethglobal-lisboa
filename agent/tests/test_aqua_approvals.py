"""Approval steps are never dropped, reordered or deduplicated.

Acknowledging cross-lane request #17 from Lane D, and pinning it so it cannot
regress silently.

**The finding.** Verified by Lane D against the real contract: `Aqua.ship()`
**succeeds with zero allowance.** It records full virtual balances and returns a
valid strategy hash, because shipping moves no tokens — the allowance is only
consumed later, when a taker fills and Aqua `pull()`s from the vault.

**Why that is uniquely dangerous.** Everywhere else, a missing approval reverts:
loud, immediate, obvious. Here it does not. An Aqua plan missing its approvals
produces a transaction that succeeds, a strategy hash that looks valid, non-zero
balances, no error anywhere — and a position that is **silently never fillable**.
The vault would sit holding what it believes is a live market-making position,
earning nothing, with every observable signal saying it is fine.

So this is the one place in the system where an optimisation that is obviously
correct elsewhere — "skip the approve, the allowance is already sufficient" —
fails quietly instead of loudly. The harness therefore does not inspect,
reorder, merge or skip venue steps at all: `build_execution_plan` submits exactly
what a venue returns, in order, and `executeBatch` sends exactly that.

These tests exist so that if anyone ever adds step-skipping, they fail here with
this explanation rather than shipping a dead position to a demo.
"""

from __future__ import annotations

import pytest
from curator_schema import (
    AllocationDecision,
    AquaShipIntent,
    ExecutionPlan,
    ExecutionStep,
    Mandate,
)

from agent import fixtures
from agent.loop.planning import build_execution_plan

USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
WETH = "0x4200000000000000000000000000000000000006"
AQUA = "0x499943E74FB0cE105688beeE8Ef2ABec5D936d31"


def _aqua_plan(steps: list[ExecutionStep]) -> ExecutionPlan:
    # A maker posts liquidity rather than crossing a spread, so 0 bps is
    # legitimate here and must not be confused with "unknown".
    return ExecutionPlan(venue="aqua", steps=steps, expected_slippage_bps=0)


def _approve(token: str, tag: str) -> ExecutionStep:
    return ExecutionStep(
        target=token,
        value="0",
        calldata="0x095ea7b3" + tag * 8 + "0" * (128 - len(tag) * 8),
        why=f"approve Aqua to pull {token[:8]}",
    )


SHIP = ExecutionStep(
    target=AQUA,
    value="0",
    calldata="0x" + "5b" * 100,
    why="ship an xyc strategy — moves no tokens, so a missing approval will NOT revert",
)

THREE_STEPS = [_approve(USDC, "a1"), _approve(WETH, "b2"), SHIP]


class _AquaVenue:
    """Stands in for Lane D's adapter. Returns whatever plan it was given."""

    key = "aqua"

    def __init__(self, plan: ExecutionPlan) -> None:
        self._plan = plan
        self.calls = 0

    async def plan(self, intent, vault):
        self.calls += 1
        return self._plan


@pytest.fixture
def mandate() -> Mandate:
    """Aqua permitted, and a slippage ceiling that cannot mask a step being lost."""
    return fixtures.mandate()


@pytest.fixture
def vault():
    return fixtures.vault_state()


def _ship_decision() -> AllocationDecision:
    return AllocationDecision(
        action="enter",
        reasoning="Posting idle USDC and WETH as a passive Aqua position.",
        facts_used=["f1", "f6"],
        venue_intents=[
            AquaShipIntent(
                tokens=["USDC", "WETH"], amounts=["750000000", "400000000000000000"]
            )
        ],
    )


# ── the harness must not touch a venue's steps ────────────────────────────


async def test_every_approval_step_survives_to_the_plan(mandate, vault):
    venue = _AquaVenue(_aqua_plan(THREE_STEPS))

    plan = await build_execution_plan(_ship_decision(), mandate, vault, {"aqua": venue})

    assert len(plan.steps) == 3, (
        "an Aqua approval was dropped — ship() would still succeed and the position "
        "would be silently unfillable (cross-lane request #17)"
    )
    assert [s.target for s in plan.steps] == [USDC, WETH, AQUA]


async def test_step_order_is_preserved_exactly(mandate, vault):
    """Approvals must precede the ship, and Aqua gives no error if they do not."""
    venue = _AquaVenue(_aqua_plan(THREE_STEPS))

    plan = await build_execution_plan(_ship_decision(), mandate, vault, {"aqua": venue})

    assert plan.steps[-1].target == AQUA, "ship() must be last"
    assert all(s.target != AQUA for s in plan.steps[:-1]), "approvals must come first"
    assert [s.calldata for s in plan.steps] == [s.calldata for s in THREE_STEPS]


async def test_redundant_looking_approvals_are_not_deduplicated(mandate, vault):
    """The exact optimisation that would break this.

    Two approvals for the same token look redundant and are not: the harness
    cannot see on-chain allowance state, and Aqua consumes the allowance later,
    at fill time. Dropping either one is invisible until a taker never fills.
    """
    duplicated = [_approve(USDC, "a1"), _approve(USDC, "a1"), SHIP]
    venue = _AquaVenue(_aqua_plan(duplicated))

    plan = await build_execution_plan(_ship_decision(), mandate, vault, {"aqua": venue})

    assert len(plan.steps) == 3, "identical-looking approvals must not be merged"


async def test_a_zero_amount_approval_is_not_pruned(mandate, vault):
    """A reset-to-zero approve looks like a no-op and is a real step."""
    reset = ExecutionStep(
        target=USDC, value="0", calldata="0x095ea7b3" + "00" * 64, why="reset allowance to 0"
    )
    venue = _AquaVenue(_aqua_plan([reset, _approve(USDC, "a1"), SHIP]))

    plan = await build_execution_plan(_ship_decision(), mandate, vault, {"aqua": venue})

    assert len(plan.steps) == 3
    assert plan.steps[0].calldata == reset.calldata


async def test_the_venue_is_asked_once_and_its_plan_used_verbatim(mandate, vault):
    """No re-planning, no second-guessing: the venue owns the step list."""
    original = _aqua_plan(THREE_STEPS)
    venue = _AquaVenue(original)

    plan = await build_execution_plan(_ship_decision(), mandate, vault, {"aqua": venue})

    assert venue.calls == 1
    assert plan.steps == original.steps


# ── and they survive encoding to the chain ────────────────────────────────


async def test_all_steps_reach_executebatch_byte_identically(mandate, vault):
    """The last place a step could be lost is the ABI encoding."""
    from agent.chain.vault_client import Web3VaultClient
    from agent.config import Settings

    from .test_chain import VAULT, _decode, _encode

    venue = _AquaVenue(_aqua_plan(THREE_STEPS))
    plan = await build_execution_plan(_ship_decision(), mandate, vault, {"aqua": venue})

    client = Web3VaultClient(
        Settings(rpc_url="http://127.0.0.1:1", agent_private_key="0x" + "11" * 32)
    )
    decoded = _decode(client, _encode(client, plan))

    assert len(decoded) == 3, "a step was lost between the plan and the transaction"
    assert decoded == [
        (s.target.lower(), int(s.value), s.calldata.removeprefix("0x").lower())
        for s in THREE_STEPS
    ]
    assert VAULT  # the encoding targets a vault, not the venue


# ── a maker legitimately reports zero slippage ────────────────────────────


async def test_zero_slippage_is_accepted_rather_than_treated_as_missing(mandate, vault):
    """Aqua reports 0 bps honestly — a maker posts liquidity, it does not cross a
    spread. Treating 0 as "unknown" would reject every ship."""
    venue = _AquaVenue(_aqua_plan(THREE_STEPS))

    plan = await build_execution_plan(_ship_decision(), mandate, vault, {"aqua": venue})

    assert plan.expected_slippage_bps == 0
    assert mandate.constraints.max_slippage_bps >= 0
