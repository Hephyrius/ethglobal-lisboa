"""What a paused vault is for.

Lane A's `pause()` puts the vault in wind-down: the contract reverts any batch
that raises a non-base balance, so **selling is permitted and buying cannot
execute**. That is the backstop. This lane has to actually *drive* the unwind,
because a paused vault that holds is a vault whose depositors still cannot leave
— `redeem` pays in the base asset, so a holder whose claim exceeds the vault's
cash cannot exit through it at all.

The tests are grouped by the thing each one protects:

1. the paused flag is **read**, not assumed;
2. the direction rule is a **separate** check, not a relaxation of the existing
   one — Wave 1's worst bug was an exemption carved into a check that was
   otherwise working;
3. the prompt states one objective rather than two contradictory ones;
4. encumbered positions are freed before the tokens holding them are sold.
"""

from __future__ import annotations

import pytest
from curator_schema import AllocationDecision

from agent import fixtures
from agent.mandate.constraints import (
    check_projected_outcome,
    check_rebalance_direction,
    check_wind_down_direction,
)
from agent.model.prompts.curator import decision_messages
from agent.model.validation import validate_decision


@pytest.fixture
def mandate():
    return fixtures.mandate()


@pytest.fixture
def vault():
    return fixtures.vault_state()


@pytest.fixture
def paused(vault):
    return vault.model_copy(update={"paused": True})


def _decision(**overrides) -> AllocationDecision:
    payload = {
        "action": "exit",
        "reasoning": "Winding down: converting the book to USDC so redemptions clear.",
        "facts_used": ["f5"],
        "target_allocations": [{"asset": "USDC", "weight": 1.0}],
        "confidence": 0.9,
    }
    payload.update(overrides)
    return AllocationDecision.model_validate(payload)


def _sell(token_in="WETH", pct=0.5) -> dict:
    return {
        "venue": "uniswap",
        "kind": "swap",
        "token_in": token_in,
        "token_out": "USDC",
        "pct_of_holdings": pct,
    }


# ── the flag is read, not assumed ─────────────────────────────────────────


def test_the_golden_vault_is_not_paused(vault):
    """The baseline the other tests move away from."""
    assert vault.paused is False


# ── direction: a separate rule, not a relaxed one ─────────────────────────


def test_selling_toward_the_base_asset_is_permitted(mandate, paused):
    decision = _decision(venue_intents=[_sell()])
    assert check_wind_down_direction(decision, mandate, paused) == []


def test_buying_anything_else_is_refused(mandate, paused):
    """The off-chain twin of Lane A's on-chain check.

    The contract would revert this, which costs gas and surfaces as a failed tick
    with no explanation. Rejecting here costs a retry and tells the model why.
    """
    decision = _decision(
        venue_intents=[
            {
                "venue": "uniswap",
                "kind": "swap",
                "token_in": "USDC",
                "token_out": "WETH",
                "pct_of_holdings": 0.2,
            }
        ]
    )
    violations = check_wind_down_direction(decision, mandate, paused)

    assert violations
    assert "winding down" in violations[0].message


def test_spending_the_base_asset_is_refused(mandate, paused):
    """USDC is what depositors are paid out of; while paused it may only rise."""
    decision = _decision(
        venue_intents=[
            {
                "venue": "uniswap",
                "kind": "swap",
                "token_in": "USDC",
                "token_out": "USDC",
                "pct_of_holdings": 0.2,
            }
        ]
    )
    assert check_wind_down_direction(decision, mandate, paused)


@pytest.mark.parametrize(
    "intent",
    [
        {"venue": "aave", "kind": "supply", "asset": "USDC", "pct_of_holdings": 0.5},
        {
            "venue": "aqua",
            "kind": "ship",
            "tokens": ["USDC", "WETH"],
            "amounts": ["1000000", "1000000000000000000"],
            "program": {"shape": "xyc", "fee_bps": 30},
        },
    ],
)
def test_committing_capital_is_refused_even_though_no_balance_rises(mandate, paused, intent):
    """The gap the contract cannot see, and the reason this layer exists.

    An Aqua ship moves no tokens at all — it records a claim against balances
    that stay put — so Lane A's end-of-batch balance check passes it. A supply
    swaps the underlying for a receipt token. Neither raises a non-base balance
    in the way the contract measures, and both commit capital when the job is to
    free it.
    """
    violations = check_wind_down_direction(_decision(venue_intents=[intent]), mandate, paused)

    assert violations
    assert "commits capital instead of freeing it" in violations[0].message


