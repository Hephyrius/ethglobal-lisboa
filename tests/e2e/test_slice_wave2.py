"""Wave 2's narrative, end to end: idle capital moves, the band is visible, persona is not law.

The other five lanes each test their own half of these. This file tests the joins, which is the
part no lane owns:

* Lane F ships `tolerance_band_pct` and `AgentAction.warnings`; Lane B decides what bends and
  records it; Lane E renders it. A warning that validates in isolation and never reaches the feed
  would pass both of their suites and fail the product.
* Lane F ships `Mandate.persona`; Lane B composes it into the prompt. The invariant that matters is
  a *negative* one — persona changes what the agent prefers and never what it may do — and a
  negative invariant is exactly what a lane testing its own code tends not to disprove.

**One test here is allowed to fail a live stack rather than skip it.** The Wave 2 definition of
done calls a tick that deploys idle capital *"the single most important box"*. A suite that went
green while that box was empty would be the same mistake as an R5 that passed on a dead position
(#39): an assertion that manufactures confidence. So when the stack is genuinely live and no
deployment has ever reached the feed, this suite says so.
"""

from __future__ import annotations

import json
import pathlib

import httpx
import pytest
from agent.mandate.constraints import banded_warnings, check_decision
from curator_schema import (
    AgentAction,
    AllocationDecision,
    ConstraintWarning,
    Mandate,
    SupplyIntent,
    SwapIntent,
    TargetAllocation,
)

PRESETS = pathlib.Path(__file__).resolve().parents[2] / "packages" / "schema" / "presets"

#: The intents that put capital to work. A swap rotates what the vault holds and earns nothing by
#: itself, so it does not count as deployment — that distinction is the whole point of §B1.
DEPLOYING_INTENTS = {"supply", "ship"}

#: Constraints the band may never touch (plan §3.1). A ceiling that was already compared against a
#: worst-case bound is not an estimate, and an allowlist is not numeric.
NEVER_BANDED = {"max_slippage_bps", "allowed_assets", "permitted_venues", "permitted_data_sources"}


def _preset(key: str) -> Mandate:
    return Mandate.model_validate(json.loads((PRESETS / f"{key}.json").read_text(encoding="utf-8")))


@pytest.fixture(scope="module")
def actions(api: str, deployments: dict) -> list[AgentAction]:
    """Every journalled action across every vault the API knows about.

    Deliberately not just the demo vault: a deployment that happened on a vault created during
    genesis still proves the capability, and pinning this to one address is how a passing
    capability gets reported as missing.
    """
    vaults = [deployments["demoVault"]]
    for extra in deployments.get("vaults", []) or []:
        addr = extra if isinstance(extra, str) else extra.get("address")
        if addr and addr not in vaults:
            vaults.append(addr)

    out: list[AgentAction] = []
    with httpx.Client(timeout=30.0) as client:
        for vault in vaults:
            try:
                resp = client.get(f"{api}/vault/{vault}/decisions", params={"limit": 200})
            except Exception:  # noqa: BLE001 — an unreachable vault is not this test's subject
                continue
            if resp.status_code != 200:
                continue
            # Validating here rather than reading raw JSON: if the API emits an action the frozen
            # schema rejects, that is itself the finding, and it should surface as a loud error
            # rather than as a quiet zero-match.
            out.extend(AgentAction.model_validate(a) for a in resp.json())
    return out


# ── the headline: idle capital gets deployed ──────────────────────────────────────────────────


def test_a_deployment_reached_the_decision_feed(actions: list[AgentAction]) -> None:
    """Wave 2's most important box: capital was put to work, and it is on the record.

    Fails rather than skips when the stack is live. See the module docstring.
    """
    assert actions, "no journalled actions at all — has a tick ever run against this stack?"

    deployments = [
        a
        for a in actions
        if a.decision
        and any(i.kind in DEPLOYING_INTENTS for i in (a.decision.venue_intents or []))
    ]
    assert deployments, (
        "no action in the feed deploys idle capital. Every intent is a swap or a hold, which is "
        "the Wave 1 behaviour Wave 2 exists to fix: the agent rotates what it holds and then sits "
        "on it. §B1 — deploying is the default, holding is a choice that needs a stated reason."
    )


def test_a_deployment_says_why_in_its_own_words(actions: list[AgentAction]) -> None:
    """A deployment with empty reasoning is a transaction, not curation.

    The product claim is data → reasoning → transaction, so the reasoning has to exist and the
    action has to be one a reader can trace. This does not grade the prose; it checks there is
    some, and that the action is not silently a rejected one.
    """
    deployments = [
        a
        for a in actions
        if a.decision
        and any(i.kind in DEPLOYING_INTENTS for i in (a.decision.venue_intents or []))
    ]
    if not deployments:
        pytest.skip("covered by test_a_deployment_reached_the_decision_feed")

    assert any(
        a.status in {"executed", "pending"} and (a.decision.reasoning or "").strip()
        for a in deployments
    ), "deployments exist but none is an executed action carrying reasoning"


# ── the band: recorded, rendered, and never applied where it must not be ───────────────────────


