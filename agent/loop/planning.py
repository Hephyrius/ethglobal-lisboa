"""Turning validated venue intents into one executable plan.

Sits between the decision and the chain. The decision says *what* to do in the
agent's terms ("swap 30% of holdings from USDC to WETH"); Lane D's venue adapters
turn that into calldata; this module drives them, applies the mandate limits that
can only be evaluated once a quote exists, and produces the single
`ExecutionPlan` the vault executes and the feed displays.

## Why the plans are merged

`AgentAction.plan` is one `ExecutionPlan`, but a mandate may allow several venue
intents per tick (`max_actions_per_tick`). Merging is the honest reading rather
than a workaround: the vault executes a flat, ordered sequence of
`execute(target, value, data)` calls, so "the plan for this tick" genuinely *is*
the concatenation of its parts. Step order is preserved, which matters because
approvals must precede the calls that need them.

The merged plan reports the **worst** expected slippage and the **earliest** quote
expiry of its parts, because both are the constraint that actually binds.
"""

from __future__ import annotations

import logging

from curator_schema import (
    AllocationDecision,
    ExecutionPlan,
    Mandate,
    VaultState,
    VenueIntent,
)

from ..clock import utcnow
from ..mandate.constraints import check_plan, describe

__all__ = ["PlanRejected", "build_execution_plan", "merge_plans"]

log = logging.getLogger(__name__)

#: `ExecutionPlan.expected_effect` is capped in the frozen schema.
_EFFECT_LIMIT = 500


class PlanRejected(Exception):
    """A plan was refused before submission. Nothing was executed."""


def _lookup_venue(registry, key: str):
    """Find a venue by key without assuming Lane D's registry shape.

    Three shapes are accepted, because all three are reasonable ways to publish
    a registry and none is worth a cross-lane request:

    - a mapping, or anything exposing `.get(key)` — `{"uniswap": venue}`
    - a lookup **function**, `get_venue(key)` — which is what Lane D publishes
    - an object carrying venues as attributes

    A lookup that raises for an unknown key (Lane D's `UnknownVenueError`) is
    treated as "not found", so the caller reports the missing adapter rather
    than leaking another lane's exception type. The venue itself is duck-typed
    against `curator_schema.ports.Venue` at the point of use.
    """
    if registry is None:
        return None

    getter = getattr(registry, "get", None)
    if callable(getter):
        try:
            if (venue := getter(key)) is not None:
                return venue
        except Exception:  # noqa: BLE001 - an unknown key is "not found", not a crash
            return None

    # A bare callable registry is a lookup function.
    if callable(registry) and not isinstance(registry, type):
        try:
            return registry(key)
        except Exception:  # noqa: BLE001
            return None

    return getattr(registry, key, None)


async def _plan_one(intent: VenueIntent, vault: VaultState, registry) -> ExecutionPlan:
    venue = _lookup_venue(registry, intent.venue)
    if venue is None:
        raise PlanRejected(
            f"the mandate permits venue {intent.venue!r} but no adapter is registered for it"
        )
    try:
        return await venue.plan(intent, vault)
    except Exception as exc:  # noqa: BLE001 - a venue failure is a rejected tick, not a crash
        raise PlanRejected(f"venue {intent.venue!r} could not build a plan: {exc}") from exc


def merge_plans(plans: list[ExecutionPlan]) -> ExecutionPlan:
    """Flatten several venue plans into the one the vault will execute."""
    if len(plans) == 1:
        return plans[0]

    slippages = [p.expected_slippage_bps for p in plans if p.expected_slippage_bps is not None]
    expiries = [p.quote_expires_at for p in plans if p.quote_expires_at is not None]
    effects = "; ".join(p.expected_effect for p in plans if p.expected_effect)

    return ExecutionPlan(
        venue="+".join(sorted({p.venue for p in plans})),
        steps=[step for plan in plans for step in plan.steps],
        expected_effect=effects[:_EFFECT_LIMIT] or None,
        expected_slippage_bps=max(slippages) if slippages else None,
        quote_expires_at=min(expiries) if expiries else None,
    )


#: Intents that *free* tokens must precede intents that spend them. An Aqua
#: position is encumbered rather than absent — the tokens sit in the vault with a
#: claim recorded against them — and a lending position is held as a receipt
#: token, so in both cases a swap of the underlying reverts until the position is
#: released. Lower sorts first.
_RELEASE_FIRST = {"dock": 0, "withdraw": 0}
_THEN_EVERYTHING_ELSE = 1


def _ordered(intents: list[VenueIntent]) -> list[VenueIntent]:
    """Free encumbered tokens before selling them, preserving order otherwise.

    Matters most during a wind-down, where the natural decision is *dock the Aqua
    position and sell what it was holding* — and a model that lists those in the
    order it thought of them produces a batch that reverts on the swap. The whole
    plan goes to chain as one `executeBatch`, so getting this wrong costs the
    entire tick rather than one step.

    A stable sort, so within each group the agent's own sequencing survives. This
    reorders **what already passed validation** and never adds, drops or resizes
    anything: the agent still chooses the route and the size.
    """
    return sorted(
        intents, key=lambda i: _RELEASE_FIRST.get(i.kind, _THEN_EVERYTHING_ELSE)
    )


async def build_execution_plan(
    decision: AllocationDecision,
    mandate: Mandate,
    vault: VaultState,
    registry,
) -> ExecutionPlan:
    """Build, check and merge the plans for a decision's intents.

    Raises `PlanRejected` — never returns a plan the mandate forbids.
    """
    intents = _ordered(decision.venue_intents or [])
    if not intents:
        raise PlanRejected("decision requested an action but carried no venue intents")

    plans = [await _plan_one(intent, vault, registry) for intent in intents]
    merged = merge_plans(plans)

    # Slippage can only be judged once a venue has quoted — the decision
    # expresses intent, the venue knows the price impact of filling it.
    if violations := check_plan(merged, mandate):
        raise PlanRejected(describe(violations))

    # A router quote that has expired must not be submitted
    # (`curator_schema.ports.Venue`). Better a rejected tick than a swap filled
    # at a price nobody agreed to.
    if merged.quote_expires_at is not None and merged.quote_expires_at <= utcnow():
        raise PlanRejected(
            f"the venue quote expired at {merged.quote_expires_at.isoformat()}; "
            "not submitting a stale quote"
        )

    log.info("plan ready: %d step(s) across %s", len(merged.steps), merged.venue)
    return merged
