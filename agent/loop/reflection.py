"""What happened after the agent last acted.

Every tick so far has been amnesiac. The model sees holdings and market data and
nothing about whether its last five decisions were any good — so it cannot learn
that its rotations keep costing more in slippage than the yield spread they
chase, and it cannot say so in its reasoning. A curator that never grades its
own homework is not curating, it is reacting.

This joins two records the system already keeps and has never put side by side:

    ActionJournal      what the agent decided, and what it expected
    PerformanceStore   what the vault was worth, before and after

## The discipline that governs this file

**A short window is noise, and the prompt must say so rather than implying a
verdict.** A share price that ticked up 4 bps in the twenty minutes after a
trade does not mean the trade was good; on a two-asset book it mostly means WETH
moved. Every outcome here is therefore reported with the window it was measured
over and an explicit confidence word, and `Outcome.verdict` is `"too early"`
until the evidence clears a bar rather than defaulting to a judgement.

The temptation is to hand the model a tidy "this trade made +0.3%" and let it
optimise. That is a reward hack waiting to happen: the model would learn to
trade before favourable drift and claim credit. Reporting the cost separately
from the drift is what keeps it honest — **realised cost is attributable, market
movement is not.**

## Cost is measured, not assumed

The share price drop across an executed tick is the *whole* cost of that trade:
slippage, fees and gas, in the units a depositor feels. It is the one number
here the agent is unambiguously responsible for, and it is available exactly
because the recorder writes a point after every tick.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

from curator_schema import AgentAction, PerformancePoint

from ..clock import to_utc, utcnow

__all__ = ["Outcome", "Reflection", "build_reflection"]

log = logging.getLogger(__name__)

#: How many past executed decisions to reflect on. Enough to see a pattern,
#: short enough that the prompt stays readable to a 3B model.
MAX_OUTCOMES = 5

#: Below this, a share-price move after a trade is not evidence about the trade.
#: Two-asset books move with WETH, and WETH moves for reasons the curator did
#: not cause. The number is deliberately generous.
_MIN_EVIDENCE_WINDOW = timedelta(hours=6)

#: A move smaller than this is inside the noise of a single swap's rounding.
_MATERIAL_MOVE = 0.001  # 10 bps


@dataclass(frozen=True)
class Outcome:
    """One past decision, and what the vault did afterwards."""

    action_id: str
    intent: str
    #: Share-price change across the executing tick itself — slippage, fees and
    #: gas, in the units a depositor feels. Attributable to the agent.
    realised_cost_pct: float | None
    #: Share-price change from just after the trade to now. NOT attributable —
    #: mostly the market, on any book holding a volatile asset.
    drift_since_pct: float | None
    #: Hours of evidence behind `drift_since_pct`.
    window_hours: float | None
    verdict: str

    def render(self) -> str:
        parts = [f"- {self.intent}"]
        if self.realised_cost_pct is not None:
            parts.append(f"cost {self.realised_cost_pct * 100:+.3f}% of share price")
        if self.drift_since_pct is not None and self.window_hours is not None:
            parts.append(
                f"share price {self.drift_since_pct * 100:+.3f}% over the "
                f"{self.window_hours:.1f}h since"
            )
        parts.append(self.verdict)
        return "  ".join(parts)


@dataclass(frozen=True)
class Reflection:
    """The agent's own track record, as it will be shown to the model."""

    outcomes: list[Outcome]
    return_pct: float | None
    max_drawdown_pct: float | None
    rejections: int
    executions: int

    def render(self) -> str:
        """The prompt block. Empty string when there is nothing honest to say."""
        if not self.outcomes and self.return_pct is None and not self.rejections:
            return ""

        lines = ["", "HOW YOUR RECENT DECISIONS HAVE WORKED OUT."]

        if self.return_pct is not None:
            summary = f"Share price is {self.return_pct * 100:+.3f}% since the record begins"
            if self.max_drawdown_pct is not None:
                summary += f", with a worst peak-to-trough fall of {self.max_drawdown_pct:.2%}"
            lines.append(summary + ".")

        if self.executions or self.rejections:
            lines.append(
                f"You have executed {self.executions} time(s) and had {self.rejections} "
                f"decision(s) rejected by validation."
            )

        if self.outcomes:
            lines.append("")
            lines += [outcome.render() for outcome in self.outcomes]

        lines.append("")
        lines.append(
            "Read this carefully and sceptically. The COST figure is yours — it is the "
            "slippage and fees your trade actually paid. The share-price move afterwards "
            "is mostly the market, not your skill, and over a few hours it is noise. Do "
            "not conclude a trade was good because the price rose after it."
        )
        lines.append(
            "What this IS good for: if your trades keep costing more than the edge you "
            "traded for, stop trading for that edge. Say so in your reasoning."
        )
        return "\n".join(lines)


def _price(point: PerformancePoint | None) -> float | None:
    if point is None or point.share_price is None:
        return None
    try:
        value = float(point.share_price)
    except ValueError:
        return None
    return value if value > 0 else None


