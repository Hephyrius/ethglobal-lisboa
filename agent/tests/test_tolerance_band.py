"""B3 · the soft mandate band, and the two ways it could become "no rules".

Wave 2 §3.1: *"make the rules less rigid — violation allowed within a threshold
of mandate ±5%."* A decision that breaches a numeric constraint by no more than
the band is accepted with a recorded warning rather than rejected, because
landing at 61% against a 60% cap is the rounding artefact of a swap that priced a
hair differently, not a breach of intent.

The plan is emphatic that getting the *scope* wrong turns "less rigid" into "no
rules", so the omissions carry more weight than the inclusions and each has its
own test below:

- **`max_slippage_bps` never bends.** It is a ceiling that was already compared
  against a bound rather than an estimate (#33). Banding it means paying 5% more
  than the mandate's stated maximum cost, silently.
- **Allowlists never bend.** There is no "5% of an asset that is not permitted".
- **Anti-churn limits never bend.** A band on `max_actions_per_tick` is just a
  bigger limit.

And two failure modes worse than the rigidity being fixed:

- **The ratchet** — accepting 5% over, tick after tick, walks the book away from
  the mandate without ever triggering a rejection. Drift is therefore measured
  against the **mandate**, never against last tick.
- **Invisible drift** — every banded acceptance produces a `ConstraintWarning`
  on the `AgentAction`, which is what Lane E renders.
"""

from __future__ import annotations

import pytest
from curator_schema import AllocationDecision, Mandate, SwapIntent, TargetAllocation

from agent import fixtures
from agent.mandate.constraints import BANDABLE, apply_band, check_decision, check_plan

BAND = 0.05


@pytest.fixture
def mandate() -> Mandate:
    """Golden mandate: 60% position cap, 20% cash floor, 50bps slippage, 5% band."""
    return fixtures.mandate()


def _targets(usdc: float, weth: float) -> AllocationDecision:
    return AllocationDecision(
        action="rebalance",
        reasoning="Closing the gap to target.",
        facts_used=["f1"],
        target_allocations=[
            TargetAllocation(asset="USDC", weight=usdc),
            TargetAllocation(asset="WETH", weight=weth),
        ],
        venue_intents=[
            SwapIntent(token_in="USDC", token_out="WETH", pct_of_holdings=0.2)
        ],
    )


def _split(decision: AllocationDecision, mandate: Mandate):
    return apply_band(check_decision(decision, mandate), mandate)


def _floor_only(mandate: Mandate, floor: float = 0.4) -> Mandate:
    """A mandate where the cash floor is the only thing that can bind.

    Two adjustments, both needed to test the floor at all:

    - **The position cap is lifted.** With two assets the weights sum to 1, so
      pushing cash below its floor pushes the other leg over any tight cap, and
      the cap rejects first for a different reason.
    - **The floor is raised to 40%.** `WEIGHT_SUM_TOLERANCE` already grants 1
      absolute percentage point of slack, and 5% of a 20% floor is *also* 1pp —
      so against the golden mandate the band and the pre-existing tolerance
      coincide exactly and the band can never be observed doing anything. It
      only adds room above a 20% floor. Worth knowing rather than discovering
      through a test that silently proves nothing.
    """
    return mandate.model_copy(
        update={
            "constraints": mandate.constraints.model_copy(
                update={"max_position_pct": 0.9, "min_cash_pct": floor}
            )
        }
    )


# ── what the band forgives ────────────────────────────────────────────────


def test_a_hair_over_the_position_cap_is_accepted_with_a_warning(mandate):
    """62% against a 60% cap is 3.3% over — inside the 5% band."""
    hard, warnings = _split(_targets(0.38, 0.62), mandate)

    assert hard == []
    assert len(warnings) == 1
    assert warnings[0].constraint == "max_position_pct"
    assert warnings[0].subject == "WETH"
    assert warnings[0].limit == 0.6
    assert warnings[0].actual == pytest.approx(0.62)
    assert warnings[0].band_pct == BAND


