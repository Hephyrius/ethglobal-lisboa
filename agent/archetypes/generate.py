"""Generate a mandate inside an envelope, or refuse to deploy one.

This is `agent/model/validation.py`'s discipline applied at genesis, and for the
same reason: **nobody reads this output before it reaches the chain.** The
decision loop has six layers because a model's word is not evidence; a generated
mandate has this because a card that says *"never holds anything but USDC"* and
a vault that permits WETH is a lie told to a depositor by a machine.

## Two failure kinds, treated differently on purpose

**An envelope violation is fatal.** Regenerate, and if the attempts run out,
raise. There is no version of "deploy it anyway" that is defensible: the bounds
are what the card promised and what makes an unread mandate safe to ship.

**A collision is not.** If the model produces a strategy this archetype has
already deployed, that is disappointing rather than dangerous — the vault is
still inside its bounds and still correct. So a collision buys a regeneration
with the earlier names named, and if the attempts run out the mandate deploys
with `collided` recorded. A duplicate vault is a cosmetic failure; a button that
refuses to work is a functional one, and the demo cannot afford the second to
avoid the first.

## Uniqueness is structural, not hoped for

Temperature alone collides — that observation is why `Archetype.emphases`
exists. Three things vary per call and only the last is chance:

1. **A rotating emphasis**, advanced by the store rather than sampled, so the
   second click cannot draw the same angle as the first.
2. **A live market snapshot**, when one can be read, so the same click at
   different times sees different conditions.
3. **A nonce**, which is the weakest of the three and is there to break ties
   between two clicks that share an emphasis and a snapshot.

## The unpriceable-asset gate

`allowed_assets` is checked against `offerable_assets()` as well as against the
envelope. Belt and braces, because these are two different failure modes: the
envelope is a promise about *this product*, while `offerable_assets()` is about
what the vault can physically value. Cross-lane #78 found that the agent could
amend its way into an asset `totalAssets()` cannot see, permanently collapsing
the share price. That path has a model in the loop and a mandate that agreed to
it. This one has neither, so the same gate belongs here more, not less.
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import Sequence
from dataclasses import dataclass, field

from curator_schema import Archetype, Mandate, MarketSnapshot, check_envelope
from pydantic import ValidationError

from ..mandate.universe import offerable_assets
from ..model.extraction import ExtractionError, extract_json_object
from ..model.prompts.archetype import archetype_messages, archetype_schema
from ..security.untrusted import sanitize
from .store import signature

__all__ = ["GenerationFailed", "Generated", "generate_mandate", "market_context"]

log = logging.getLogger(__name__)

#: Enough for a model that misses a bound once to be told and fix it, few enough
#: that a click cannot hang for a minute. Grok answers in ~2.3s, so the worst
#: case here is ~10s; under the 3B it was closer to a minute, which is why this
#: feature was not practical before the backend changed.
DEFAULT_ATTEMPTS = 4

#: A little above zero. Exactly 0.0 makes every click with the same emphasis and
#: the same snapshot produce the same mandate, which defeats the nonce; high
#: enough and the model starts leaving the envelope for no benefit.
TEMPERATURE = 0.7


class GenerationFailed(Exception):
    """No generation sat inside the envelope. Nothing was deployed."""

    def __init__(self, key: str, attempts: int, failures: Sequence[str]) -> None:
        self.key = key
        self.attempts = attempts
        self.failures = list(failures)
        detail = "; ".join(f"attempt {i + 1}: {f}" for i, f in enumerate(self.failures))
        super().__init__(
            f"no mandate inside the '{key}' envelope after {attempts} attempt(s) — {detail}"
        )


@dataclass
class Generated:
    """A mandate that passed its envelope, and what it took."""

    mandate: Mandate
    archetype: str
    emphasis: str
    emphasis_index: int
    attempts: int = 1
    #: Every rejection along the way, in the words the model was given back.
    #: Surfaced rather than hidden: the same argument as
    #: `ModelProvenance.validation_retries`, and it is the evidence that the
    #: envelope check does something.
    rejections: list[str] = field(default_factory=list)
    #: True when this strategy matched one this archetype had already produced
    #: and the attempts ran out. Recorded rather than raised — see the module
    #: docstring.
    collided: bool = False

    @property
    def signature(self) -> str:
        return signature(self.mandate)


def market_context(snapshot: MarketSnapshot | None, limit: int = 6) -> str:
    """A few lines of what the market looked like when the button was pressed.

    Sanitised, because these are third-party labels reaching a prompt exactly as
    they do in the decision loop — the same channel, and there is no reason the
    generation path should be the soft one. Capped at a handful of facts: this is
    a seed for variety, not a dataset, and a page of numbers invites the model to
    hardcode one into a mandate that will outlive it.
    """
    if snapshot is None or not snapshot.facts:
        return ""
    lines = []
    for fact in snapshot.facts[:limit]:
        subject = fact.subject
        about = " ".join(
            p for p in (subject.protocol, subject.market, subject.token) if p
        ) or subject.chain
        lines.append(f"- {sanitize(about)}: {fact.value:g} ({fact.kind})")
    return "\n".join(lines)


def _unpriceable(mandate: Mandate) -> list[str]:
    """Assets the vault cannot value. Fails closed when the venue layer is absent."""
    return sorted(set(mandate.constraints.allowed_assets) - set(offerable_assets()))


async def generate_mandate(
    backend,
    archetype: Archetype,
    *,
    emphasis_index: int = 0,
    seen: Sequence[str] = (),
    known_names: Sequence[str] = (),
    context: str = "",
    max_attempts: int = DEFAULT_ATTEMPTS,
    nonce_factory=None,
) -> Generated:
    """Ask for a mandate, check it against the envelope, retry until it fits.

    Corrections are appended as real conversation turns — the model's own output
    as an `assistant` message and the specific violations as a `user` message —
    rather than restarting from a rewritten prompt. Same finding as the decision
    loop: models correct their own visible mistakes far more reliably than they
    avoid an abstract one described up front.
    """
    attempts = max(1, max_attempts)
    emphasis = archetype.emphases[emphasis_index % len(archetype.emphases)]
    nonce = nonce_factory() if nonce_factory else secrets.token_hex(4)
    conversation = archetype_messages(
        archetype, emphasis, nonce=nonce, context=context, avoid=known_names
    )
    rejections: list[str] = []
    duplicate: Mandate | None = None

    for attempt in range(1, attempts + 1):
        raw = await backend.complete(
            conversation, json_schema=archetype_schema(archetype), temperature=TEMPERATURE
        )
        try:
            mandate, problem = _parse_and_check(raw, archetype, seen)
        except (ExtractionError, ValidationError) as exc:
            problem, mandate = _schema_failure(exc), None

        if mandate is not None and problem is None:
            return Generated(
                mandate=mandate,
                archetype=archetype.key,
                emphasis=emphasis,
                emphasis_index=emphasis_index,
                attempts=attempt,
                rejections=rejections,
            )

        # A collision is the one failure whose product is still deployable, so
        # it is kept aside in case the attempts run out.
        if mandate is not None and signature(mandate) in seen:
            duplicate = mandate

        rejections.append(problem or "unknown")
        log.info(
            "archetype %s attempt %d/%d rejected: %s",
            archetype.key, attempt, attempts, problem,
        )
        if attempt == attempts:
            break
        conversation = [
            *conversation,
            {"role": "assistant", "content": (raw or "")[:1200]},
            {
                "role": "user",
                "content": (
                    f"That mandate was rejected. {problem}\n\n"
                    "Return the corrected mandate as a single JSON object only — "
                    "no explanation, no code fences."
                ),
            },
        ]

    if duplicate is not None:
        # Inside its bounds, just not new. Deploying a duplicate is a worse
        # demo than a distinct vault and a much better one than a button that
        # does nothing.
        log.warning(
            "archetype %s produced a duplicate strategy; deploying it anyway", archetype.key
        )
        return Generated(
            mandate=duplicate,
            archetype=archetype.key,
            emphasis=emphasis,
            emphasis_index=emphasis_index,
            attempts=attempts,
            rejections=rejections,
            collided=True,
        )

    raise GenerationFailed(archetype.key, attempts, rejections)


def _parse_and_check(
    raw: str, archetype: Archetype, seen: Sequence[str]
) -> tuple[Mandate | None, str | None]:
    """Parse one response and return it with the reason it cannot deploy."""
    payload = extract_json_object(raw, expect_key="name")
    # Assigned rather than trusted: the model is asked for 1, and a generated
    # mandate that claims to be version 7 would make the amendment trail read as
    # though six changes had already happened.
    payload["version"] = 1
    # Read before validating: pydantic fills a missing constraint from its own
    # default, so by the time a `Mandate` exists there is no way to tell "the
    # model chose 0.0" from "the model never mentioned it". Those need different
    # corrections — the first is a wrong number, the second is a missing field,
    # and telling a model its value is out of range when it never set one is how
    # a retry loop repeats itself four times without converging.
    supplied = payload.get("constraints")
    omitted = (
        sorted(set(archetype.constraint_ranges) - set(supplied))
        if isinstance(supplied, dict)
        else []
    )
    mandate = Mandate.model_validate(payload)

    if violations := check_envelope(mandate, archetype):
        detail = "; ".join(f"{v.field} {v.message}" for v in violations)
        problem = f"it escapes the archetype's bounds — {detail}"
        if named := [o for o in omitted if any(o in v.field for v in violations)]:
            problem += (
                f". You did not set {', '.join(named)} at all, so it took a default "
                f"outside the range — every constraint listed above must appear in "
                f"`constraints` with a value you chose."
            )
        return mandate, problem

    if unpriceable := _unpriceable(mandate):
        return mandate, (
            f"constraints.allowed_assets names {', '.join(unpriceable)}, which the vault "
            f"cannot price — its valuations read one Chainlink feed per token, cannot "
            f"compose, and are immutable after deployment. Choose from "
            f"{', '.join(offerable_assets())}."
        )

    if signature(mandate) in seen:
        return mandate, (
            "this is the same strategy as a vault this archetype already deployed. "
            "Choose a different point in the ranges — a different cash floor, a "
            "different venue mix, a different cooldown — and a different name."
        )

    return mandate, None


def _schema_failure(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        errors = exc.errors()[:4]
        detail = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or '<root>'}: {e['msg']}" for e in errors
        )
        return f"your JSON does not match the mandate schema — {detail}"
    return f"your response was not a single JSON object — {exc}"
