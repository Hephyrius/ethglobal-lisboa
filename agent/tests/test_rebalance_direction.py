"""Validation layers 5 and 6: a swap must go the right way, and land in a legal place.

**Both layers exist because the loop executed real transactions that were wrong,
and every earlier layer passed them.** Two consecutive live ticks on the fork,
from `qwen2.5:3b-instruct-q4_K_M`, each correct in every respect but one:

| tick | diagnosis | direction | size | result |
|---|---|---|---|---|
| `0x129da1a0…` | right | **wrong** | — | 70/30 → 79/21, away from a 50/50 target |
| `0x704f54a2…` | right | right | **`pct: 1.0`** | 79/21 → **0/100**, breaching two limits |

The shared lesson, which is the reason both checks are here rather than in the
prompt: **the mandate limits were being applied to what the model *declared*, never
to what its trade would *do*.** Declared intent and realised effect are different
things, and only the second one spends money.

Layer 5 checks the sign. Layer 6 projects the trade forward and checks where it
lands. Neither is a property of the mandate alone — both compare the decision to
reality — so they hold whatever a mandate says.

The first failure, in full:

    current   70.0% USDC / 30.0% WETH
    target    50.0% USDC / 50.0% WETH   (the model's own target_allocations)
    reasoning "deviates from the target allocations ... by more than the
               tolerance of 5 percentage points"      <- correct
    intent    swap WETH -> USDC                        <- backwards
    result    ~79% USDC / ~21% WETH, tx 0x129da1a0...

Right diagnosis, wrong sign, real money. **Layers 1 through 4 all passed it**, and
correctly so: the JSON was well-formed, the schema matched, both assets were
permitted, the weights summed to 1, the action label agreed with the intents, and
every cited fact was real. The decision was internally consistent in every respect
except the one that decides whether it makes money.

The check is deliberately a property of the *decision against reality* rather
than of the mandate, so it holds whatever the mandate says: you may not sell an
asset that is already below its target, nor buy one already above it.
"""

from __future__ import annotations

import pytest
from curator_schema import AllocationDecision, Holding, SwapIntent, VaultState

from agent import fixtures
from agent.mandate.constraints import check_rebalance_direction
from agent.model.validation import validate_decision

USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
WETH = "0x4200000000000000000000000000000000000006"


def _vault(usdc_value: int, weth_value: int) -> VaultState:
    """A vault whose weights are exactly the two values given (6dp base asset)."""
    total = usdc_value + weth_value
    return VaultState(
        address="0x0E2c0e50E67B96C9C401C94e111a3DBD00DEB5d1",
        asset=USDC,
        asset_decimals=6,
        total_assets=str(total),
        total_supply=str(total * 10**12),
        holdings=[
            Holding(
                token=USDC,
                symbol="USDC",
                balance=str(usdc_value),
                decimals=6,
                value_in_asset=str(usdc_value),
            ),
            Holding(
                token=WETH,
                symbol="WETH",
                balance="403383142516784630",
                decimals=18,
                value_in_asset=str(weth_value),
            ),
        ],
    )


#: The exact book that produced the bad trade: 1,750 USDC and 749.88 of WETH.
SEVENTY_THIRTY = _vault(1_750_000000, 749_880000)


def _decision(token_in: str, token_out: str, targets: dict[str, float]) -> AllocationDecision:
    return AllocationDecision(
        action="rebalance",
        reasoning="Closing the gap to the target split.",
        facts_used=["f1", "f2"],
        target_allocations=[{"asset": a, "weight": w} for a, w in targets.items()],
        venue_intents=[
            SwapIntent(token_in=token_in, token_out=token_out, pct_of_holdings=0.3)
        ],
    )


# ── the failure that happened ─────────────────────────────────────────────


