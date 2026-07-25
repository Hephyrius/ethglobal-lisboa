"""The validation layer, which is the only thing between the model and the key.

Master plan §12 makes this Lane B's first gate: *"pytest on validation retry
(feed deliberately malformed model output, assert recovery)."*

Every malformed response below is a real failure mode of small instruct models,
not an invented edge case. The tests are grouped by validation layer so a
failure says which layer regressed.
"""

from __future__ import annotations

import json

import pytest
from curator_schema import AllocationDecision

from agent import fixtures
from agent.mandate.constraints import check_decision
from agent.model.backends.scripted import ScriptedBackend
from agent.model.validation import (
    DecisionRejected,
    generate_validated_decision,
    validate_decision,
)


@pytest.fixture(scope="module")
def mandate():
    return fixtures.mandate()


@pytest.fixture(scope="module")
def snapshot():
    return fixtures.market_snapshot()


@pytest.fixture(scope="module")
def good_json():
    return fixtures.allocation_decision().model_dump_json(exclude_none=True)


def _decision(**overrides) -> str:
    """The golden decision as raw JSON, with fields replaced."""
    payload = json.loads(fixtures.allocation_decision().model_dump_json(exclude_none=True))
    payload.update(overrides)
    return json.dumps(payload)


# ── the fixtures must agree with each other ───────────────────────────────


def test_golden_decision_is_legal_under_the_golden_mandate(mandate, snapshot, good_json):
    """If this fails, either the fixtures disagree or a constraint is misread.

    It is the anchor for every other test here: the shared golden decision
    allocates USDC 0.70 / WETH 0.30 against a mandate with max_position_pct 0.60
    and min_cash_pct 0.20, which only passes if `max_position_pct` caps risk
    positions rather than the base-asset cash leg. See
    `agent/mandate/constraints.py`.
    """
    decision = validate_decision(good_json, mandate, snapshot)
    assert decision.action == "rebalance"
    assert check_decision(decision, mandate) == []


# ── layer 1: extraction ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("label", "wrap"),
    [
        ("code fence", lambda j: f"```json\n{j}\n```"),
        ("bare fence", lambda j: f"```\n{j}\n```"),
        ("prose preamble", lambda j: f"Here is my decision:\n\n{j}"),
        ("prose postscript", lambda j: f"{j}\n\nLet me explain my thinking..."),
        ("both", lambda j: f"Sure! My decision:\n```json\n{j}\n```\nHope that helps."),
        ("reasoning block", lambda j: f"<think>\nHmm, {{maybe}} 0.5?\n</think>\n{j}"),
        ("leading whitespace", lambda j: f"\n\n   {j}   \n"),
    ],
)
def test_recovers_json_from_model_packaging(mandate, snapshot, good_json, label, wrap):
    assert validate_decision(wrap(good_json), mandate, snapshot).action == "rebalance"


@pytest.mark.parametrize(
    ("label", "mangle"),
    [
        # `..., "confidence": 0.68,}`
        ("before closing brace", lambda j: j[:-1].rstrip() + ",}"),
        # `[{"asset": "USDC", "weight": 0.7},]`
        ("before closing bracket", lambda j: j.replace("}]", "},]")),
    ],
)
def test_repairs_a_trailing_comma(mandate, snapshot, good_json, label, mangle):
    """Legal in JavaScript, not in JSON, and very common from models."""
    mangled = mangle(good_json)
    assert mangled != good_json, "the test input was not actually mangled"
    with pytest.raises(json.JSONDecodeError):
        json.loads(mangled)
    assert validate_decision(mangled, mandate, snapshot)


def test_picks_the_object_that_looks_like_a_decision(mandate, snapshot, good_json):
    """A model that drafts, reconsiders, then answers emits two objects."""
    noisy = f'{{"scratch": "let me think about this"}}\n\n{good_json}'
    assert validate_decision(noisy, mandate, snapshot).action == "rebalance"


def test_braces_inside_reasoning_do_not_break_extraction(mandate, snapshot):
    """The scanner must be string-aware — reasoning text quotes real numbers."""
    raw = _decision(reasoning="Morpho {sic} pays 5.87% vs Aave's 4.32% — see {f2}.")
    assert validate_decision(raw, mandate, snapshot)


