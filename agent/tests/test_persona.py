"""B2 · personas skew preference inside the permitted set and never widen it.

Wave 2 §3.2 states the invariant and asks this lane to pin it: *"a persona skews
preference inside the permitted set and can never widen it. An aggressive persona
may prefer the riskier of two permitted assets; it may not reach an asset the
mandate did not allow, raise a cap, or shrink the cash floor. Persona is taste;
constraints are law. If those two ever merge, 'aggressive' becomes an exploit."*

The structural reason it holds is worth stating, because it is stronger than any
individual test here: **`check_decision` never receives the persona.** The
validator takes a decision and a mandate, and `Mandate.persona` is not consulted
by any check. There is no code path by which a persona could loosen a bound, so
these tests are guarding against a future edit that introduces one rather than
against a hole that exists today.

What the persona *does* change is the system prompt — the voice, the leanings and
the sizing appetite. That matters for a different reason: a model that believes
it has permission wastes the tick producing decisions the harness rejects, and
its `reasoning` tells a depositor it was allowed to do something it was not. So
the block says "this is who you are, not what you may do" in as many words, and
that sentence is tested too.
"""

from __future__ import annotations

import json
import pathlib

import pytest
from curator_schema import (
    AllocationDecision,
    Mandate,
    Persona,
    SwapIntent,
    TargetAllocation,
)

from agent import fixtures
from agent.mandate.constraints import apply_band, check_decision
from agent.model.prompts.curator import _render_persona, decision_messages

PRESETS = pathlib.Path(__file__).resolve().parents[2] / "packages" / "schema" / "presets"

#: The most permissive persona expressible: high conviction, every bias pointing
#: at more risk. If constraints are law, this changes nothing about what passes.
AGGRESSIVE = Persona(
    name="Scam Bankman-Fried",
    voice="Certain, fast, allergic to hedging.",
    biases=[
        "always prefers the highest headline yield",
        "treats cash as a failure of imagination",
        "would rather be concentrated and right",
    ],
    conviction="high",
)


@pytest.fixture
def mandate() -> Mandate:
    """Golden mandate: USDC/WETH only, 60% cap, 20% floor."""
    return fixtures.mandate()


@pytest.fixture
def aggressive(mandate: Mandate) -> Mandate:
    return mandate.model_copy(update={"persona": AGGRESSIVE})


def _decide(**overrides) -> AllocationDecision:
    base = {
        "action": "rebalance",
        "reasoning": "Leaning in.",
        "facts_used": ["f1"],
        "target_allocations": [
            TargetAllocation(asset="USDC", weight=0.4),
            TargetAllocation(asset="WETH", weight=0.6),
        ],
        "venue_intents": [
            SwapIntent(token_in="USDC", token_out="WETH", pct_of_holdings=0.2)
        ],
    }
    return AllocationDecision(**{**base, **overrides})


def _hard(decision: AllocationDecision, mandate: Mandate):
    """Violations that survive the tolerance band."""
    return apply_band(check_decision(decision, mandate), mandate)[0]


# ── the invariant ─────────────────────────────────────────────────────────


def test_a_persona_cannot_reach_an_asset_the_mandate_omits(mandate, aggressive):
    """The clearest case: cbETH is not in `allowed_assets`, and no amount of
    appetite puts it there."""
    reaching = _decide(
        target_allocations=[
            TargetAllocation(asset="USDC", weight=0.4),
            TargetAllocation(asset="cbETH", weight=0.6),
        ],
        venue_intents=[
            SwapIntent(token_in="USDC", token_out="cbETH", pct_of_holdings=0.5)
        ],
    )

    without = _hard(reaching, mandate)
    with_persona = _hard(reaching, aggressive)

    assert without, "sanity: this should breach even without a persona"
    assert len(with_persona) == len(without), "the persona changed what is permitted"
    assert any("cbETH" in str(v) for v in with_persona)


def test_a_persona_cannot_raise_the_position_cap(mandate, aggressive):
    """80% against a 60% cap is 33% over — far outside the band, with or
    without a persona arguing for it."""
    oversized = _decide(
        target_allocations=[
            TargetAllocation(asset="USDC", weight=0.2),
            TargetAllocation(asset="WETH", weight=0.8),
        ]
    )

    assert _hard(oversized, aggressive), "an aggressive persona raised the cap"
    assert len(_hard(oversized, aggressive)) == len(_hard(oversized, mandate))


def test_a_persona_cannot_shrink_the_cash_floor(mandate, aggressive):
    """"Cash is a failure of imagination" is a preference, not a permission."""
    starved = _decide(
        target_allocations=[
            TargetAllocation(asset="USDC", weight=0.02),
            TargetAllocation(asset="WETH", weight=0.98),
        ]
    )
    assert _hard(starved, aggressive)


def test_a_persona_cannot_loosen_the_slippage_ceiling(mandate, aggressive):
    """Slippage is outside the tolerance band by design, and conviction is not a
    second way in."""
    from agent.mandate.constraints import check_plan

    plan = fixtures.execution_plan().model_copy(
        update={"expected_slippage_bps": 400, "quote_expires_at": None}
    )
    assert check_plan(plan, aggressive)
    assert len(check_plan(plan, aggressive)) == len(check_plan(plan, mandate))