def test_the_observed_wrong_way_trade_is_rejected():
    """Sells WETH (30%, target 50%) to buy USDC (70%, target 50%).

    Both sides are wrong at once, so both are reported — the model gets told
    everything it needs in one correction.
    """
    bad = _decision("WETH", "USDC", {"USDC": 0.5, "WETH": 0.5})

    violations = check_rebalance_direction(bad, SEVENTY_THIRTY)

    assert violations, "the trade that actually happened must not validate"
    text = " ".join(str(v) for v in violations)
    assert "WETH" in text and "USDC" in text
    assert "further from your own target" in text


def test_the_right_way_round_is_accepted():
    """The same book, the same targets, the correct direction."""
    good = _decision("USDC", "WETH", {"USDC": 0.5, "WETH": 0.5})
    assert check_rebalance_direction(good, SEVENTY_THIRTY) == []


def test_the_message_names_the_actual_and_target_weights():
    """The correction has to be actionable — 'wrong direction' teaches nothing."""
    bad = _decision("WETH", "USDC", {"USDC": 0.5, "WETH": 0.5})
    message = " ".join(str(v) for v in check_rebalance_direction(bad, SEVENTY_THIRTY))

    assert "30.0%" in message and "50.0%" in message
    assert "swap the other way" in message


# ── it fires through the full validator, as layer 5 ───────────────────────


def test_validate_decision_rejects_a_wrong_way_trade():
    raw = _decision("WETH", "USDC", {"USDC": 0.5, "WETH": 0.5}).model_dump_json(
        exclude_none=True
    )

    with pytest.raises(ValueError, match="away from your own targets"):
        validate_decision(raw, fixtures.mandate(), fixtures.market_snapshot(), SEVENTY_THIRTY)


def test_the_same_decision_passes_without_a_vault():
    """Layer 5 needs reality to compare against, and says so by not running.

    Every live tick supplies a vault, so this only affects callers that cannot —
    and silently inventing weights would be worse than skipping.
    """
    raw = _decision("WETH", "USDC", {"USDC": 0.5, "WETH": 0.5}).model_dump_json(
        exclude_none=True
    )
    assert validate_decision(raw, fixtures.mandate(), fixtures.market_snapshot()) is not None


# ── it must not fire when it cannot know ──────────────────────────────────


def test_no_targets_means_no_opinion():
    """Without `target_allocations` there is no direction to be wrong about."""
    decision = AllocationDecision(
        action="rebalance",
        reasoning="Taking profit on WETH.",
        facts_used=["f1"],
        venue_intents=[SwapIntent(token_in="WETH", token_out="USDC", pct_of_holdings=0.2)],
    )
    assert check_rebalance_direction(decision, SEVENTY_THIRTY) == []


def test_an_unpriced_holding_is_skipped_rather_than_counted_as_zero():
    """`value_in_asset` is optional. Treating an unpriced holding as 0% would
    make every sale of it look like a violation."""
    vault = SEVENTY_THIRTY.model_copy(
        update={
            "holdings": [
                SEVENTY_THIRTY.holdings[0],
                SEVENTY_THIRTY.holdings[1].model_copy(update={"value_in_asset": None}),
            ]
        }
    )
    decision = _decision("WETH", "USDC", {"USDC": 0.5, "WETH": 0.5})

    problems = check_rebalance_direction(decision, vault)

    assert all("WETH" not in str(p) for p in problems), "cannot judge an unpriced asset"


def test_a_book_already_on_target_is_not_flagged_for_noise():
    """Sub-percentage drift must not block a legitimate small adjustment."""
    on_target = _vault(1_250_000000, 1_250_000000)  # exactly 50/50
    decision = _decision("USDC", "WETH", {"USDC": 0.5, "WETH": 0.5})
    assert check_rebalance_direction(decision, on_target) == []


def test_an_empty_vault_is_not_judged():
    empty = SEVENTY_THIRTY.model_copy(update={"total_assets": "0", "holdings": []})
    decision = _decision("WETH", "USDC", {"USDC": 0.5, "WETH": 0.5})
    assert check_rebalance_direction(decision, empty) == []


