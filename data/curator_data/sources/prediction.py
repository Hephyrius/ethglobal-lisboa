"""Prediction-market odds — what the market thinks happens next.

Every other source in this lane is **backward-looking**: an APY is what a
market paid, TVL is what is there now, a price is the last trade. A curator
allocating for the next period has nothing that says what people expect.

An implied probability is exactly that, and it is priced by people with money
on it. Read live on 2026-07-25:

    75.1%  no change in Fed interest rates after the July 2026 meeting
    24.1%  a 25bp increase
     0.4%  a 25bp decrease

For a vault whose entire book is lending yield, a 24% chance of a rate rise is
material information that no APY series contains.

## Read-only, free, no token gate

Polymarket's public gamma API. No credential, no signing, no position — this
source *reads odds*, it does not trade them. It ships independently of any
venue integration, and is the honest fallback if a prediction-market venue
never lands.

## Why the filtering is client-side

The API's `search` parameter is ignored — verified live, `search=ethereum` and
`search=fed` return byte-identical results, both led by an esports match. So
relevance is decided here, from `TOPICS`, against a page ordered by 24-hour
volume. Volume is the credibility filter that matters: an implied probability
from a market with $200 of volume is one person's opinion wearing a number.

## The fact kind is an interim

There is no `probability` in the frozen `FactKind` enum, and the schema says
plainly *"Extend this list rather than overloading an existing kind."* Lane F
owns that enum; the request is filed. Until it lands these are emitted as
`sentiment`, which is the closest honest fit — a forward-looking market
consensus — and `FACT_KIND` is a single constant so the switch is one line.
The subject carries the question, so these are never confused with the
Fear & Greed index at the point of use.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx
from curator_schema.models import Fact

from ..config import Settings
from ..diagnostics import OTHERS_UNAFFECTED, explain_exception
from ..facts import FactBuilder
from ..http import LoopBoundClient
from ..ports import BaseSource

logger = logging.getLogger(__name__)

API_URL = "https://gamma-api.polymarket.com/markets"

#: Emitted kind. Becomes `probability` once Lane F extends the enum — see the
#: module docstring. One constant so that is a one-line change.
FACT_KIND = "sentiment"

#: What a *vault curator* cares about, as opposed to what Polymarket is mostly
#: about (sports). Data, not code: widening the agent's forward view is an edit
#: here. Matched case-insensitively against the market question.
TOPICS: tuple[str, ...] = (
    "fed",
    "interest rate",
    "rate cut",
    "rate hike",
    "inflation",
    "cpi",
    "recession",
    "ethereum",
    "bitcoin",
    "stablecoin",
    "etf",
    "depeg",
)

#: Below this, an implied probability is one person's opinion wearing a number.
MIN_VOLUME_24H_USD = 10_000.0

#: Markets scanned per fetch. The API caps a page at 100 regardless of what is
#: asked for, verified live.
SCAN_LIMIT = 100

#: Facts emitted, most-traded first. Enough to be informative, few enough that
#: the snapshot stays readable.
TOP_N = 6

#: Prediction markets are a third-party consensus rather than a measurement, so
#: their facts carry lower confidence than an on-chain read - the same
#: treatment `defillama` gets for the same reason.
MARKET_CONFIDENCE = 0.5

_SLUG = re.compile(r"[^a-z0-9]+")


def _slug(question: str, limit: int = 48) -> str:
    """A short, stable identity for a market question."""
    text = _SLUG.sub("-", question.strip().lower()).strip("-")
    return text[:limit].rstrip("-") or "market"


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _json_list(raw: Any) -> list:
    """`outcomes` and `outcomePrices` arrive as JSON-encoded strings."""
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, list) else []
        except ValueError:
            return []
    return []


class PredictionSource(BaseSource):
    """Implied probabilities for events a curator should care about."""

    key = "prediction"
    provides = (FACT_KIND,)
    description = (
        "Implied probabilities from Polymarket for rate decisions, inflation and crypto "
        "events. The only forward-looking source here - everything else reports what "
        "already happened. Read-only and needs no credential."
    )

    def __init__(self, settings: Settings, *, client: httpx.AsyncClient | None = None):
        super().__init__()
        self.settings = settings
        self._owns_client = client is None
        self._http = LoopBoundClient(
            lambda: httpx.AsyncClient(timeout=settings.request_timeout_s, follow_redirects=True)
        )
        self._http.adopt(client)

    @property
    def client(self) -> httpx.AsyncClient:
        return self._http.get_client()

    async def fetch(self, assets: list[str]) -> list[Fact]:
        # Deliberately ignores `assets`: a Fed decision bears on a USDC lending
        # book without USDC appearing in the question.
        markets = await self._markets()
        if markets is None:
            return []

        relevant = []
        for market in markets:
            question = str(market.get("question") or "").strip()
            if not question or not self._is_relevant(question):
                continue
            volume = _to_float(market.get("volume24hr")) or 0.0
            if volume < MIN_VOLUME_24H_USD:
                continue
            probability = self._leading_probability(market)
            if probability is None:
                continue
            relevant.append((volume, question, probability, market))

        if not relevant:
            self.diagnose(
                "market universe",
                f"no open market above ${MIN_VOLUME_24H_USD:,.0f} of 24h volume matched "
                f"{len(TOPICS)} curator topics among the top {SCAN_LIMIT} by volume",
                "there is no forward-looking consensus in this snapshot; the backward-looking "
                "sources are unaffected",
                failure=False,
            )
            return []

        relevant.sort(key=lambda row: -row[0])
        builder = FactBuilder(self.key, chain=self.settings.chain)
        facts: list[Fact] = []

        for volume, question, probability, market in relevant[:TOP_N]:
            outcome, value = probability
            subject = builder.subject(market=_slug(question))
            facts.append(
                builder.fact(
                    FACT_KIND,
                    subject,
                    value,
                    "ratio",
                    confidence=MARKET_CONFIDENCE,
                )
            )
            # The slug alone does not say what was asked. Without the question
            # and the resolution date, a bare 0.751 is unreadable.
            ends = str(market.get("endDate") or "")[:10]
            self.diagnose(
                _slug(question),
                f'"{question}" - {outcome} at {value:.0%}'
                + (f", resolving {ends}" if ends else ""),
                f"a forward-looking market consensus with ${volume:,.0f} of 24h volume "
                f"behind it, not a measurement",
                failure=False,
            )
        return facts

    @staticmethod
    def _is_relevant(question: str) -> bool:
        lowered = question.lower()
        return any(topic in lowered for topic in TOPICS)

    @staticmethod
    def _leading_probability(market: dict) -> tuple[str, float] | None:
        """(outcome, probability) for **the question as asked**.

        This must be the `Yes` side, and getting it wrong is an inversion, not
        an inaccuracy. Reporting the *leading* outcome looks reasonable and is
        catastrophic: live, "Will the Fed decrease interest rates by 50+ bps?"
        prices `["Yes","No"] = [0.0015, 0.9985]`, so the leading outcome is
        `No` at 99.85%. A fact whose subject is `will-the-fed-decrease-...` and
        whose value is `0.9985` tells a model the near-certain opposite of what
        the market believes.

        The same class of bug as the Token API's direction-flipped price field,
        and the fix is the same: bind the number to the question rather than to
        whichever side happens to be winning.
        """
        outcomes = [str(o) for o in _json_list(market.get("outcomes"))]
        prices = [_to_float(p) for p in _json_list(market.get("outcomePrices"))]
        pairs = [
            (outcome, price)
            for outcome, price in zip(outcomes, prices, strict=False)
            if price is not None and 0.0 <= price <= 1.0
        ]
        if not pairs:
            return None

        for outcome, price in pairs:
            if outcome.strip().lower() == "yes":
                return outcome, price
        # Not a Yes/No market. The first outcome is the one the question is
        # phrased around, and it is named in the note either way.
        return pairs[0]

    async def _markets(self) -> list[dict] | None:
        params = {
            "closed": "false",
            "active": "true",
            "limit": str(SCAN_LIMIT),
            "order": "volume24hr",
            "ascending": "false",
        }
        try:
            response = await self.client.get(API_URL, params=params)
        except Exception as exc:  # noqa: BLE001 - a stray error must not kill the source
            self.diagnose("Polymarket", explain_exception(exc), OTHERS_UNAFFECTED)
            return None

        if response.status_code >= 400:
            self.diagnose(
                "Polymarket", f"HTTP {response.status_code}", OTHERS_UNAFFECTED
            )
            return None

        try:
            body = response.json()
        except ValueError:
            self.diagnose("Polymarket", "the response was not JSON", OTHERS_UNAFFECTED)
            return None

        rows = body if isinstance(body, list) else body.get("data")
        if not rows:
            self.diagnose(
                "Polymarket", "returned no open markets", OTHERS_UNAFFECTED, failure=False
            )
            return None
        return list(rows)

    async def close(self) -> None:
        if self._owns_client:
            await self._http.aclose()


def make_prediction_source(settings: Settings) -> PredictionSource:
    """Registration factory. Referenced from `sources/__init__.py`."""
    return PredictionSource(settings)


__all__ = ["PredictionSource", "make_prediction_source", "TOPICS", "FACT_KIND"]
