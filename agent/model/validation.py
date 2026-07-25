"""Output validation — the load-bearing layer of this whole component.

`plans/initiate_plan.md` §2 locks three things together: the mandate is soft and
off-chain, the agent holds a key and executes directly, and no human can override
it after genesis. There is no on-chain backstop. So the *only* thing standing
between a 14B open-weight model's output and a signed transaction is this file.
It fails closed: anything it cannot fully validate is rejected and recorded, and
nothing unvalidated reaches a venue or the chain.

## Five layers, five different retry hints

| Layer | Catches | What the model is told |
|---|---|---|
| 1 extract | fences, prose, `<think>`, trailing commas | "return only a JSON object" |
| 2 schema | wrong types, unknown fields, bad enums | the pydantic error, compacted |
| 3 mandate | forbidden asset, weights ≠ 1, too many actions | the breach *and the limit* |
| 4 grounding | citing facts that were never in the snapshot | the invented ids and the real ones |
| 5 direction | trades moving *away* from the decision's own targets | which side is past target |

The layering is what makes retries work. A single "invalid output, try again"
teaches the model nothing and burns the tick; a message naming the breach and the
limit it violated is usually fixed on the next attempt.

Layer 5 was added after the loop executed a real transaction in the wrong
direction: the model read a 70/30 book against a 50/50 target, said so correctly,
and then sold the *under*-weighted asset. Layers 1–4 all passed it, because the
decision was internally consistent in every respect except the sign. It needs the
vault state, so it only runs when one is supplied — but every live tick supplies
one.

## Why grounding is a validation layer and not a nicety

`AllocationDecision.facts_used` must reference real `Fact.id`s from the snapshot
the model was given (`packages/schema/README.md`). Two things depend on it: the
dApp joins facts to reasoning to transaction hash to show *why* the agent acted,
and a model citing `f9` when the snapshot stopped at `f6` has demonstrably
stopped reading its inputs. That is the cheapest available signal that the
reasoning is confabulated, and a confabulated rebalance spends real money.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from curator_schema import AllocationDecision, Mandate, MarketSnapshot, VaultState
from curator_schema.ports import ModelBackend
from pydantic import ValidationError

from ..mandate.constraints import check_decision, check_rebalance_direction, describe
from .extraction import ExtractionError, extract_json_object

__all__ = [
    "DecisionRejected",
    "ValidatedDecision",
    "validate_decision",
    "generate_validated_decision",
]

log = logging.getLogger(__name__)

#: How much of a bad response is echoed back on retry. Enough for the model to
#: recognise its own output, short enough that three failures cannot crowd the
#: real prompt out of a small context window.
_ECHO_LIMIT = 1200
#: Pydantic reports every error; more than a handful is noise that buries the
#: first, actionable one.
_MAX_SCHEMA_ERRORS = 6


class DecisionRejected(Exception):
    """Every attempt failed validation. Nothing was executed.

    The cycle records this as `AgentAction(status="rejected")` with `failures`
    as the error — kept deliberately, because those records are the evidence
    that this layer does something.
    """

    def __init__(self, attempts: int, failures: Sequence[str]) -> None:
        self.attempts = attempts
        self.failures = list(failures)
        detail = "; ".join(f"attempt {i + 1}: {f}" for i, f in enumerate(self.failures))
        super().__init__(f"decision rejected after {attempts} attempt(s) — {detail}")


@dataclass
class ValidatedDecision:
    """A decision that passed every layer, plus what it took to get there."""

    decision: AllocationDecision
    #: Total attempts, including the successful one.
    attempts: int = 1
    #: Rejections along the way. Surfaced as `ModelProvenance.validation_retries`
    #: and worth showing: the honest cost of running a small local model.
    failures: list[str] = field(default_factory=list)

    @property
    def retries(self) -> int:
        return self.attempts - 1


def _compact_schema_errors(error: ValidationError) -> str:
    lines = []
    for item in error.errors()[:_MAX_SCHEMA_ERRORS]:
        location = ".".join(str(p) for p in item["loc"]) or "<root>"
        lines.append(f"{location}: {item['msg']}")
    remaining = len(error.errors()) - len(lines)
    if remaining > 0:
        lines.append(f"(and {remaining} more)")
    return "; ".join(lines)


def _check_grounding(decision: AllocationDecision, snapshot: MarketSnapshot) -> str | None:
    available = {fact.id for fact in snapshot.facts}
    cited = set(decision.facts_used)

    if invented := sorted(cited - available):
        known = ", ".join(sorted(available)) or "none"
        verb = "was" if len(invented) == 1 else "were"
        return (
            f"facts_used cites {', '.join(invented)}, which {verb} not in the market "
            f"snapshot you were given. Cite only these fact ids: {known}"
        )

    # A trade justified by no data at all is not a decision, it is a guess.
    # Holding without citing anything is legitimate — sometimes the honest
    # reason to hold is that nothing could be read this tick.
    if available and not cited and decision.action != "hold":
        return (
            f"action '{decision.action}' cites no facts. Every action other than 'hold' must "
            f"list the fact ids that justify it in facts_used. Available ids: "
            f"{', '.join(sorted(available))}"
        )

    return None


def validate_decision(
    raw: str,
    mandate: Mandate,
    snapshot: MarketSnapshot,
    vault: VaultState | None = None,
) -> AllocationDecision:
    """Run every layer over one raw model response.

    Raises `ValueError` whose message is written to be fed straight back to the
    model as a correction. Returns only a decision that is well-formed, legal
    under the mandate, grounded in the snapshot it was given, and — when `vault`
    is supplied — actually moving the portfolio toward its own stated targets.
    """
    # 1 — extract
    payload: dict[str, Any] = extract_json_object(raw)

    # 2 — schema
    try:
        decision = AllocationDecision.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(
            f"your JSON does not match the required schema — {_compact_schema_errors(exc)}. "
            "Fix these fields and return the corrected JSON object."
        ) from exc

    # 3 — mandate
    if violations := check_decision(decision, mandate):
        raise ValueError(
            f"your decision breaches the mandate — {describe(violations)}. "
            "Return a corrected decision that respects these limits."
        )

    # 4 — grounding
    if problem := _check_grounding(decision, snapshot):
        raise ValueError(problem)

    # 5 — direction. Needs the vault, so it only runs when one was supplied.
    if violations := check_rebalance_direction(decision, vault):
        raise ValueError(
            f"your trades move the vault away from your own targets — {describe(violations)}. "
            "Return a corrected decision whose swaps close the gap."
        )

    return decision


async def generate_validated_decision(
    backend: ModelBackend,
    messages: list[dict[str, str]],
    *,
    mandate: Mandate,
    snapshot: MarketSnapshot,
    vault: VaultState | None = None,
    max_attempts: int = 3,
    json_schema: dict[str, Any] | None = None,
    temperature: float = 0.0,
) -> ValidatedDecision:
    """Ask the model for a decision, rejecting and retrying until it is valid.

    The correction is appended as a real conversation turn — the model's own bad
    output as an `assistant` message, the specific failure as a `user` message —
    rather than restarting from a rewritten prompt. Models correct their own
    visible mistakes far more reliably than they avoid an abstract one described
    in the system prompt, and it keeps the original task text intact.

    Raises `DecisionRejected` when attempts are exhausted. It never returns an
    unvalidated decision, and the caller must treat the exception as a real
    outcome to record, not an error to swallow.
    """
    attempts = max(1, max_attempts)
    conversation = list(messages)
    failures: list[str] = []

    for attempt in range(1, attempts + 1):
        raw = await backend.complete(
            conversation, json_schema=json_schema, temperature=temperature
        )
        try:
            decision = validate_decision(raw, mandate, snapshot, vault)
        except (ValueError, ExtractionError) as exc:
            failure = str(exc)
            failures.append(failure)
            log.warning("decision attempt %d/%d rejected: %s", attempt, attempts, failure)
            if attempt == attempts:
                break
            conversation = [
                *conversation,
                {"role": "assistant", "content": (raw or "")[:_ECHO_LIMIT]},
                {
                    "role": "user",
                    "content": (
                        f"That response was rejected. {failure}\n\n"
                        "Reply with the corrected JSON object only — no explanation, "
                        "no code fences."
                    ),
                },
            ]
            continue

        if failures:
            log.info(
                "decision accepted on attempt %d after %d rejection(s)", attempt, len(failures)
            )
        return ValidatedDecision(decision=decision, attempts=attempt, failures=failures)

    raise DecisionRejected(attempts, failures)