def test_the_two_direction_rules_judge_the_same_decision_differently(mandate, vault, paused):
    """Wave 1's worst bug was an exemption carved into a working check, so these
    are two rules rather than one with a carve-out.

    The decision that separates them is a liquidation *against the mandate's own
    targets* — the shape a real wind-down produces on a vault whose mandate says
    70/30. Paused it is correct; trading it is selling the underweight leg.

    Worth stating what does **not** separate them: a decision that declares
    `USDC 1.0` as its target and liquidates into it is legal in both modes, and
    always was. Layer 5 compares trades to the decision's *own* targets, so
    declaring the destination makes the trade coherent. Wind-down's real work is
    telling the model to do this, suspending layer 6's overshoot rule, and
    refusing the commits below.

    So the book here is drifted **under** its WETH target, which is the one shape
    where selling WETH is what layer 5 exists to refuse — and is exactly what a
    wind-down must do anyway.
    """
    drifted = vault.model_copy(
        update={
            "holdings": [
                vault.holdings[0].model_copy(update={"value_in_asset": "2250000000"}),
                vault.holdings[1].model_copy(update={"value_in_asset": "250000000"}),
                *vault.holdings[2:],
            ]
        }
    )
    decision = _decision(
        venue_intents=[_sell(pct=1.0)],
        target_allocations=[
            {"asset": "USDC", "weight": 0.7},
            {"asset": "WETH", "weight": 0.3},
        ],
    )

    assert check_wind_down_direction(
        decision, mandate, drifted.model_copy(update={"paused": True})
    ) == []
    assert check_rebalance_direction(decision, drifted) != []


# ── layer 6: the suspended target, and what stays on ──────────────────────


def test_the_overshoot_rule_stands_down_while_paused(mandate, paused, vault):
    """A liquidation moves every asset away from the mandate's targets, which is
    the point. Judging it against them would reject every wind-down trade."""
    decision = _decision(
        venue_intents=[_sell(pct=1.0)],
        target_allocations=[{"asset": "USDC", "weight": 0.7}, {"asset": "WETH", "weight": 0.3}],
    )

    assert check_projected_outcome(decision, mandate, paused) == []
    assert check_projected_outcome(decision, mandate, vault) != []


def test_the_floor_and_ceiling_still_run_while_paused(mandate, paused):
    """Not an exemption — a no-op. Selling raises cash and lowers positions, so a
    genuine wind-down trade cannot breach either, and leaving them on means there
    is no relaxed path for a bad one to slip through."""
    decision = _decision(venue_intents=[_sell(pct=1.0)])
    projected = check_projected_outcome(decision, mandate, paused)

    assert projected == [], "a full liquidation breaches neither the floor nor the cap"


# ── the whole validator, end to end ───────────────────────────────────────


def test_a_liquidation_passes_every_layer_while_paused(mandate, paused):
    """The property B3 exists for: a paused vault can actually act."""
    snapshot = fixtures.market_snapshot()
    raw = _decision(venue_intents=[_sell(pct=1.0)]).model_dump_json()

    decision = validate_decision(raw, mandate, snapshot, paused)
    assert decision.action == "exit"


def test_the_same_liquidation_is_rejected_while_trading(mandate, vault):
    """The mirror, and it is what proves the paused case is doing work rather
    than the decision being legal all along.

    Uses the mandate's own 70/30 targets, because a decision that *declares* 100%
    USDC is coherent in both modes — see the direction test above.
    """
    snapshot = fixtures.market_snapshot()
    raw = _decision(
        venue_intents=[_sell(pct=1.0)],
        target_allocations=[
            {"asset": "USDC", "weight": 0.7},
            {"asset": "WETH", "weight": 0.3},
        ],
    ).model_dump_json()

    with pytest.raises(ValueError):
        validate_decision(raw, mandate, snapshot, vault)


def test_a_paused_buy_is_rejected_with_a_correction_naming_the_base_asset(mandate, paused):
    snapshot = fixtures.market_snapshot()
    raw = _decision(
        venue_intents=[
            {
                "venue": "uniswap",
                "kind": "swap",
                "token_in": "USDC",
                "token_out": "WETH",
                "pct_of_holdings": 0.2,
            }
        ]
    ).model_dump_json()

    with pytest.raises(ValueError) as raised:
        validate_decision(raw, mandate, snapshot, paused)

    assert "winding down" in str(raised.value)
    assert "USDC" in str(raised.value)