def _nearest_before(points: list[PerformancePoint], when) -> PerformancePoint | None:
    candidates = [p for p in points if to_utc(p.timestamp) <= when]
    return candidates[-1] if candidates else None


def _nearest_after(points: list[PerformancePoint], when) -> PerformancePoint | None:
    return next((p for p in points if to_utc(p.timestamp) >= when), None)


#: Non-ASCII that venue adapters legitimately emit, and what to render instead.
#:
#: The rendered prompt must stay ASCII — Windows consoles are cp1252 and turn a
#: UTF-8 dash into a mojibake box, and the prompt reaches a terminal through
#: `agent.bench`. That invariant has a test, but the test uses fixtures, so text
#: arriving from a venue's `expected_effect` at runtime would slip past it. Real
#: output already contained both of these: "tokens stay in the vault —" and a
#: truncated address "0xd1f99f37…".
_ASCII_SUBSTITUTIONS = {
    "—": "-",  # em dash
    "–": "-",  # en dash
    "…": "...",  # ellipsis
    "‘": "'",
    "’": "'",
    "“": '"',
    "”": '"',
    " ": " ",  # non-breaking space
}


def _asciify(text: str) -> str:
    for source, replacement in _ASCII_SUBSTITUTIONS.items():
        text = text.replace(source, replacement)
    # Anything still outside ASCII is dropped rather than guessed at. Losing a
    # character from a one-line summary costs nothing; a mojibake box in the
    # prompt is noise the model has to reason around.
    return text.encode("ascii", "ignore").decode("ascii")


def _describe(action: AgentAction) -> str:
    """What the decision was trying to do, in one line.

    Prefers the venue's own `expected_effect` over the model's reasoning: the
    adapter's description is a statement of what the calldata does, while the
    reasoning is what the model believed. Feeding the model its own prose back
    invites it to agree with itself.
    """
    if action.plan and action.plan.expected_effect:
        return _asciify(action.plan.expected_effect[:160])
    if action.decision and action.decision.venue_intents:
        kinds = ", ".join(sorted({i.kind for i in action.decision.venue_intents}))
        return f"{action.decision.action} via {kinds}"
    return action.decision.action if action.decision else action.status


def _verdict(cost: float | None, drift: float | None, hours: float | None) -> str:
    """Deliberately conservative, and never a compliment.

    Returns "too early to tell" unless there is both a material move and enough
    elapsed time to mean anything. The alternative — always producing a verdict
    — trains the model to treat noise as signal, which is the failure this whole
    module is trying to avoid.
    """
    if hours is None or drift is None:
        return "(no follow-up data yet)"
    if hours < _MIN_EVIDENCE_WINDOW.total_seconds() / 3600:
        return "(too early to tell — under 6h of evidence)"
    if abs(drift) < _MATERIAL_MOVE:
        return "(flat since — no signal either way)"
    if cost is not None and drift < 0 and abs(drift) > abs(cost) * 2:
        return "(the book has fallen since, by more than the trade cost)"
    if drift > 0:
        return "(the book is up since, though the market may be the reason)"
    return "(the book is down since)"


def build_reflection(
    actions: list[AgentAction],
    points: list[PerformancePoint],
    *,
    limit: int = MAX_OUTCOMES,
) -> Reflection:
    """Join the decision journal to the share-price series.

    Both inputs may be empty or short; the result then says less rather than
    guessing more.
    """
    ordered = sorted(points, key=lambda p: to_utc(p.timestamp))
    now = utcnow()

    executed = sorted(
        (a for a in actions if a.status == "executed"),
        key=lambda a: to_utc(a.timestamp),
        reverse=True,
    )[:limit]

    outcomes: list[Outcome] = []
    for action in executed:
        at = to_utc(action.timestamp)
        before = _price(_nearest_before(ordered, at))
        after_point = _nearest_after(ordered, at)
        after = _price(after_point)
        latest = _price(ordered[-1]) if ordered else None

        cost = None
        if before is not None and after is not None:
            cost = (after - before) / before

        drift = window_hours = None
        if after is not None and latest is not None and after_point is not None:
            drift = (latest - after) / after
            window_hours = (now - to_utc(after_point.timestamp)).total_seconds() / 3600

        outcomes.append(
            Outcome(
                action_id=action.id,
                intent=_describe(action),
                realised_cost_pct=cost,
                drift_since_pct=drift,
                window_hours=window_hours,
                verdict=_verdict(cost, drift, window_hours),
            )
        )

    first = _price(ordered[0]) if ordered else None
    last = _price(ordered[-1]) if ordered else None
    total_return = (last - first) / first if first and last else None

    drawdown = None
    prices = [p for p in (_price(point) for point in ordered) if p is not None]
    if len(prices) >= 2:
        peak = prices[0]
        worst = 0.0
        for price in prices:
            peak = max(peak, price)
            worst = max(worst, (peak - price) / peak)
        drawdown = worst

    return Reflection(
        outcomes=outcomes,
        return_pct=total_return,
        max_drawdown_pct=drawdown,
        rejections=sum(1 for a in actions if a.status == "rejected"),
        executions=sum(1 for a in actions if a.status == "executed"),
    )