def test_an_asset_with_no_target_is_not_judged():
    """Selling something the targets do not mention is a decision, not an error."""
    decision = _decision("WETH", "USDC", {"USDC": 1.0})
    problems = check_rebalance_direction(decision, SEVENTY_THIRTY)
    assert all("WETH" not in str(p) for p in problems)


# ── layer 6: where the trade LANDS ────────────────────────────────────────
#
# The next tick got the direction right and then sized the swap at
# `pct_of_holdings: 1.0` — every USDC in the vault — taking a 79/21 book to
# 0/100 against a 50/50 target and breaching both mandate limits at once.
#
# Every earlier layer passed it, and each was right to. The mandate limits were
# being checked against what the model *said it wanted*, never against what its
# trade would actually *do*. Declared intent and realised effect are different
# things, and only the second one spends money.


def _mandate_5030():
    """A mandate with a 30% cash floor and a 60% position ceiling."""
    return fixtures.mandate().model_copy(
        update={
            "constraints": fixtures.mandate().constraints.model_copy(
                update={"min_cash_pct": 0.3, "max_position_pct": 0.6}
            )
        }
    )


#: The exact 79/21 book that produced tx 0x704f54a2.
SEVENTY_NINE = _vault(1_974_825442, 524_916313)


@pytest.mark.parametrize(
    ("pct", "expected"),
    [
        (1.0, "rejected"),  # the trade that happened: 0% cash, 100% WETH
        (0.6, "rejected"),  # still breaches the 60% position ceiling
        (0.37, "accepted"),  # lands near 50/50
    ],
)
def test_a_swap_is_judged_by_where_it_lands(pct, expected):
    from agent.mandate.constraints import check_projected_outcome

    decision = _decision("USDC", "WETH", {"USDC": 0.5, "WETH": 0.5}).model_copy(
        update={
            "venue_intents": [
                SwapIntent(token_in="USDC", token_out="WETH", pct_of_holdings=pct)
            ]
        }
    )
    problems = check_projected_outcome(decision, _mandate_5030(), SEVENTY_NINE)

    assert bool(problems) == (expected == "rejected"), [str(p) for p in problems]


def test_the_cash_floor_is_checked_against_the_result_not_the_declaration():
    """The declared target said 50% cash. The trade left 0%."""
    from agent.mandate.constraints import check_projected_outcome

    decision = _decision("USDC", "WETH", {"USDC": 0.5, "WETH": 0.5}).model_copy(
        update={
            "venue_intents": [
                SwapIntent(token_in="USDC", token_out="WETH", pct_of_holdings=1.0)
            ]
        }
    )
    problems = check_projected_outcome(decision, _mandate_5030(), SEVENTY_NINE)
    message = " ".join(str(p) for p in problems)

    assert "0.0% in USDC" in message and "30% cash floor" in message
    assert "100.0%" in message and "60% single-position ceiling" in message
    assert "Sell less" in message


def test_an_overshoot_within_the_limits_is_still_caught():
    """A trade can respect every limit and still sail past its own target."""
    from agent.mandate.constraints import check_projected_outcome

    # 79% USDC, target 50%. Selling 55% lands at ~35%, i.e. 15pp past.
    relaxed = fixtures.mandate().model_copy(
        update={
            "constraints": fixtures.mandate().constraints.model_copy(
                update={"min_cash_pct": 0.0, "max_position_pct": 1.0}
            )
        }
    )
    decision = _decision("USDC", "WETH", {"USDC": 0.5, "WETH": 0.5}).model_copy(
        update={
            "venue_intents": [
                SwapIntent(token_in="USDC", token_out="WETH", pct_of_holdings=0.9)
            ]
        }
    )
    message = " ".join(str(p) for p in check_projected_outcome(decision, relaxed, SEVENTY_NINE))
    assert "no closer than it started" in message