# ── the prompt states one objective, not two ──────────────────────────────


def test_the_prompt_says_the_vault_is_winding_down(mandate, paused):
    rendered = decision_messages(mandate, fixtures.market_snapshot(), paused)[-1]["content"]

    assert "THIS VAULT IS WINDING DOWN" in rendered
    assert "target weights stated below are suspended" in rendered


def test_the_wind_down_prompt_does_not_also_tell_it_to_deploy_idle_capital(mandate, paused):
    """The contradiction this replaced rather than layered over.

    The normal step 4 says idle capital is a position earning nothing and that
    deploying it is the default — exactly backwards when cash is the goal.
    Showing both and hoping the model picks correctly is how a paused vault ends
    up supplying to Aave, getting rejected, and burning the tick it was supposed
    to spend selling.
    """
    rendered = decision_messages(mandate, fixtures.market_snapshot(), paused)[-1]["content"]

    assert "Deploying it into a permitted venue is the default" not in rendered
    assert "Decide what to sell now" in rendered


def test_the_normal_prompt_is_unchanged_when_not_paused(mandate, vault):
    rendered = decision_messages(mandate, fixtures.market_snapshot(), vault)[-1]["content"]

    assert "WINDING DOWN" not in rendered
    assert "Deploying it into a permitted venue is the default" in rendered


def test_the_prompt_says_withdrawals_are_not_paused(mandate, paused):
    """Lane A's §A2 boundary, restated where the model can act on it.

    It matters here for the same reason it matters in the UI: *paused* alone
    reads as "the money is stuck", which is the exact opposite of the truth.
    """
    rendered = decision_messages(mandate, fixtures.market_snapshot(), paused)[-1]["content"]
    assert "Withdrawals are not paused" in rendered


def test_encumbered_positions_are_named_in_the_prompt(mandate, paused):
    """The golden vault holds an Aqua position, and a swap of tokens still
    committed to it reverts."""
    rendered = decision_messages(mandate, fixtures.market_snapshot(), paused)[-1]["content"]

    assert "encumbered, not absent" in rendered
    assert "aqua" in rendered


def test_the_wind_down_prompt_stays_ascii(mandate, paused):
    rendered = "\n".join(
        m["content"] for m in decision_messages(mandate, fixtures.market_snapshot(), paused)
    )
    assert not [c for c in rendered if ord(c) > 127]


# ── ordering: free before you sell ────────────────────────────────────────


def test_a_dock_is_planned_before_the_swap_that_needs_it():
    """One `executeBatch`, so a wrong order costs the whole tick rather than one
    step — and the natural way to write this decision is the wrong way round."""
    from agent.loop.planning import _ordered

    intents = AllocationDecision.model_validate(
        {
            "action": "exit",
            "reasoning": "sell what the Aqua position was holding",
            "facts_used": ["f5"],
            "venue_intents": [
                _sell(),
                {"venue": "aqua", "kind": "dock", "strategy_hash": "0x" + "ab" * 32},
            ],
        }
    ).venue_intents

    assert [i.kind for i in _ordered(intents)] == ["dock", "swap"]


def test_a_withdraw_is_planned_before_the_swap_that_needs_it():
    from agent.loop.planning import _ordered

    intents = AllocationDecision.model_validate(
        {
            "action": "exit",
            "reasoning": "pull the lending position and sell it",
            "facts_used": ["f5"],
            "venue_intents": [
                _sell(),
                {"venue": "aave", "kind": "withdraw", "asset": "USDC"},
            ],
        }
    ).venue_intents

    assert [i.kind for i in _ordered(intents)] == ["withdraw", "swap"]


def test_ordering_is_stable_within_a_group():
    """The agent still chooses the sequence; this only moves releases ahead of
    spends. Reordering two sells would be this lane overruling a decision that
    already passed validation."""
    from agent.loop.planning import _ordered

    intents = AllocationDecision.model_validate(
        {
            "action": "exit",
            "reasoning": "sell both legs",
            "facts_used": ["f5"],
            "venue_intents": [_sell("WETH"), _sell("CBETH")],
        }
    ).venue_intents

    assert [i.token_in for i in _ordered(intents)] == ["WETH", "CBETH"]