@pytest.mark.parametrize("raw", ["", "   ", "I cannot help with that.", "{not json at all"])
def test_unrecoverable_responses_are_rejected(mandate, snapshot, raw):
    with pytest.raises(ValueError):
        validate_decision(raw, mandate, snapshot)


# ── layer 2: schema ───────────────────────────────────────────────────────


def test_unknown_action_is_rejected(mandate, snapshot):
    with pytest.raises(ValueError, match="schema"):
        validate_decision(_decision(action="yolo"), mandate, snapshot)


def test_unknown_field_is_rejected(mandate, snapshot):
    """`extra="forbid"` — a typo must fail at the boundary, not propagate."""
    with pytest.raises(ValueError, match="schema"):
        validate_decision(_decision(leverage=3), mandate, snapshot)


def test_missing_reasoning_is_rejected(mandate, snapshot):
    payload = json.loads(_decision())
    del payload["reasoning"]
    with pytest.raises(ValueError, match="reasoning"):
        validate_decision(json.dumps(payload), mandate, snapshot)


def test_schema_error_message_names_the_field(mandate, snapshot):
    """The message is fed back to the model, so it has to be actionable."""
    with pytest.raises(ValueError) as caught:
        validate_decision(_decision(confidence=4.2), mandate, snapshot)
    assert "confidence" in str(caught.value)


# ── layer 3: the mandate ──────────────────────────────────────────────────


def test_forbidden_asset_is_rejected(mandate, snapshot):
    raw = _decision(
        target_allocations=[
            {"asset": "USDC", "weight": 0.7},
            {"asset": "cbETH", "weight": 0.3},
        ]
    )
    with pytest.raises(ValueError) as caught:
        validate_decision(raw, mandate, snapshot)
    message = str(caught.value)
    assert "cbETH" in message
    # The model must be told the limit, not just that it broke one.
    assert "USDC" in message and "WETH" in message


def test_weights_that_do_not_sum_to_one_are_rejected(mandate, snapshot):
    raw = _decision(
        target_allocations=[
            {"asset": "USDC", "weight": 0.7},
            {"asset": "WETH", "weight": 0.7},
        ]
    )
    with pytest.raises(ValueError, match="sum"):
        validate_decision(raw, mandate, snapshot)


def test_small_rounding_in_weights_is_tolerated(mandate, snapshot):
    """0.33 x 3 is right in intent and 0.01 short in arithmetic."""
    raw = _decision(
        target_allocations=[
            {"asset": "USDC", "weight": 0.67},
            {"asset": "WETH", "weight": 0.33},
        ],
    )
    assert validate_decision(raw, mandate, snapshot)


def test_oversized_risk_position_is_rejected(mandate, snapshot):
    """WETH at 80% against a 60% ceiling."""
    raw = _decision(
        target_allocations=[
            {"asset": "USDC", "weight": 0.2},
            {"asset": "WETH", "weight": 0.8},
        ]
    )
    with pytest.raises(ValueError, match="ceiling"):
        validate_decision(raw, mandate, snapshot)


def test_cash_floor_is_enforced(mandate, snapshot):
    """min_cash_pct is 20%; 5% in the base asset breaches it."""
    raw = _decision(
        target_allocations=[
            {"asset": "USDC", "weight": 0.05},
            {"asset": "WETH", "weight": 0.95},
        ]
    )
    with pytest.raises(ValueError) as caught:
        validate_decision(raw, mandate, snapshot)
    assert "cash" in str(caught.value)


def test_too_many_actions_in_one_tick_is_rejected(mandate, snapshot):
    """max_actions_per_tick is 2."""
    swap = {
        "venue": "uniswap",
        "kind": "swap",
        "token_in": "USDC",
        "token_out": "WETH",
        "pct_of_holdings": 0.1,
    }
    with pytest.raises(ValueError, match="at most"):
        validate_decision(_decision(venue_intents=[swap, swap, swap]), mandate, snapshot)


def test_hold_carrying_intents_is_rejected(mandate, snapshot):
    """Would trade while telling the depositor it stood still."""
    with pytest.raises(ValueError, match="hold"):
        validate_decision(_decision(action="hold"), mandate, snapshot)


