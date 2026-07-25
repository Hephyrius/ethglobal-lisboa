"""Idle capital, as a fact the model can cite.

Wave 2's headline feedback: *"ensure that the agents are deploying — liquidity
needs to be deployed on Aqua (or other protocols) when idle within risk
parameters of the vault."* Today the agent swaps and then sits on cash.

The fix is deliberately **not** a validation layer. `hold` is a first-class
answer and a harness that rejects it churns the vault, which is the failure the
whole six-layer design exists to prevent. Pressure belongs in the prompt and the
scoreboard; the gate stays about legality.

What this module does instead is make idle capital *visible and citable*. The
snapshot gains one derived fact, so the decision feed can show **"deployed
because 68% of the book was idle"** with the number attached — rather than the
agent asserting it and the reader having to take that on trust. Citability is
the point: `facts_used` is validated against the snapshot (layer 4), so a fact
the model can cite is a fact it cannot invent.

**Idle means "beyond the cash the mandate requires, and backing nothing."** Base
asset above `min_cash_pct` that carries no `committed_to_venue`. Capital backing
an Aqua position is *encumbered, not idle*, even though the tokens are still in
the vault — that distinction is the whole Pattern 1 claim, and counting it as
idle would tell the agent to deploy money it has already deployed.

No schema change: `source="harness"` marks a fact this lane derived about the
vault itself rather than one a provider reported, which keeps provenance honest
in the UI (Wave 2 plan §3.5 — a field for this would put policy in the frozen
interface).
"""

from __future__ import annotations

from curator_schema import Fact, FactSubject, Mandate, MarketSnapshot, VaultState

from ..clock import utcnow

__all__ = [
    "HARNESS_SOURCE",
    "IDLE_FACT_ID",
    "idle_fraction",
    "idle_capital_fact",
    "best_lending_rate",
    "idle_drag_for",
]

#: Provenance for facts the harness derives about the vault, as opposed to
#: market data a provider reported. Rendered distinctly in the prompt and shown
#: as-is in the feed, so nobody reads a derived figure as a Graph query result.
HARNESS_SOURCE = "harness"

#: Stable id, because the model cites it and the feed joins on it.
IDLE_FACT_ID = "vault:idle-capital"

#: Below this the surplus is rounding, not a position worth a transaction.
_MATERIAL = 0.01


def idle_fraction(mandate: Mandate, vault: VaultState | None) -> float | None:
    """Share of the vault earning nothing that the mandate does not require.

    `None` when it cannot be computed honestly — no vault, nothing valued, or an
    empty book. Returning 0.0 in those cases would tell the model the vault is
    fully deployed when the truth is that we do not know.
    """
    if vault is None:
        return None
    total = int(vault.total_assets or 0)
    if total <= 0:
        return None

    uncommitted = sum(
        int(h.value_in_asset)
        for h in vault.holdings
        if h.symbol == mandate.base_asset
        and h.value_in_asset is not None
        and not h.committed_to_venue
    )
    if not any(h.value_in_asset is not None for h in vault.holdings):
        return None

    surplus = uncommitted / total - mandate.constraints.min_cash_pct
    return max(0.0, surplus)


def idle_capital_fact(mandate: Mandate, vault: VaultState | None) -> Fact | None:
    """The idle share as a citable `Fact`, or None if it cannot be derived.

    Emitted even when the figure is 0.0 — "nothing is idle" is a fact worth
    citing when the agent holds, and its absence would leave the model unable to
    justify holding with anything concrete.
    """
    fraction = idle_fraction(mandate, vault)
    if fraction is None:
        return None

    return Fact(
        id=IDLE_FACT_ID,
        kind="utilization",
        subject=FactSubject(
            protocol="this vault",
            market="capital earning nothing",
            token=mandate.base_asset,
        ),
        value=round(fraction, 4),
        unit="ratio",
        source=HARNESS_SOURCE,
        observed_at=utcnow(),
        confidence=1.0,
    )


def with_idle_fact(
    snapshot: MarketSnapshot, mandate: Mandate, vault: VaultState | None
) -> MarketSnapshot:
    """The snapshot plus the idle fact, if one could be derived.

    Appended after the registry returns, so Lane C's contract is untouched and a
    source that fails still degrades exactly as before.
    """
    fact = idle_capital_fact(mandate, vault)
    if fact is None:
        return snapshot
    return snapshot.model_copy(update={"facts": [*snapshot.facts, fact]})


def is_material(fraction: float | None) -> bool:
    """Whether an idle share is worth acting on rather than rounding noise."""
    return fraction is not None and fraction > _MATERIAL


def best_lending_rate(
    snapshot: MarketSnapshot, mandate: Mandate
) -> tuple[float, str] | None:
    """The best lending yield in the snapshot for an asset the mandate permits.

    `(apy_fraction, where)`. Used to price what idle capital forwent — the drag
    only means something against a rate the agent could actually have taken, so
    yields on assets outside `allowed_assets` are ignored rather than quoted as
    a missed opportunity the mandate forbade.
    """
    allowed = {a.lower() for a in mandate.constraints.allowed_assets}
    best: tuple[float, str] | None = None

    for fact in snapshot.facts:
        if fact.kind != "yield" or fact.unit != "apy_fraction":
            continue
        subject = fact.subject
        market = (subject.market or subject.token or "").lower()
        if market and market not in allowed:
            continue
        where = " ".join(p for p in (subject.protocol, subject.market) if p) or fact.id
        if best is None or fact.value > best[0]:
            best = (fact.value, where)

    return best


def idle_drag_for(mandate: Mandate, vault: VaultState | None, snapshot: MarketSnapshot, hours):
    """Assemble the `IdleDrag` the reflection renders, or None.

    Returns None whenever any leg is unknown rather than substituting a zero:
    "we could not price the drag" and "the drag is nothing" are different
    statements, and only one of them is true when there is no yield in the
    snapshot.
    """
    from .reflection import IdleDrag

    fraction = idle_fraction(mandate, vault)
    if not is_material(fraction):
        return None
    best = best_lending_rate(snapshot, mandate)
    if best is None:
        return None
    rate, where = best
    return IdleDrag(idle_pct=fraction, best_rate=rate, where=where, hours=hours)