def test_a_hair_under_the_cash_floor_is_accepted_with_a_warning(mandate):
    """38.5% against a 40% floor is 3.75% under — inside the band, and outside
    the 1pp absolute slack that would otherwise absorb it."""
    hard, warnings = _split(_targets(0.385, 0.615), _floor_only(mandate))

    banded = [w for w in warnings if w.constraint == "min_cash_pct"]
    assert banded, [str(v) for v in hard]
    assert banded[0].limit == 0.4


def test_the_warning_says_what_bent_and_by_how_much(mandate):
    """Structured *and* legible: the feed shows the sentence, the reflection
    reads the numbers."""
    _, warnings = _split(_targets(0.38, 0.62), mandate)
    message = warnings[0].message

    assert "62.00%" in message and "60.00%" in message
    assert "tolerance band" in message
    assert "steering back" in message, "a band is not permission to stay there"


# ── what it never forgives ────────────────────────────────────────────────


def test_well_past_the_cap_is_still_rejected(mandate):
    """75% against a 60% cap is 25% over. The band is a tolerance, not a lever."""
    hard, warnings = _split(_targets(0.25, 0.75), mandate)

    assert hard and warnings == []
    assert "ceiling" in str(hard[0])


def test_slippage_never_bends(mandate):
    """**The most important omission.** A ceiling was already compared against a
    bound, not an estimate, so banding it means silently paying more than the
    mandate's stated maximum cost."""
    plan = fixtures.execution_plan().model_copy(
        update={"expected_slippage_bps": 52, "quote_expires_at": None}
    )  # 52 vs a 50bps ceiling: 4% over, well inside a 5% band

    hard, warnings = apply_band(check_plan(plan, mandate), mandate)

    assert warnings == [], "slippage must never be banded"
    assert hard, "a plan over the slippage ceiling must still be rejected"


def test_a_forbidden_asset_never_bends(mandate):
    """Not numeric. There is no "5% of an asset that is not permitted"."""
    decision = _targets(0.5, 0.5).model_copy(
        update={
            "target_allocations": [
                TargetAllocation(asset="USDC", weight=0.5),
                TargetAllocation(asset="cbETH", weight=0.5),
            ]
        }
    )
    hard, warnings = _split(decision, mandate)

    assert warnings == []
    assert any("cbETH" in str(v) for v in hard)


def test_too_many_actions_never_bends(mandate):
    """An anti-churn limit with a band is just a bigger anti-churn limit."""
    swap = SwapIntent(token_in="USDC", token_out="WETH", pct_of_holdings=0.1)
    decision = _targets(0.5, 0.5).model_copy(update={"venue_intents": [swap, swap, swap]})

    hard, warnings = _split(decision, mandate)

    assert warnings == []
    assert any("at most" in str(v) for v in hard)


def test_the_bandable_set_is_exactly_the_three_allocation_constraints():
    """Pinned so widening it becomes a deliberate act with a diff, rather than
    something that drifts in behind a plausible-looking edit."""
    assert BANDABLE == {"max_position_pct", "min_cash_pct", "target_allocation"}


# ── the ratchet ───────────────────────────────────────────────────────────


def test_drift_is_measured_against_the_mandate_not_the_last_tick(mandate):
    """**The ratchet guard.** If each tick were measured against the previous
    one, 5% at a time would walk the book anywhere without ever tripping a
    rejection. Every call compares to the mandate's own number, so a book that
    has already drifted gets *less* room, not a fresh allowance."""
    first_hard, first_warn = _split(_targets(0.38, 0.62), mandate)
    assert first_hard == [] and first_warn

    # A second tick reaching further does not get another 5% from 62%.
    second_hard, second_warn = _split(_targets(0.34, 0.66), mandate)
    assert second_hard, "10% over the mandate must reject, whatever last tick did"
    assert second_warn == []


def test_the_band_is_relative_to_the_limit_not_absolute(mandate):
    """A percentage point means different things against a 60% cap and a 20%
    floor, so the overage is a fraction of the limit."""
    _, cap_warn = _split(_targets(0.385, 0.615), mandate)  # 2.5% over 0.60
    assert cap_warn and cap_warn[0].constraint == "max_position_pct"

    # 2.5pp under a 40% floor is 6.25% — outside the band, though the same
    # 2.5pp would be well inside it against a 60% limit.
    hard, warnings = _split(_targets(0.375, 0.625), _floor_only(mandate))
    assert not [w for w in warnings if w.constraint == "min_cash_pct"]
    assert any(v.constraint == "min_cash_pct" for v in hard)