def test_every_recorded_warning_is_well_formed(actions: list[AgentAction]) -> None:
    """Whatever the harness records, the feed must be able to render it.

    `AgentAction.warnings` is new this wave, so this is the first place the two ends meet: Lane B
    populates it, Lane E reads it, and neither would notice a warning naming a constraint that
    cannot be banded.
    """
    for action in actions:
        for w in action.warnings:
            assert w.kind == "tolerance_band"
            assert w.constraint not in NEVER_BANDED, (
                f"{action.id} records a band on {w.constraint!r}. A slippage ceiling was already "
                f"compared against a worst case, and an allowlist is not numeric — banding either "
                f"is how 'less rigid' becomes 'no rules'."
            )
            assert 0 <= w.band_pct <= 0.5
            assert w.message.strip(), "a warning with no message cannot be rendered"


def test_a_small_breach_is_banded_and_a_large_one_is_not() -> None:
    """The band's actual behaviour, through Lane B's own function and Lane F's own preset.

    Deterministic and stack-free on purpose: this is the assertion that would catch the band being
    silently widened, and it must not be able to skip.
    """
    mandate = _preset("balanced-two-asset")  # 60% cap, 5% band -> 63% admitted, 70% not
    assert mandate.constraints.max_position_pct == 0.6
    assert mandate.constraints.tolerance_band_pct == 0.05

    just_over = AllocationDecision(
        action="rebalance",
        reasoning="Nudge WETH slightly past the cap; the swap priced a hair differently.",
        target_allocations=[
            TargetAllocation(asset="WETH", weight=0.62),
            TargetAllocation(asset="USDC", weight=0.38),
        ],
        venue_intents=[SwapIntent(token_in="USDC", token_out="WETH", pct_of_holdings=0.1)],
    )
    far_over = AllocationDecision(
        action="rebalance",
        reasoning="Take WETH well past the cap.",
        target_allocations=[
            TargetAllocation(asset="WETH", weight=0.85),
            TargetAllocation(asset="USDC", weight=0.15),
        ],
        venue_intents=[SwapIntent(token_in="USDC", token_out="WETH", pct_of_holdings=0.5)],
    )

    banded = banded_warnings(just_over, mandate, None)
    assert banded, "62% against a 60% cap is inside a 5% band and should be accepted with a warning"
    assert all(isinstance(w, ConstraintWarning) for w in banded)
    assert all(w.constraint not in NEVER_BANDED for w in banded)

    assert check_decision(far_over, mandate), (
        "85% against a 60% cap is far outside the band and must still be rejected — a band that "
        "swallows this is not a band, it is a removed constraint"
    )


def test_the_band_never_reaches_the_slippage_ceiling() -> None:
    """The one exemption the plan is most emphatic about, asserted rather than assumed.

    Banding a slippage ceiling means paying more than the mandate's stated maximum cost, silently,
    which is a different kind of mistake from drifting an allocation by a percent.
    """
    mandate = _preset("conservative-income")  # 10 bps, a deliberately tight ceiling
    assert mandate.constraints.max_slippage_bps == 10
    for warning in banded_warnings(
        AllocationDecision(
            action="rebalance",
            reasoning="Supply the idle cash.",
            venue_intents=[SupplyIntent(asset="USDC", pct_of_holdings=0.5)],
        ),
        mandate,
        None,
    ):
        assert warning.constraint != "max_slippage_bps"


# ── personas are taste, constraints are law ───────────────────────────────────────────────────


def test_a_persona_cannot_widen_a_constraint() -> None:
    """The negative invariant, at the seam.

    The aggressive preset carries a persona that openly prefers concentration. If persona were
    doing any of the work, a decision matching its stated taste would sail through. It must not:
    the constraints are checked against the mandate, and the persona is not part of that check.
    """
    aggressive = _preset("opportunistic")
    assert aggressive.persona is not None
    assert aggressive.persona.conviction == "high"

    # Exactly what that persona would argue for: everything in one leg, floor ignored.
    over_concentrated = AllocationDecision(
        action="rebalance",
        reasoning="Conviction is high and the yield is the best available. Size up.",
        target_allocations=[
            TargetAllocation(asset="WETH", weight=1.0),
            TargetAllocation(asset="USDC", weight=0.0),
        ],
        venue_intents=[SwapIntent(token_in="USDC", token_out="WETH", pct_of_holdings=1.0)],
    )
    assert check_decision(over_concentrated, aggressive), (
        "an aggressive persona reached 100% of one asset past an 80% cap and a 5% cash floor. "
        "Persona is taste; constraints are law. If those merge, 'aggressive' is an exploit."
    )

    # And the same decision is equally rejected with no persona at all, which is what shows the
    # persona neither loosened nor tightened anything.
    neutral = aggressive.model_copy(update={"persona": None})
    assert check_decision(over_concentrated, neutral) == check_decision(
        over_concentrated, aggressive
    ), "the verdict changed when the persona was removed — persona is influencing the gate"


def test_a_persona_cannot_reach_an_unpermitted_asset() -> None:
    """The other half: taste may not widen `allowed_assets`, which is not numeric and not banded."""
    aggressive = _preset("opportunistic")
    reaching = AllocationDecision(
        action="enter",
        reasoning="The best risk-adjusted return on the board is somewhere this mandate has "
        "never heard of.",
        venue_intents=[SwapIntent(token_in="USDC", token_out="AERO", pct_of_holdings=0.2)],
    )
    violations = check_decision(reaching, aggressive)
    assert violations, "a persona reached an asset outside allowed_assets and nothing stopped it"
    assert any("AERO" in str(v) or "allowed" in str(v).lower() for v in violations)
