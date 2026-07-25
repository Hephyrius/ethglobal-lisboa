"""Crypto Fear & Greed — the one number that is not about a market.

`https://api.alternative.me/fng/` returns a single 0–100 index of crypto market
mood, updated daily, free and with no credential.

## Why a sentiment reading belongs in a yield curator's snapshot

Every other fact answers "what is this market paying?". None of them answers
"what is the market about to do?", and a curator deciding whether to rotate cash
into WETH is implicitly taking a view on exactly that. The index is a weak
signal and a well-known one, which is the point — it lets the agent say *"the
spread favours WETH but the market is at 78, extreme greed, so I am sizing
half"* instead of pretending the decision is purely arithmetic.

## Why it needed a new `Fact.kind`

`sentiment` is a new kind rather than a `ratio` smuggled in under `volatility`.
The curator prompt renders a `_KIND_LABELS` table specifically because a small
model that reads `f6 | liquidity | $12.4M` as "10.43% APY" is a failure we have
already observed. Overloading a kind is how that happens again.

Normalised to 0–1 at the adapter — 0.78, not 78 — because that is what every
other fraction-valued fact in the schema does, and a mixed convention inside one
snapshot is a trap for both the model and the UI.

## Not chain-specific, and honest about it

The index is global crypto sentiment, not a Base measurement. Its subject
therefore carries no token and no protocol; it describes the whole market. That
also means it is the one source here whose value would be identical on any
chain, which is worth knowing before anyone reads too much into it.
"""

from __future__ import annotations

import logging

# `datetime.UTC` is 3.11+, and this package supports 3.10 (the MCP SDK's
# floor). `timezone.utc` is the portable spelling.
from datetime import datetime, timezone
from typing import Any

import httpx
from curator_schema.models import Fact

from ..config import Settings
from ..facts import FactBuilder
from ..http import LoopBoundClient
from ..ports import BaseSource

logger = logging.getLogger(__name__)

FNG_URL = "https://api.alternative.me/fng/?limit=1&format=json"

#: The index moves once a day. Beyond this it is not "sentiment now", and the
#: agent should be told so rather than left to assume freshness.
STALE_AFTER_S = 48 * 3600

#: Low: a daily index is a weak input to an hourly decision, and `confidence`
#: is the honest place to say so.
SENTIMENT_CONFIDENCE = 0.5


class SentimentSource(BaseSource):
    """Crypto Fear & Greed, normalised to 0–1."""

    key = "feargreed"
    provides = ("sentiment",)
    description = (
        "The Crypto Fear & Greed index (alternative.me), normalised to 0–1 where 0 is "
        "extreme fear and 1 extreme greed. Free, no credential, updated daily. Global "
        "crypto mood rather than a Base measurement — a weak signal, labelled as one."
    )

    def __init__(self, settings: Settings, *, client: httpx.AsyncClient | None = None):
        super().__init__()
        self.settings = settings
        self._owns_client = client is None
        self._http = LoopBoundClient(
            lambda: httpx.AsyncClient(timeout=settings.request_timeout_s)
        )
        self._http.adopt(client)

    @property
    def client(self) -> httpx.AsyncClient:
        return self._http.get_client()

    async def fetch(self, assets: list[str]) -> list[Fact]:
        del assets  # global sentiment is not per-asset

        try:
            response = await self.client.get(FNG_URL, headers={"Accept": "application/json"})
        except httpx.HTTPError as exc:
            raise RuntimeError(
                f"Fear & Greed unreachable: {type(exc).__name__}: {exc}"
            ) from exc

        if response.status_code >= 400:
            raise RuntimeError(f"Fear & Greed returned HTTP {response.status_code}")

        try:
            body: Any = response.json()
        except ValueError as exc:
            raise RuntimeError("Fear & Greed returned non-JSON") from exc

        rows = body.get("data") if isinstance(body, dict) else None
        if not rows:
            raise RuntimeError("Fear & Greed returned no readings")

        row = rows[0]
        try:
            raw = float(row.get("value"))
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                f"Fear & Greed value was not a number: {row.get('value')!r}"
            ) from exc

        if not 0 <= raw <= 100:
            # Out of range means the API changed shape. Reporting it as 0–1
            # anyway would feed the agent a number with no defined meaning.
            raise RuntimeError(f"Fear & Greed returned {raw}, outside its documented 0-100")

        observed = self._observed_at(row)
        if observed is not None:
            age = (datetime.now(timezone.utc) - observed).total_seconds()
            if age > STALE_AFTER_S:
                self.remark(
                    f"the index is {age / 3600:.0f}h old — it updates daily, so treat this as "
                    f"a stale reading rather than current mood"
                )

        builder = FactBuilder(self.key, chain=self.settings.chain)
        classification = str(row.get("value_classification") or "").strip()
        return [
            builder.ratio(
                "sentiment",
                # No token, no protocol: this describes the whole market, and
                # attaching it to an asset would imply a measurement we did not
                # make. `market` carries the human label the API gives it.
                builder.subject(market=classification or "crypto market"),
                raw / 100.0,
                observed_at=observed,
                confidence=SENTIMENT_CONFIDENCE,
            )
        ]

    @staticmethod
    def _observed_at(row: dict) -> datetime | None:
        """`timestamp` is a unix string. When the index was published, not when
        we asked — staleness is the agent's to reason about (frozen schema)."""
        try:
            return datetime.fromtimestamp(int(row.get("timestamp")), tz=timezone.utc)
        except (TypeError, ValueError):
            return None

    async def close(self) -> None:
        if self._owns_client:
            await self._http.aclose()


def make_sentiment_source(settings: Settings) -> SentimentSource:
    """Registration factory. Referenced from `sources/__init__.py`."""
    return SentimentSource(settings)


__all__ = ["SentimentSource", "make_sentiment_source", "STALE_AFTER_S"]
