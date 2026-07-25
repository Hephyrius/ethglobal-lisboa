"""Idle capital: the derived fact, and the drag it carries.

Wave 2's headline feedback is that the agent swaps and then sits on cash. The
response is deliberately **not** a validation layer — `hold` stays a first-class
answer, because a harness that rejects it churns the vault, which is the failure
the six layers exist to prevent. Pressure goes in the prompt and the scoreboard.

So what has to be true is narrower and testable: the number must be **right**,
**citable**, and **honest about what it does not know**. These tests cover those
three, and the boundary that matters most — capital behind an Aqua position is
*encumbered, not idle*, and counting it as idle would tell the agent to deploy
money it has already deployed.
"""

from __future__ import annotations

import pytest
from curator_schema import Fact, FactSubject, Holding, MarketSnapshot, VaultState

from agent import fixtures
from agent.clock import utcnow
from agent.loop.idle import (
    HARNESS_SOURCE,
    IDLE_FACT_ID,
    best_lending_rate,
    idle_capital_fact,
    idle_drag_for,
    idle_fraction,
    is_material,
    with_idle_fact,
)

USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
WETH = "0x4200000000000000000000000000000000000006"


def _vault(*holdings: Holding, total: int) -> VaultState:
    return VaultState(
        address="0x0E2c0e50E67B96C9C401C94e111a3DBD00DEB5d1",
        asset=USDC,
        asset_decimals=6,
        total_assets=str(total),
        total_supply=str(total * 10**12),
        holdings=list(holdings),
    )


def _usdc(value: int, *, committed: str | None = None) -> Holding:
    return Holding(
        token=USDC,
        symbol="USDC",
        balance=str(value),
        decimals=6,
        value_in_asset=str(value),
        committed_to_venue=committed,
    )


def _weth(value: int, *, committed: str | None = None) -> Holding:
    return Holding(
        token=WETH,
        symbol="WETH",
        balance="400000000000000000",
        decimals=18,
        value_in_asset=str(value),
        committed_to_venue=committed,
    )


@pytest.fixture
def mandate():
    """Golden mandate: USDC base, 20% cash floor."""
    return fixtures.mandate()


# ── the number itself ─────────────────────────────────────────────────────


def test_idle_is_cash_above_the_floor(mandate):
    """700 of 1000 in USDC against a 20% floor leaves 50% idle."""
    vault = _vault(_usdc(700), _weth(300), total=1000)
    assert idle_fraction(mandate, vault) == pytest.approx(0.5)


def test_a_book_at_the_floor_has_nothing_idle(mandate):
    vault = _vault(_usdc(200), _weth(800), total=1000)
    assert idle_fraction(mandate, vault) == pytest.approx(0.0)


def test_below_the_floor_is_zero_not_negative(mandate):
    """Under-cash is a different problem, and a negative idle share would render
    as "-10% of the vault is sitting idle"."""
    vault = _vault(_usdc(50), _weth(950), total=1000)
    assert idle_fraction(mandate, vault) == 0.0


def test_capital_behind_a_venue_is_encumbered_not_idle(mandate):
    """**The distinction that matters.** Aqua holds no tokens — they stay in the
    vault — so a naive balance check counts a live market-making position as
    idle and tells the agent to deploy money it has already deployed."""
    free = _vault(_usdc(700), _weth(300), total=1000)
    shipped = _vault(_usdc(700, committed="aqua"), _weth(300), total=1000)

    assert idle_fraction(mandate, free) == pytest.approx(0.5)
    assert idle_fraction(mandate, shipped) == 0.0


def test_only_the_base_asset_counts_as_idle(mandate):
    """WETH is a position, not cash. It may be a bad position, but it is not
    capital sitting still."""
    vault = _vault(_usdc(200), _weth(800), total=1000)
    assert idle_fraction(mandate, vault) == pytest.approx(0.0)


# ── honest about what it cannot know ──────────────────────────────────────


@pytest.mark.parametrize(
    ("label", "vault"),
    [
        ("no vault", None),
        ("empty vault", _vault(total=0)),
        ("nothing valued", _vault(_usdc(700).model_copy(update={"value_in_asset": None}),
                                  total=1000)),
    ],
)
def test_unknowable_returns_none_rather_than_zero(mandate, label, vault):
    """`0.0` would tell the model the vault is fully deployed. The truth is that
    we do not know, and those are different statements."""
    assert idle_fraction(mandate, vault) is None


def test_a_tiny_surplus_is_not_material(mandate):
    assert is_material(0.005) is False
    assert is_material(0.5) is True
    assert is_material(None) is False


# ── the fact ──────────────────────────────────────────────────────────────


def test_the_fact_is_citable_and_attributed_to_the_harness(mandate):
    """`source` must not borrow a provider's name. A derived number attributed
    to The Graph would be a provenance lie in the feed."""
    fact = idle_capital_fact(mandate, _vault(_usdc(700), _weth(300), total=1000))

    assert fact is not None
    assert fact.id == IDLE_FACT_ID
    assert fact.source == HARNESS_SOURCE
    assert fact.value == pytest.approx(0.5)
    assert fact.unit == "ratio"


