"""P5 — the agent grading its own homework, without letting it cheat.

Every tick before this was amnesiac: the model saw holdings and market data and
nothing about whether its last five decisions worked. It could not learn that
its rotations kept costing more in slippage than the spread they chased.

The hard part is not joining the two records. It is refusing to hand the model a
tidy verdict it can optimise against. A share price that rose after a trade is
mostly the market; a share price that fell *during* the trade is the trade. One
is attributable and one is not, and conflating them trains the model to trade
before favourable drift and claim credit.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from curator_schema import (
    AgentAction,
    AllocationDecision,
    ExecutionPlan,
    ExecutionStep,
    PerformancePoint,
    SwapIntent,
)

from agent.loop.reflection import build_reflection

VAULT = "0x0E2c0e50E67B96C9C401C94e111a3DBD00DEB5d1"


def _now() -> datetime:
    return datetime.now(UTC)


def _point(hours_ago: float, price: int) -> PerformancePoint:
    return PerformancePoint(
        timestamp=_now() - timedelta(hours=hours_ago),
        block_number=49_000_000 + int(hours_ago * 100),
        share_price=str(price),
        total_assets=str(price * 10_000),
        total_supply="10000000000000000000000",
    )


def _executed(hours_ago: float, effect: str = "swap 500 USDC for ~0.27 WETH") -> AgentAction:
    return AgentAction(
        id=f"act_{int(hours_ago * 100):06d}",
        vault=VAULT,
        timestamp=_now() - timedelta(hours=hours_ago),
        status="executed",
        decision=AllocationDecision(
            action="rebalance",
            reasoning="the spread favoured WETH",
            venue_intents=[SwapIntent(token_in="USDC", token_out="WETH", pct_of_holdings=0.5)],
        ),
        plan=ExecutionPlan(
            venue="uniswap",
            steps=[ExecutionStep(target="0x" + "11" * 20, calldata="0x", why="swap")],
            expected_effect=effect,
        ),
    )


def _rejected(hours_ago: float) -> AgentAction:
    return AgentAction(
        id=f"rej_{int(hours_ago * 100):06d}",
        vault=VAULT,
        timestamp=_now() - timedelta(hours=hours_ago),
        status="rejected",
        error="below the cash floor",
    )


# ── the discipline ────────────────────────────────────────────────────────


def test_a_recent_trade_is_reported_as_too_early_to_tell():
    """The guard against reward hacking, and the point of the whole module.

    A trade two hours ago whose book is up 0.5% has told us nothing. Rendering
    that as a success teaches the model that trading before favourable drift is
    skill.
    """
    points = [_point(2.1, 1_000_000), _point(2.0, 999_500), _point(0.0, 1_005_000)]
    reflection = build_reflection([_executed(2.05)], points)

    assert len(reflection.outcomes) == 1
    assert "too early" in reflection.outcomes[0].verdict


def test_cost_and_drift_are_reported_separately():
    """Cost is the agent's. Drift is the market's. Never one number.

    The share-price drop across the executing tick is slippage, fees and gas in
    the units a depositor feels — unambiguously attributable. What the book did
    afterwards is not.
    """
    points = [_point(30.0, 1_000_000), _point(29.9, 999_000), _point(0.0, 1_020_000)]
    outcome = build_reflection([_executed(29.95)], points).outcomes[0]

    assert outcome.realised_cost_pct == pytest.approx(-0.001, abs=1e-6), "10 bps of cost"
    assert outcome.drift_since_pct == pytest.approx(0.021021, abs=1e-4), "+2.1% of market"

    rendered = outcome.render()
    assert "cost" in rendered and "since" in rendered


def test_the_prompt_block_warns_against_reading_drift_as_skill():
    points = [_point(30.0, 1_000_000), _point(29.9, 999_000), _point(0.0, 1_020_000)]
    text = build_reflection([_executed(29.95)], points).render()

    assert "mostly the market, not your skill" in text
    assert "COST figure is yours" in text


def test_a_flat_book_gets_no_signal_either_way():
    points = [_point(30.0, 1_000_000), _point(29.9, 999_900), _point(0.0, 999_950)]
    outcome = build_reflection([_executed(29.95)], points).outcomes[0]
    assert "no signal" in outcome.verdict


def test_a_book_that_fell_by_more_than_the_trade_cost_is_named_as_such():
    """The one verdict that is allowed to be negative, because it is the one
    the agent can act on: if the trades keep costing more than the edge, stop."""
    points = [_point(30.0, 1_000_000), _point(29.9, 999_000), _point(0.0, 980_000)]
    outcome = build_reflection([_executed(29.95)], points).outcomes[0]
    assert "fallen since" in outcome.verdict


# ── shape ─────────────────────────────────────────────────────────────────


def test_nothing_to_say_renders_as_nothing():
    """An empty heading reads as a system that lost the data."""
    assert build_reflection([], []).render() == ""


def test_holds_and_rejections_are_counted_but_not_given_outcomes():
    """A rejected decision never reached the chain, so it has no outcome — but
    the count is worth showing: it is the evidence validation is load-bearing."""
    actions = [_executed(30.0), _rejected(20.0), _rejected(10.0)]
    points = [_point(30.1, 1_000_000), _point(29.9, 999_000), _point(0.0, 999_500)]
    reflection = build_reflection(actions, points)

    assert len(reflection.outcomes) == 1
    assert reflection.rejections == 2
    assert reflection.executions == 1
    assert "2 decision(s) rejected" in reflection.render()


def test_the_venues_description_is_preferred_over_the_models_own_prose():
    """Feeding a model its own reasoning back invites it to agree with itself.

    The adapter's `expected_effect` states what the calldata does; the reasoning
    states what the model believed. Only the first is evidence.
    """
    points = [_point(30.0, 1_000_000), _point(29.9, 999_000), _point(0.0, 999_000)]
    action = _executed(29.95, effect="swap 500 USDC for ~0.27 WETH")
    outcome = build_reflection([action], points).outcomes[0]

    assert "swap 500 USDC" in outcome.intent
    assert "the spread favoured WETH" not in outcome.intent


def test_only_the_most_recent_executions_are_shown():
    actions = [_executed(float(h)) for h in range(1, 12)]
    points = [_point(12.0, 1_000_000), _point(0.0, 1_001_000)]
    assert len(build_reflection(actions, points, limit=5).outcomes) == 5


def test_a_missing_performance_series_still_produces_a_usable_block():
    """A vault with decisions and no recorded prices is a real state — the
    reflection should say what it knows and not claim outcomes it cannot see."""
    reflection = build_reflection([_executed(5.0), _rejected(4.0)], [])
    text = reflection.render()

    assert reflection.outcomes[0].realised_cost_pct is None
    assert "no follow-up data yet" in text
    assert "1 time(s)" in text


def test_venue_text_is_coerced_to_ascii():
    """The prompt must stay ASCII, and venue text arrives at runtime.

    `test_prompt_rendering.py` already guards this, but it renders fixtures —
    text coming from a live `expected_effect` slips past it. Real output
    contained both an em dash and a truncated address ellipsis:
    "ship a 0.3% position into Aqua (0xd1f99f37…) — tokens stay in the vault".
    """
    action = _executed(30.0, effect="ship into Aqua (0xd1f99f37…) — tokens stay in the vault")
    points = [_point(30.1, 1_000_000), _point(29.9, 1_000_000), _point(0.0, 1_000_000)]
    intent = build_reflection([action], points).outcomes[0].intent

    assert all(ord(ch) < 128 for ch in intent), f"non-ASCII survived: {intent!r}"
    assert "0xd1f99f37..." in intent, "the ellipsis should degrade, not vanish"
    assert "- tokens stay in the vault" in intent


def test_the_whole_rendered_block_is_ascii_not_just_the_venue_text():
    """Coercion at the exit, not at each source.

    The first version asciified only venue-supplied text, and the module's own
    verdict strings ("too early to tell — under 6h") then leaked em dashes into
    the prompt: the same bug one layer up. Asserting on the whole block makes
    the guarantee structural rather than something every future line has to
    remember.
    """
    actions = [_executed(2.0, effect="ship into Aqua (0xabc…) — held"), _rejected(1.0)]
    points = [_point(2.1, 1_000_000), _point(1.9, 999_000), _point(0.0, 999_500)]
    text = build_reflection(actions, points).render()

    offenders = sorted({ch for ch in text if ord(ch) > 127})
    assert not offenders, f"non-ASCII in the reflection block: {offenders}"