def test_a_zero_band_restores_strict_behaviour(mandate):
    """`tolerance_band_pct: 0` must mean exactly what it did before the band
    existed, so a mandate can opt out entirely."""
    strict = mandate.model_copy(
        update={"constraints": mandate.constraints.model_copy(update={"tolerance_band_pct": 0.0})}
    )
    hard, warnings = _split(_targets(0.38, 0.62), strict)

    assert warnings == []
    assert hard


# ── visibility ────────────────────────────────────────────────────────────


async def test_a_banded_acceptance_is_recorded_on_the_action(tmp_path):
    """The whole point. Lane E renders `AgentAction.warnings`; a band that never
    reaches the action is indistinguishable from no rule at all."""
    import json

    from agent.chain.stub import StubVaultClient
    from agent.config import Settings
    from agent.loop.cycle import DecisionCycle
    from agent.loop.engine import LlmDecisionEngine
    from agent.loop.store import ActionJournal
    from agent.mandate.store import MandateStore
    from agent.model.backends.scripted import ScriptedBackend
    from agent.providers.fixture_data import FixtureDataRegistry
    from agent.providers.fixture_venue import FixtureVenueRegistry

    vault = "0x1111111111111111111111111111111111111111"
    mandates = MandateStore(tmp_path)
    mandates.save(vault, fixtures.mandate())

    # 62% WETH: over the 60% cap, inside the band. Direction is correct for the
    # golden vault's 70/30 book, so only the cap bends.
    raw = json.dumps(
        {
            "action": "rebalance",
            "reasoning": "Leaning into WETH while the spread justifies the inventory.",
            "facts_used": ["f1"],
            "target_allocations": [
                {"asset": "USDC", "weight": 0.38},
                {"asset": "WETH", "weight": 0.62},
            ],
            "venue_intents": [
                {
                    "venue": "uniswap",
                    "kind": "swap",
                    "token_in": "USDC",
                    "token_out": "WETH",
                    "pct_of_holdings": 0.2,
                }
            ],
        }
    )
    cycle = DecisionCycle(
        engine=LlmDecisionEngine(ScriptedBackend([raw]), max_attempts=1),
        registry=FixtureDataRegistry(),
        venues=FixtureVenueRegistry(),
        vault_client=StubVaultClient(),
        mandates=mandates,
        journal=ActionJournal(tmp_path),
        settings=Settings(state_dir=tmp_path),
    )

    action = await cycle.run(vault)

    assert action.status == "executed", action.error
    assert action.warnings, "a banded acceptance left no trace on the action"
    assert action.warnings[0].constraint == "max_position_pct"


async def test_a_clean_decision_records_no_warnings(tmp_path):
    """Warnings must mean something. If every action carried one, the feed would
    train a reader to ignore them."""
    import json

    from agent.chain.stub import StubVaultClient
    from agent.config import Settings
    from agent.loop.cycle import DecisionCycle
    from agent.loop.engine import LlmDecisionEngine
    from agent.loop.store import ActionJournal
    from agent.mandate.store import MandateStore
    from agent.model.backends.scripted import ScriptedBackend
    from agent.providers.fixture_data import FixtureDataRegistry
    from agent.providers.fixture_venue import FixtureVenueRegistry

    vault = "0x1111111111111111111111111111111111111111"
    mandates = MandateStore(tmp_path)
    mandates.save(vault, fixtures.mandate())

    raw = json.dumps(
        {
            "action": "hold",
            "reasoning": "The book is inside its bands and nothing on offer pays for a trade.",
            "facts_used": ["f1"],
            "confidence": 0.7,
        }
    )
    cycle = DecisionCycle(
        engine=LlmDecisionEngine(ScriptedBackend([raw]), max_attempts=1),
        registry=FixtureDataRegistry(),
        venues=FixtureVenueRegistry(),
        vault_client=StubVaultClient(),
        mandates=mandates,
        journal=ActionJournal(tmp_path),
        settings=Settings(state_dir=tmp_path),
    )

    action = await cycle.run(vault)

    assert action.status == "held"
    assert action.warnings == []