def test_action_with_no_intents_is_rejected(mandate, snapshot):
    """Would execute nothing while reporting that it acted."""
    payload = json.loads(_decision())
    del payload["venue_intents"]
    with pytest.raises(ValueError, match="nothing would happen"):
        validate_decision(json.dumps(payload), mandate, snapshot)


def test_swap_with_no_size_is_rejected(mandate, snapshot):
    raw = _decision(
        venue_intents=[
            {"venue": "uniswap", "kind": "swap", "token_in": "USDC", "token_out": "WETH"}
        ]
    )
    with pytest.raises(ValueError, match="amount_in or pct_of_holdings"):
        validate_decision(raw, mandate, snapshot)


def test_all_breaches_are_reported_together(mandate, snapshot):
    """One retry that fixes three problems beats three retries."""
    raw = _decision(
        target_allocations=[
            {"asset": "cbETH", "weight": 0.9},
            {"asset": "USDC", "weight": 0.5},
        ]
    )
    with pytest.raises(ValueError) as caught:
        validate_decision(raw, mandate, snapshot)
    message = str(caught.value)
    assert "cbETH" in message and "sum" in message


# ── layer 4: grounding ────────────────────────────────────────────────────


def test_invented_fact_id_is_rejected(mandate, snapshot):
    """The cheapest signal that a model stopped reading its inputs."""
    with pytest.raises(ValueError) as caught:
        validate_decision(_decision(facts_used=["f1", "f99"]), mandate, snapshot)
    message = str(caught.value)
    assert "f99" in message
    assert "f1" in message, "the model must be told which ids are real"


def test_action_citing_no_facts_is_rejected(mandate, snapshot):
    with pytest.raises(ValueError, match="cites no facts"):
        validate_decision(_decision(facts_used=[]), mandate, snapshot)


def test_hold_may_cite_nothing(mandate, snapshot):
    """Sometimes the honest reason to hold is that nothing could be read."""
    payload = json.loads(_decision(action="hold", facts_used=[]))
    del payload["venue_intents"]
    assert validate_decision(json.dumps(payload), mandate, snapshot).action == "hold"


# ── reject-and-retry: the §12 gate ────────────────────────────────────────


async def test_recovers_from_malformed_output_on_retry(mandate, snapshot, good_json):
    """Deliberately malformed output, then recovery. The gate from §12."""
    backend = ScriptedBackend(["I think we should probably buy some ETH?", good_json])

    result = await generate_validated_decision(
        backend, [{"role": "user", "content": "decide"}], mandate=mandate, snapshot=snapshot
    )

    assert result.decision.action == "rebalance"
    assert result.attempts == 2
    assert result.retries == 1
    assert len(result.failures) == 1


async def test_recovers_from_a_mandate_breach_on_retry(mandate, snapshot, good_json):
    breach = _decision(
        target_allocations=[{"asset": "cbETH", "weight": 1.0}],
    )
    backend = ScriptedBackend([breach, good_json])

    result = await generate_validated_decision(
        backend, [{"role": "user", "content": "decide"}], mandate=mandate, snapshot=snapshot
    )
    assert result.retries == 1


async def test_the_retry_tells_the_model_exactly_what_was_wrong(mandate, snapshot, good_json):
    """A bare 'try again' teaches nothing and wastes the tick.

    The correction must name the breach and the limit, and the model must see
    its own rejected output in context.
    """
    breach = _decision(target_allocations=[{"asset": "cbETH", "weight": 1.0}])
    backend = ScriptedBackend([breach, good_json])

    await generate_validated_decision(
        backend, [{"role": "user", "content": "decide"}], mandate=mandate, snapshot=snapshot
    )

    second_conversation = backend.calls[1]
    assert second_conversation[-2]["role"] == "assistant"
    assert "cbETH" in second_conversation[-2]["content"], "model must see its own output"

    correction = second_conversation[-1]
    assert correction["role"] == "user"
    assert "cbETH" in correction["content"]
    assert "USDC" in correction["content"], "the correction must state the permitted set"


async def test_exhausted_retries_raise_and_nothing_is_returned(mandate, snapshot):
    """Fail closed. There is no partial credit when the agent holds a key."""
    backend = ScriptedBackend(["not json", "still not json", "nope"])

    with pytest.raises(DecisionRejected) as caught:
        await generate_validated_decision(
            backend,
            [{"role": "user", "content": "decide"}],
            mandate=mandate,
            snapshot=snapshot,
            max_attempts=3,
        )

    assert caught.value.attempts == 3
    assert len(caught.value.failures) == 3