def test_zero_idle_still_emits_a_fact(mandate):
    """"Nothing is idle" is worth citing when the agent holds. Without it the
    model has no concrete ground for the decision."""
    fact = idle_capital_fact(mandate, _vault(_usdc(200), _weth(800), total=1000))
    assert fact is not None and fact.value == 0.0


def test_no_fact_when_it_cannot_be_derived(mandate):
    assert idle_capital_fact(mandate, None) is None


def test_the_snapshot_gains_exactly_one_fact(mandate):
    """Appended, never replacing — a failing source must still degrade the way
    Lane C designed it to."""
    original = fixtures.market_snapshot()
    merged = with_idle_fact(original, mandate, _vault(_usdc(700), _weth(300), total=1000))

    assert len(merged.facts) == len(original.facts) + 1
    assert merged.errors == original.errors
    assert [f.id for f in merged.facts[:-1]] == [f.id for f in original.facts]


def test_the_snapshot_is_unchanged_when_nothing_can_be_derived(mandate):
    original = fixtures.market_snapshot()
    assert with_idle_fact(original, mandate, None) is original


# ── the rate the drag is priced against ───────────────────────────────────


def test_the_best_rate_ignores_assets_the_mandate_forbids(mandate):
    """A missed opportunity the mandate prohibited is not a missed opportunity.
    Quoting it would teach the agent to regret obeying its own constraints."""
    snapshot = MarketSnapshot(
        taken_at=utcnow(),
        facts=[
            Fact(id="a", kind="yield", subject=FactSubject(protocol="aave-v3", market="USDC"),
                 value=0.04, unit="apy_fraction", source="messari", observed_at=utcnow()),
            Fact(id="b", kind="yield", subject=FactSubject(protocol="silo", market="cbETH"),
                 value=0.19, unit="apy_fraction", source="messari", observed_at=utcnow()),
        ],
    )
    best = best_lending_rate(snapshot, mandate)

    assert best is not None
    assert best[0] == pytest.approx(0.04), "picked a yield on a forbidden asset"


def test_no_yields_means_no_rate(mandate):
    assert best_lending_rate(MarketSnapshot(taken_at=utcnow(), facts=[]), mandate) is None


# ── the drag ──────────────────────────────────────────────────────────────


def test_drag_leads_with_the_annualised_rate(mandate):
    """Over a few hours the accumulated figure is basis points. Leading with it
    would teach precisely the wrong lesson — that idling is free."""
    drag = idle_drag_for(mandate, _vault(_usdc(700), _weth(300), total=1000),
                         fixtures.market_snapshot(), 6.5)

    assert drag is not None
    assert drag.annualised_pct == pytest.approx(0.5 * 0.0587)
    rendered = drag.render()
    assert rendered.index("a year") < rendered.index("already cost")


def test_drag_accumulates_with_time(mandate):
    vault = _vault(_usdc(700), _weth(300), total=1000)
    snapshot = fixtures.market_snapshot()

    short = idle_drag_for(mandate, vault, snapshot, 1.0)
    long = idle_drag_for(mandate, vault, snapshot, 100.0)

    assert short.forgone_pct < long.forgone_pct
    assert short.annualised_pct == long.annualised_pct, "the rate does not depend on the window"


def test_no_window_means_no_accumulated_figure(mandate):
    """A vault that has never executed has no window to price the drag against,
    and inventing one would invent the cost."""
    drag = idle_drag_for(mandate, _vault(_usdc(700), _weth(300), total=1000),
                         fixtures.market_snapshot(), None)

    assert drag is not None
    assert drag.forgone_pct is None
    assert "already cost" not in drag.render()


def test_no_drag_when_nothing_is_idle(mandate):
    assert idle_drag_for(mandate, _vault(_usdc(200), _weth(800), total=1000),
                         fixtures.market_snapshot(), 6.0) is None


def test_no_drag_when_no_rate_is_available(mandate):
    """"We could not price the drag" and "the drag is nothing" are different
    statements, and only one of them is true here."""
    empty = MarketSnapshot(taken_at=utcnow(), facts=[])
    assert idle_drag_for(mandate, _vault(_usdc(700), _weth(300), total=1000), empty, 6.0) is None


def test_the_drag_reaches_the_reflection_block(mandate):
    from agent.loop.reflection import build_reflection

    drag = idle_drag_for(mandate, _vault(_usdc(700), _weth(300), total=1000),
                         fixtures.market_snapshot(), 6.5)
    rendered = build_reflection([], [], idle_drag=drag).render()

    assert "THE COST OF SITTING STILL" in rendered
    assert "morpho-blue USDC" in rendered


def test_the_reflection_stays_empty_with_nothing_to_say():
    from agent.loop.reflection import build_reflection

    assert build_reflection([], []).render() == ""
