"""What the model is actually shown.

Both confabulations observed against the real model were *rendering* failures,
not reasoning failures, and both were fixed in the prompt rather than in the
validator — because neither was catchable downstream:

1. **Invented a value for a real fact.** Shown `f6 | liquidity | uniswap-v3
   USDC/WETH | $12,400,000`, the model reported *"the highest headline APY of
   10.43%"*. Grounding validation checks that cited **ids** exist; it cannot
   check that quoted **numbers** are right. So the row has to be unmisreadable.

2. **Did arithmetic across units and got it wrong.** Shown `1,750.0000 USDC` and
   `0.4034 WETH`, it reported *"403.4 WETH, which is a 23.1% allocation (0.4034 /
   1750 * 100)"*, concluded the book was balanced, and declined to rebalance a
   70/30 book against a 50/50 target. Weighing a portfolio needs a price; the
   vault already computes one, so the weights are given rather than asked for.

These tests pin the properties that stopped each failure. They are cheap and they
protect a surface with no other safety net — nothing downstream can tell that a
number in free prose was invented.
"""

from __future__ import annotations

import pytest

from agent import fixtures
from agent.model.prompts.curator import (
    _render_facts,
    _render_gaps,
    _render_holdings,
    decision_messages,
)


@pytest.fixture
def snapshot():
    return fixtures.market_snapshot()


@pytest.fixture
def vault():
    return fixtures.vault_state()


# ── facts: only yields may look like yields ───────────────────────────────


def test_only_yield_facts_are_expressed_as_rates(snapshot):
    """`f6` is $12.4M of pool depth. Nothing about its row may read as a rate."""
    rendered = _render_facts(snapshot)
    liquidity_row = next(line for line in rendered.splitlines() if line.startswith("f6"))

    assert "%" not in liquidity_row, f"a non-yield row reads as a percentage: {liquidity_row}"
    assert "$12.4M" in liquidity_row
    assert "not a rate" in liquidity_row


def test_yield_rows_state_their_period(snapshot):
    """'4.32%' alone is ambiguous; '4.32% per year' is not."""
    for fact_id in ("f1", "f2"):
        rows = _render_facts(snapshot).splitlines()
        row = next(line for line in rows if line.startswith(fact_id))
        assert "per year" in row


def test_the_table_names_which_ids_are_yields(snapshot):
    """The explicit backstop against calling a TVL figure an APY."""
    rendered = _render_facts(snapshot)
    assert "Yields available this tick: f1, f2" in rendered
    assert "Do not describe one as an APY" in rendered


def test_every_fact_says_what_it_measures_in_words(snapshot):
    """A bare enum (`liquidity`) is easier to misread than 'pool depth'."""
    rendered = _render_facts(snapshot)
    for phrase in ("lending yield", "pool depth", "total value locked", "spot price"):
        assert phrase in rendered


def test_each_fact_id_appears_exactly_once(snapshot):
    """Ids are what the model must cite; a duplicate invites an ambiguous one."""
    rendered = _render_facts(snapshot)
    for fact in snapshot.facts:
        starts = [line for line in rendered.splitlines() if line.startswith(f"{fact.id} ")]
        assert len(starts) == 1, f"{fact.id} appears {len(starts)} times"


def test_an_empty_snapshot_says_so_rather_than_rendering_an_empty_table(snapshot):
    empty = snapshot.model_copy(update={"facts": []})
    assert "No market data" in _render_facts(empty)


# ── holdings: the weights are given, not asked for ────────────────────────


def test_holdings_are_rendered_with_their_computed_weight(vault):
    """The fix for the arithmetic failure: percentages, already worked out."""
    rendered = _render_holdings(vault)

    assert "70.0% of the vault" in rendered  # 35,000 USDC of 50,000
    assert "30.0% of the vault" in rendered  # 15,000 of value in WETH
    assert "do not recalculate them" in rendered


def test_holdings_show_value_in_the_base_asset_not_just_token_amounts(vault):
    """0.4034 WETH means nothing next to 1,750 USDC without a price."""
    rendered = _render_holdings(vault)
    assert "worth" in rendered
    assert "Total value" in rendered