async def test_a_valid_first_response_costs_no_retries(mandate, snapshot, good_json):
    backend = ScriptedBackend([good_json])
    result = await generate_validated_decision(
        backend, [{"role": "user", "content": "decide"}], mandate=mandate, snapshot=snapshot
    )
    assert result.attempts == 1
    assert result.retries == 0
    assert result.failures == []
    assert len(backend.calls) == 1


async def test_retry_budget_is_honoured(mandate, snapshot):
    backend = ScriptedBackend(["bad"])
    with pytest.raises(DecisionRejected):
        await generate_validated_decision(
            backend,
            [{"role": "user", "content": "decide"}],
            mandate=mandate,
            snapshot=snapshot,
            max_attempts=2,
        )
    assert len(backend.calls) == 2, "must not exceed the configured attempt budget"


# ── the decision that reaches the chain is a real, typed object ───────────


def test_validated_output_is_an_allocation_decision(mandate, snapshot, good_json):
    result = validate_decision(good_json, mandate, snapshot)
    assert isinstance(result, AllocationDecision)
    assert result.facts_used and set(result.facts_used) <= {f.id for f in snapshot.facts}


# ── retry-hint quality: the message IS the mechanism ──────────────────────
#
# Observed live, and the reason these exist: the model omitted `token_out` on a
# swap. `VenueIntent` is a union of three shapes, so pydantic reported failures
# for all three — twelve errors, truncated to six, with the one real problem
# buried among complaints that the swap was not a valid `AquaShipIntent`. The
# model failed three attempts in a row, 260 seconds, without ever being told the
# single thing that was wrong.
#
# Layer 2 exists to teach the model what to fix. A message describing two shapes
# it never attempted is worse than no message at all.


def _swap_missing_token_out() -> str:
    return json.dumps(
        {
            "action": "rebalance",
            "reasoning": "Rebalance toward the target split.",
            "facts_used": ["f1"],
            "target_allocations": [
                {"asset": "USDC", "weight": 0.5},
                {"asset": "WETH", "weight": 0.5},
            ],
            "venue_intents": [
                {"venue": "uniswap", "kind": "swap", "token_in": "WETH", "pct_of_holdings": 0.5}
            ],
        }
    )


def test_a_union_error_names_only_the_shape_the_model_attempted(mandate, snapshot):
    with pytest.raises(ValueError) as caught:
        validate_decision(_swap_missing_token_out(), mandate, snapshot)
    message = str(caught.value)

    assert "token_out" in message, "the actual problem must be stated"
    for unattempted in ("AquaShipIntent", "AquaDockIntent", "tokens", "amounts"):
        assert unattempted not in message, (
            f"the hint mentions {unattempted!r}, which the model never wrote — "
            "that is the noise that made three retries fail"
        )


def test_the_union_variant_is_stripped_from_the_reported_path(mandate, snapshot):
    """The model wrote `venue_intents[0]`, not `venue_intents[0].SwapIntent`.

    Pointing at a path it did not write is one more thing to be confused by.
    """
    with pytest.raises(ValueError) as caught:
        validate_decision(_swap_missing_token_out(), mandate, snapshot)

    assert "venue_intents.0.token_out" in str(caught.value)
    assert "SwapIntent" not in str(caught.value)


def test_the_hint_stays_short_enough_to_act_on(mandate, snapshot):
    """One missing field should produce one line, not a wall."""
    with pytest.raises(ValueError) as caught:
        validate_decision(_swap_missing_token_out(), mandate, snapshot)

    body = str(caught.value).split("—", 1)[-1]
    assert body.count(";") <= 1, f"too many errors reported for one mistake: {body}"


def test_errors_outside_a_union_are_still_reported(mandate, snapshot):
    """Filtering union noise must not swallow ordinary field errors."""
    with pytest.raises(ValueError) as caught:
        validate_decision(_decision(action="yolo", confidence=4.2), mandate, snapshot)
    message = str(caught.value)

    assert "action" in message and "confidence" in message