def test_a_mirror_image_overshoot_is_caught():
    """The failure a "did it get worse?" rule cannot see.

    Observed live: a book at 0% USDC against a 50% target swapped its **entire**
    WETH position, projecting to 100% USDC. Fifty points under became fifty
    points over — exactly as far away, so a rule that only rejected *worse*
    passed it. It is the same overshoot wearing a symmetric mask, so the rule
    demands improvement rather than the absence of harm.
    """
    from agent.mandate.constraints import check_projected_outcome

    all_weth = _vault(0, 2_499_327844)
    decision = _decision("WETH", "USDC", {"USDC": 0.5, "WETH": 0.5}).model_copy(
        update={
            "venue_intents": [
                SwapIntent(token_in="WETH", token_out="USDC", pct_of_holdings=1.0)
            ]
        }
    )

    message = " ".join(str(p) for p in check_projected_outcome(decision, _mandate_5030(), all_weth))

    assert "0.0% to 100.0%" in message
    assert "50.0% away before, 50.0% after" in message


def test_the_correctly_sized_half_is_accepted():
    """Selling half the WETH from an all-WETH book lands exactly on 50/50."""
    from agent.mandate.constraints import check_projected_outcome

    all_weth = _vault(0, 2_499_327844)
    decision = _decision("WETH", "USDC", {"USDC": 0.5, "WETH": 0.5}).model_copy(
        update={
            "venue_intents": [
                SwapIntent(token_in="WETH", token_out="USDC", pct_of_holdings=0.5)
            ]
        }
    )
    assert check_projected_outcome(decision, _mandate_5030(), all_weth) == []


def test_a_book_already_on_target_may_still_trade():
    """The golden fixture declares a 70/30 target on a 70/30 book and then
    trades. That is legal — it is expressing a view, not correcting a drift —
    and only the floor and ceiling bound where it may land. Layer 5 skips
    at-target assets for the same reason; the two must agree."""
    from agent.mandate.constraints import check_projected_outcome

    assert (
        check_projected_outcome(
            fixtures.allocation_decision(), fixtures.mandate(), fixtures.vault_state()
        )
        == []
    )


def test_a_swap_sized_in_token_units_is_not_projected():
    """`amount_in` is denominated in the input token and this module has no
    price. Guessing would be worse than declining to judge."""
    from agent.mandate.constraints import check_projected_outcome

    decision = _decision("USDC", "WETH", {"USDC": 0.5, "WETH": 0.5}).model_copy(
        update={
            "venue_intents": [
                SwapIntent(token_in="USDC", token_out="WETH", amount_in="1974825442")
            ]
        }
    )
    assert check_projected_outcome(decision, _mandate_5030(), SEVENTY_NINE) == []


def test_layer_six_fires_through_the_full_validator():
    raw = (
        _decision("USDC", "WETH", {"USDC": 0.5, "WETH": 0.5})
        .model_copy(
            update={
                "venue_intents": [
                    SwapIntent(token_in="USDC", token_out="WETH", pct_of_holdings=1.0)
                ]
            }
        )
        .model_dump_json(exclude_none=True)
    )

    with pytest.raises(ValueError, match="land the vault in a state the mandate forbids"):
        validate_decision(raw, _mandate_5030(), fixtures.market_snapshot(), SEVENTY_NINE)


def test_aqua_intents_are_not_direction_checked():
    """Shipping posts liquidity rather than changing composition, so there is no
    direction to be wrong about — and Aqua moves no tokens at all."""
    from curator_schema import AquaShipIntent

    decision = AllocationDecision(
        action="enter",
        reasoning="Posting the existing book as passive liquidity.",
        facts_used=["f1"],
        target_allocations=[{"asset": "USDC", "weight": 0.5}, {"asset": "WETH", "weight": 0.5}],
        venue_intents=[
            AquaShipIntent(tokens=["USDC", "WETH"], amounts=["750000000", "400000000000000000"])
        ],
    )
    assert check_rebalance_direction(decision, SEVENTY_THIRTY) == []