@pytest.mark.parametrize("conviction", ["low", "medium", "high"])
def test_conviction_changes_nothing_the_validator_sees(mandate, conviction):
    """Conviction steers sizing *within* the cap. It moves no bound, so the same
    decision gets the same verdict at every setting."""
    persona = AGGRESSIVE.model_copy(update={"conviction": conviction})
    with_persona = mandate.model_copy(update={"persona": persona})
    oversized = _decide(
        target_allocations=[
            TargetAllocation(asset="USDC", weight=0.2),
            TargetAllocation(asset="WETH", weight=0.8),
        ]
    )

    assert [str(v) for v in _hard(oversized, with_persona)] == [
        str(v) for v in _hard(oversized, mandate)
    ]


def test_the_validator_never_receives_the_persona(mandate, aggressive):
    """The structural guarantee, stated as a test.

    Every decision that passes without a persona passes with one, and every
    decision that fails without one fails with it. If a future edit ever wires
    persona into a check, this is what fails.
    """
    legal = _decide()
    assert _hard(legal, mandate) == [] and _hard(legal, aggressive) == []


# ── what the persona *does* change ────────────────────────────────────────


def test_the_persona_reaches_the_system_prompt(aggressive):
    messages = decision_messages(aggressive, fixtures.market_snapshot(), fixtures.vault_state())
    system = messages[0]["content"]

    assert "Scam Bankman-Fried" in system
    assert "allergic to hedging" in system
    assert "always prefers the highest headline yield" in system


def test_the_prompt_says_persona_is_not_permission(aggressive):
    """A model that believes it has permission burns the tick on decisions the
    harness rejects, and its reasoning misleads whoever reads the feed."""
    system = decision_messages(
        aggressive, fixtures.market_snapshot(), fixtures.vault_state()
    )[0]["content"]

    assert "not what you may do" in system
    assert "does not widen a single limit" in system


def test_no_persona_adds_nothing(mandate):
    """A mandate without one must not gain an empty section."""
    assert _render_persona(mandate) == ""
    system = decision_messages(mandate, fixtures.market_snapshot(), fixtures.vault_state())[0][
        "content"
    ]
    assert "YOU ARE CURATING AS" not in system


def test_two_personas_produce_different_prompts_from_one_snapshot(mandate):
    """The Wave 2 definition of done asks for two vaults with visibly different
    personas deciding differently *from the same snapshot*. Different decisions
    need a real model; that the inputs genuinely differ is testable here."""
    cautious = mandate.model_copy(
        update={
            "persona": Persona(
                name="The Steward",
                voice="Measured and specific about what it does not know.",
                biases=["prefers the deepest market over the highest yield"],
                conviction="low",
            )
        }
    )
    bold = mandate.model_copy(update={"persona": AGGRESSIVE})
    snapshot, vault = fixtures.market_snapshot(), fixtures.vault_state()

    a = decision_messages(cautious, snapshot, vault)[0]["content"]
    b = decision_messages(bold, snapshot, vault)[0]["content"]

    assert a != b
    assert "The Steward" in a and "Scam Bankman-Fried" in b
    assert "Conviction: low" in a and "Conviction: high" in b


def test_the_prompt_stays_ascii_with_a_persona(aggressive):
    """Lane C's finding: a Windows console turns a UTF-8 dash into a mojibake
    box, and personas are free text that arrives from a preset file."""
    text = "\n".join(
        m["content"]
        for m in decision_messages(aggressive, fixtures.market_snapshot(), fixtures.vault_state())
    )
    assert not [c for c in text if ord(c) > 127]


# ── the shipped presets ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "preset", sorted(p.stem for p in PRESETS.glob("*.json") if p.stem != "index")
)
def test_every_preset_persona_renders_and_stays_ascii(preset):
    """Preset personas are prompt input written in another lane's file. If one
    arrives with a smart quote, the whole prompt stops being ASCII."""
    mandate = Mandate.model_validate(
        json.loads((PRESETS / f"{preset}.json").read_text(encoding="utf-8"))
    )
    rendered = _render_persona(mandate)

    if mandate.persona is None:
        assert rendered == ""
        return

    assert mandate.persona.name in rendered
    assert not [c for c in rendered if ord(c) > 127], f"{preset} persona is not ASCII"


@pytest.mark.parametrize(
    "preset", sorted(p.stem for p in PRESETS.glob("*.json") if p.stem != "index")
)
def test_no_preset_persona_can_widen_its_own_mandate(preset):
    """Each preset ships as a pair, so the pairing is what gets tested: a
    decision that breaches the preset's own limits stays rejected under the
    preset's own persona."""
    mandate = Mandate.model_validate(
        json.loads((PRESETS / f"{preset}.json").read_text(encoding="utf-8"))
    )
    stripped = mandate.model_copy(update={"persona": None})

    breach = AllocationDecision(
        action="rebalance",
        reasoning="Going all in.",
        facts_used=["f1"],
        target_allocations=[
            TargetAllocation(asset=mandate.constraints.allowed_assets[-1], weight=1.0)
        ],
        venue_intents=[
            SwapIntent(
                token_in=mandate.base_asset,
                token_out=mandate.constraints.allowed_assets[-1],
                pct_of_holdings=1.0,
            )
        ],
    )

    assert [str(v) for v in _hard(breach, mandate)] == [str(v) for v in _hard(breach, stripped)]
