"""Prediction-market odds: the inversion, and the credibility filter.

Fixtures are live values from Polymarket on 2026-07-25:

    Will the Fed decrease rates by 50+ bps?   Yes 0.0015   No 0.9985
    Will there be no change in Fed rates?     Yes 0.7525   No 0.2475
    Will the Fed increase rates by 25 bps?    Yes 0.2405   No 0.7595

The first is why the first test exists. Reporting the *leading* outcome looks
reasonable and is catastrophic: it would publish 99.85% against a subject
reading `will-the-fed-decrease-...`, telling the model the near-certain
opposite of what the market believes. Structurally the same bug as the Token
API's direction-flipped price field.
"""

from __future__ import annotations

import json

import httpx

from curator_data.config import Settings
from curator_data.sources.prediction import (
    FACT_KIND,
    MIN_VOLUME_24H_USD,
    TOP_N,
    PredictionSource,
)

SETTINGS = Settings(chain="base")


def _market(question: str, yes: float, volume: float = 500_000.0,
            outcomes=("Yes", "No"), end: str = "2026-07-29T12:00:00Z") -> dict:
    prices = [yes, round(1.0 - yes, 4)] if len(outcomes) == 2 else [yes]
    return {
        "question": question,
        "outcomes": json.dumps(list(outcomes)),
        "outcomePrices": json.dumps([str(p) for p in prices]),
        "volume24hr": volume,
        "endDate": end,
        "closed": False,
    }


def _source(markets: list[dict] | None = None, *, handler=None) -> PredictionSource:
    if handler is None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=markets or [])

    return PredictionSource(
        SETTINGS, client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )


# ── the inversion ─────────────────────────────────────────────────────────


async def test_the_probability_is_of_the_question_as_asked_not_the_leading_outcome():
    """Live: Yes 0.0015 / No 0.9985. Reporting 0.9985 against a subject that
    reads "will the fed decrease" is a near-certain lie."""
    facts = await _source([
        _market("Will the Fed decrease interest rates by 50+ bps after the July 2026 meeting?",
                yes=0.0015)
    ]).fetch(["USDC"])

    assert len(facts) == 1
    assert facts[0].value == 0.0015
    assert facts[0].value < 0.5, "reported the No side against a 'will X happen' question"


async def test_a_likely_outcome_is_reported_as_likely():
    """The fix must not simply invert everything."""
    facts = await _source([
        _market("Will there be no change in Fed interest rates after the July 2026 meeting?",
                yes=0.7525)
    ]).fetch(["USDC"])
    assert facts[0].value == 0.7525


async def test_a_non_binary_market_falls_back_to_the_first_outcome():
    """Not every market is Yes/No. The question is phrased around the first
    outcome, and the note names it either way."""
    facts = await _source([
        _market("How many Fed rate cuts in 2026?", yes=0.42, outcomes=("Two", "Three"))
    ]).fetch(["USDC"])
    assert facts[0].value == 0.42


# ── credibility ───────────────────────────────────────────────────────────


async def test_thin_markets_are_ignored():
    """An implied probability with $200 behind it is one person's opinion
    wearing a number."""
    facts = await _source([
        _market("Will the Fed cut rates?", yes=0.9, volume=MIN_VOLUME_24H_USD - 1)
    ]).fetch(["USDC"])
    assert facts == []


async def test_facts_carry_reduced_confidence():
    """A third-party consensus is not a measurement - the same treatment
    defillama gets for the same reason."""
    facts = await _source([_market("Will the Fed cut rates?", yes=0.24)]).fetch(["USDC"])
    assert facts[0].confidence is not None
    assert facts[0].confidence < 1.0


async def test_only_the_most_traded_markets_are_reported():
    markets = [
        _market(f"Will the Fed do thing {i}?", yes=0.5, volume=1_000_000 - i)
        for i in range(TOP_N + 5)
    ]
    facts = await _source(markets).fetch(["USDC"])
    assert len(facts) == TOP_N


# ── relevance ─────────────────────────────────────────────────────────────


async def test_irrelevant_markets_are_filtered_out():
    """Polymarket is mostly sports. The API's `search` parameter is ignored -
    verified live - so relevance is decided here."""
    facts = await _source([
        _market("LoL: Top Esports vs ThunderTalk Gaming (BO3)", yes=0.99, volume=2_255_750)
    ]).fetch(["USDC"])
    assert facts == []


async def test_a_relevant_market_survives_the_filter():
    facts = await _source([_market("Will inflation exceed 3% in 2026?", yes=0.31)]).fetch(["USDC"])
    assert len(facts) == 1


async def test_nothing_relevant_is_context_not_a_failure():
    source = _source([_market("LoL: some match", yes=0.9, volume=9_000_000)])
    assert await source.fetch(["USDC"]) == []
    assert source.drain_notes() == []
    assert "no forward-looking consensus" in source.drain_remarks()[0]


# ── the note carries the question ─────────────────────────────────────────


async def test_the_note_states_the_question_outcome_and_resolution_date():
    """A bare 0.751 against a slug is unreadable; the question is the fact."""
    source = _source([
        _market("Will there be no change in Fed interest rates after the July 2026 meeting?",
                yes=0.7525)
    ])
    await source.fetch(["USDC"])

    note = source.drain_remarks()[0]
    assert "no change in Fed interest rates" in note
    assert "75%" in note
    assert "2026-07-29" in note
    assert "not a measurement" in note


# ── shape and degradation ─────────────────────────────────────────────────


async def test_assets_are_ignored_because_macro_bears_on_every_book():
    """A Fed decision matters to a USDC lending book without USDC appearing
    anywhere in the question."""
    markets = [_market("Will the Fed cut rates?", yes=0.24)]
    assert len(await _source(markets).fetch([])) == 1
    assert len(await _source(markets).fetch(["WETH"])) == 1


async def test_the_emitted_kind_matches_the_declared_capability():
    """`provides` drives capability routing; a mismatch makes the source
    unreachable through the registry."""
    source = _source([_market("Will the Fed cut rates?", yes=0.24)])
    facts = await source.fetch(["USDC"])
    assert facts[0].kind == FACT_KIND
    assert FACT_KIND in source.provides


async def test_an_unreachable_api_degrades_rather_than_raising():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("[Errno 11001] getaddrinfo failed")

    source = _source(handler=handler)
    assert await source.fetch(["USDC"]) == []
    assert "DNS" in source.drain_notes()[0]


async def test_a_malformed_outcome_list_is_skipped_not_crashed():
    bad = {"question": "Will the Fed cut rates?", "outcomes": "not json",
           "outcomePrices": "[]", "volume24hr": 500_000.0}
    assert await _source([bad]).fetch(["USDC"]) == []