def test_a_holding_with_no_valuation_says_so_rather_than_implying_zero(vault):
    """`value_in_asset` is optional. Rendering an unpriced holding as 0% would
    tell the model the vault holds nothing of it."""
    unpriced = vault.holdings[1].model_copy(update={"value_in_asset": None})
    holdings = [vault.holdings[0], unpriced]
    rendered = _render_holdings(vault.model_copy(update={"holdings": holdings}))

    unpriced_line = next(line for line in rendered.splitlines() if unpriced.symbol in line)
    assert "value unknown this tick" in unpriced_line
    # Substring-safe: "70.0% of the vault" contains "0.0% of the vault".
    assert "% of the vault" not in unpriced_line


def test_venue_encumbrance_is_shown(vault):
    """`committed_to_venue` flags encumbrance, not location — the vault still
    custodies it, and the model needs to know it is not freely tradable."""
    assert "committed to aqua" in _render_holdings(vault)


def test_no_holdings_renders_nothing_rather_than_an_empty_header(vault):
    assert _render_holdings(vault.model_copy(update={"holdings": []})) == ""
    assert _render_holdings(None) == ""


# ── gaps: the model must know what it could not see ───────────────────────


def test_source_failures_are_shown_to_the_model(snapshot):
    """A degraded snapshot that looks complete invites a confident wrong call."""
    rendered = _render_gaps(snapshot)
    assert "could NOT read" in rendered
    assert "token_api" in rendered


def test_no_errors_renders_nothing(snapshot):
    assert _render_gaps(snapshot.model_copy(update={"errors": []})) == ""


# ── the assembled prompt ──────────────────────────────────────────────────


def test_the_prompt_carries_every_limit_the_validator_enforces(snapshot, vault):
    """A retry must read as a correction, not a contradiction — so every rule
    the validator can reject on has to be stated up front."""
    mandate = fixtures.mandate()
    text = "\n".join(m["content"] for m in decision_messages(mandate, snapshot, vault))

    assert f"{mandate.constraints.max_slippage_bps} bps" in text
    assert f"{mandate.constraints.max_position_pct:.0%}" in text
    assert f"{mandate.constraints.min_cash_pct:.0%}" in text
    assert str(mandate.constraints.max_actions_per_tick) in text
    for asset in mandate.constraints.allowed_assets:
        assert asset in text


def test_hold_is_offered_as_a_real_option(snapshot, vault):
    """A model asked to allocate will allocate; left alone, small models churn
    the vault to death by fees."""
    text = "\n".join(m["content"] for m in decision_messages(fixtures.mandate(), snapshot, vault))
    assert "hold" in text.lower()
    assert text.lower().count("hold") >= 3


def test_the_prompt_is_ascii_so_no_console_mangles_it(snapshot, vault):
    """Lane C's finding: Windows consoles are cp1252 and turn a UTF-8 dash into
    a mojibake box. The prompt reaches a terminal via `agent.bench`."""
    text = "\n".join(m["content"] for m in decision_messages(fixtures.mandate(), snapshot, vault))
    offenders = sorted({ch for ch in text if ord(ch) > 127})
    assert not offenders, f"non-ASCII in the rendered prompt: {offenders}"


# ── the genesis prompt gets the same guarantees ───────────────────────────
#
# The decision prompt has been ASCII-guarded since Wave 1, and that guard has
# caught three regressions. The genesis prompt had none — and it now embeds
# preset prose written in Lane F's files, which is exactly the kind of text that
# arrives with a smart quote in it.


def test_the_genesis_prompt_is_ascii():
    from agent.model.prompts.genesis import genesis_messages

    text = "\n".join(
        m["content"] for m in genesis_messages([], ["messari", "aave"], ["uniswap", "aqua"])
    )
    offenders = sorted({ch for ch in text if ord(ch) > 127})
    assert not offenders, f"non-ASCII in the genesis prompt: {offenders}"


def test_genesis_offers_every_preset_with_its_tradeoff():
    """A genesis flow that lists benefits and omits costs is a sales page, and
    this one produces a mandate no human can change afterwards."""
    from agent.mandate.presets import load_presets
    from agent.model.prompts.genesis import genesis_messages

    text = "\n".join(m["content"] for m in genesis_messages([], ["messari"], ["aqua"]))

    for preset in load_presets():
        assert preset.key in text
        assert preset.tradeoff[:40] in text, f"{preset.key} offered without its tradeoff"


def test_genesis_does_not_recommend_one_preset_over_another():
    """Which tradeoff is acceptable is the user's judgement. A default framed as
    "the safe choice" is the model making a risk decision on their behalf."""
    from agent.model.prompts.genesis import genesis_messages

    text = "\n".join(m["content"] for m in genesis_messages([], ["messari"], ["aqua"]))
    assert "do not present one as the safe or obvious choice" in text
