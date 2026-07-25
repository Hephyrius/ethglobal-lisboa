"""The five things a candidate model is scored on, and how each is decided.

Every metric here is structural. Nothing is scored by reading the model's prose, because the point
of the exercise is to find out whether a model can drive this harness — and the harness does not
read prose either. It validates, checks constraints, and submits calldata.

The scoring reuses Lane B's own validation and constraint functions rather than reimplementing
them. That is deliberate: a bake-off scored against a private copy of the rules measures the copy.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

from agent.mandate.constraints import check_decision
from agent.model.validation import validate_decision
from curator_schema import AllocationDecision, Mandate, MarketSnapshot, VaultState

from .scenarios import Scenario


@dataclass
class Trial:
    """One model, one scenario, one attempt."""

    model: str
    scenario: str
    #: Metric 1. Retries are the entire cost of a small model, so first-attempt validity is the
    #: headline rather than eventual success.
    valid_first_attempt: bool
    #: Metric 2. Empty means every mandate limit held.
    violations: list[str] = field(default_factory=list)
    #: Metric 3, the go/no-go. Did it author the intent the scenario needs at all?
    authored_wanted_intent: bool = False
    intents: list[str] = field(default_factory=list)
    action: str | None = None
    #: Metric 4. A cited fact that was never in the snapshot breaks the data -> reasoning -> tx
    #: chain that IS the product, so it is tracked separately from citing nothing.
    facts_cited: int = 0
    facts_invented: list[str] = field(default_factory=list)
    #: Metric 5. Wall clock, on this hardware, including the model loading if it was cold.
    latency_s: float = 0.0
    #: Present when the output never validated. The message is the diagnosis.
    error: str | None = None
    #: The model's own words, kept so a human can sanity-check a suspiciously good score.
    reasoning: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def score(
    raw: str,
    *,
    model: str,
    scenario: Scenario,
    snapshot: MarketSnapshot,
    latency_s: float,
) -> Trial:
    """Turn one raw model response into a scored trial.

    `validate_decision` is Lane B's own gate — schema, fact references, and the mandate-aware
    checks. If it raises, the model produced something the real harness would have rejected and
    retried, which is exactly metric 1.
    """
    trial = Trial(
        model=model,
        scenario=scenario.key,
        valid_first_attempt=False,
        latency_s=round(latency_s, 2),
    )

    try:
        decision: AllocationDecision = validate_decision(
            raw, scenario.mandate, snapshot, scenario.vault
        )
    except Exception as exc:  # noqa: BLE001 — any failure is the same finding: it did not validate
        trial.error = f"{type(exc).__name__}: {exc}"[:400]
        return trial

    trial.valid_first_attempt = True
    trial.action = decision.action
    trial.reasoning = (decision.reasoning or "")[:600]

    intents = [i.kind for i in (decision.venue_intents or [])]
    trial.intents = intents
    if scenario.wanted_intents:
        trial.authored_wanted_intent = any(k in scenario.wanted_intents for k in intents)
    else:
        # The control scenario: the wanted answer is to do nothing, and doing nothing is only
        # credited when it is expressed as `hold` rather than as an empty intent list on a
        # `rebalance`, which would be a malformed answer that happens to be harmless.
        trial.authored_wanted_intent = decision.action == "hold" and not intents

    known = {f.id for f in snapshot.facts}
    trial.facts_cited = len(decision.facts_used)
    trial.facts_invented = [f for f in decision.facts_used if f not in known]

    trial.violations = [str(v) for v in check_decision(decision, scenario.mandate)]
    return trial


@dataclass
class ModelReport:
    model: str
    trials: list[Trial]

    @property
    def n(self) -> int:
        return len(self.trials)

    @property
    def valid_rate(self) -> float:
        return _rate(t.valid_first_attempt for t in self.trials)

    @property
    def compliant_rate(self) -> float:
        """Of the trials that validated, how many broke no mandate limit.

        Conditioned on validity on purpose: a model that never produces parseable output has no
        compliance rate, and reporting 0% would read as "it proposes illegal trades" when the
        truth is "it proposes nothing".
        """
        valid = [t for t in self.trials if t.valid_first_attempt]
        if not valid:
            return float("nan")
        return _rate(not t.violations for t in valid)

    @property
    def right_shape_rate(self) -> float:
        return _rate(t.authored_wanted_intent for t in self.trials)

    @property
    def invented_facts(self) -> int:
        return sum(len(t.facts_invented) for t in self.trials)

    @property
    def median_latency_s(self) -> float:
        lat = sorted(t.latency_s for t in self.trials)
        if not lat:
            return float("nan")
        mid = len(lat) // 2
        return lat[mid] if len(lat) % 2 else (lat[mid - 1] + lat[mid]) / 2

    def can_author(self, scenario_key: str) -> bool:
        """The go/no-go. Once, ever, across all trials of that scenario — a model that manages it
        one time in five is still a model that CAN, and the retry loop exists for exactly that."""
        return any(
            t.authored_wanted_intent for t in self.trials if t.scenario == scenario_key
        )

    def can_author_intent(self, scenario_key: str, kind: str) -> bool:
        """Did it ever author THIS intent kind — not merely an acceptable one?

        `can_author()` is not a substitute, and using it for the ship column was a
        real bug that survived the whole 3B run. `balanced-ship` accepts
        `("ship", "supply")` because supplying the idle leg is a defensible answer
        there, so a model that only ever supplies still scores `authored_wanted_intent`.
        The 3B never exposed it: its output was invalid, so the column read ❌ for the
        right answer by accident. Grok made it read ✅ while authoring **zero** ships.

        The claim that column feeds — "the model can author an Aqua ship" — is one
        the submission would have carried. A metric that is only correct when the
        model fails is not a metric.
        """
        return any(
            kind in t.intents for t in self.trials if t.scenario == scenario_key
        )


def _rate(flags) -> float:
    flags = list(flags)
    return (sum(1 for f in flags if f) / len(flags)) if flags else float("nan")


def markdown_table(reports: list[ModelReport], ship_scenario: str = "balanced-ship") -> str:
    """The table that goes in the build log. Written for a reader deciding which model to run."""
    lines = [
        "| Model | Valid 1st attempt | Mandate-compliant | Right shape | Authored a ship | "
        "Invented facts | Median latency |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in reports:
        lines.append(
            f"| `{r.model}` | {_pct(r.valid_rate)} | {_pct(r.compliant_rate)} | "
            f"{_pct(r.right_shape_rate)} | "
            f"{'✅' if r.can_author_intent(ship_scenario, 'ship') else '❌'} | "
            f"{r.invented_facts} | {r.median_latency_s:.0f}s |"
        )
    return "\n".join(lines)


def _pct(value: float) -> str:
    return "n/a" if value != value else f"{value * 100:.0f}%"
