"""Constructing `Fact`s correctly, so sources don't each get it wrong.

Two invariants from the frozen schema are easy to violate and expensive when
violated:

  * **`Fact.source` must be the registry key.** Provenance is the whole point;
    a fact whose source is wrong is worse than a missing fact.
  * **`apy_fraction` is 0.0432 for 4.32%, never 4.32.** Normalise at the source
    adapter. Messari reports interest rates as percentages, so this is a live
    trap, not a hypothetical one.

`FactBuilder` makes both structural. A source constructs one with its own key
and then cannot emit a fact attributed to anyone else, and the APY constructors
are named after the unit they consume (`apy_from_percent` / `apy_from_fraction`)
so the conversion is a decision at the call site rather than an assumption.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from curator_schema.models import Fact, FactKind, FactSubject

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _slug(value: str) -> str:
    return _SLUG_STRIP.sub("-", value.strip().lower()).strip("-")


def subject_slug(subject: FactSubject) -> str:
    """Compact, human-readable identity for a fact's subject.

    Appears in fact ids, which the dApp renders next to the agent's reasoning —
    `messari:yield:aave-v3/usdc` is legible in a decision feed;
    a hash is not.
    """
    parts: list[str] = []
    if subject.protocol:
        parts.append(_slug(subject.protocol))
    if subject.market:
        parts.append(_slug(subject.market))
    if subject.token:
        parts.append(_slug(subject.token))
    if subject.pair:
        parts.append("-".join(_slug(p) for p in subject.pair))
    return "/".join(parts) or "unknown"


class FactBuilder:
    """Emits `Fact`s already stamped with one source's provenance.

    Ids are deterministic (`source:kind:subject`) rather than sequential: the
    same market observed in two consecutive snapshots keeps the same id, which
    is what lets the dApp diff decisions and lets us spot a model citing a fact
    it was never shown. The registry de-duplicates collisions at merge time.
    """

    def __init__(self, source: str, *, chain: str = "base", observed_at: datetime | None = None):
        if not source:
            raise ValueError("FactBuilder requires a source key — provenance is not optional")
        self.source = source
        self.chain = chain
        self.observed_at = observed_at or utcnow()

    # ── subject helpers ───────────────────────────────────────────────────

    def subject(
        self,
        *,
        protocol: str | None = None,
        market: str | None = None,
        token: str | None = None,
        pair: list[str] | None = None,
    ) -> FactSubject:
        return FactSubject(
            protocol=protocol, market=market, token=token, pair=pair, chain=self.chain
        )

    # ── the general form ──────────────────────────────────────────────────

    def fact(
        self,
        kind: FactKind,
        subject: FactSubject,
        value: float,
        unit: str,
        *,
        observed_at: datetime | None = None,
        confidence: float | None = None,
    ) -> Fact:
        return Fact(
            id=f"{self.source}:{kind}:{subject_slug(subject)}",
            kind=kind,
            subject=subject,
            value=float(value),
            unit=unit,  # type: ignore[arg-type]  # validated by pydantic
            source=self.source,
            observed_at=observed_at or self.observed_at,
            confidence=confidence,
        )

    # ── unit-safe constructors ────────────────────────────────────────────

    def apy_from_percent(self, subject: FactSubject, percent: float, **kw) -> Fact:
        """APY given as `4.32` meaning 4.32%. Converts to the 0.0432 the schema wants."""
        return self.fact("yield", subject, float(percent) / 100.0, "apy_fraction", **kw)

    def apy_from_fraction(self, subject: FactSubject, fraction: float, **kw) -> Fact:
        """APY already normalised: `0.0432` meaning 4.32%."""
        return self.fact("yield", subject, float(fraction), "apy_fraction", **kw)

    def usd(self, kind: FactKind, subject: FactSubject, value: float, **kw) -> Fact:
        return self.fact(kind, subject, float(value), "usd", **kw)

    def ratio(self, kind: FactKind, subject: FactSubject, value: float, **kw) -> Fact:
        return self.fact(kind, subject, float(value), "ratio", **kw)


def dedupe_ids(facts: list[Fact]) -> list[Fact]:
    """Guarantee id uniqueness within one snapshot.

    Deterministic ids can legitimately collide — two Aave markets whose names
    slugify identically, say. `AllocationDecision.facts_used` points at these,
    so a duplicate would make a decision's citation ambiguous. Later duplicates
    get a `#n` suffix; the first keeps the clean id so the common case stays
    readable.
    """
    seen: dict[str, int] = {}
    out: list[Fact] = []
    for fact in facts:
        count = seen.get(fact.id, 0)
        seen[fact.id] = count + 1
        out.append(fact if count == 0 else fact.model_copy(update={"id": f"{fact.id}#{count}"}))
    return out


__all__ = ["FactBuilder", "dedupe_ids", "subject_slug", "utcnow"]
