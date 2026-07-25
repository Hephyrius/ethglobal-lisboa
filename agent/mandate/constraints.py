"""Checking a decision against what the mandate actually permits.

This is layer 3 of output validation, and the layer with teeth. A model can emit
perfectly schema-valid JSON that proposes buying an asset the mandate forbids,
allocating 140% of the vault, or firing six transactions when the mandate allows
two. The schema cannot catch any of that; only the mandate can.

Kept separate from `agent/model/validation.py` for two reasons: these rules are a
property of the *mandate*, not of model plumbing, and keeping them here means
they are testable without a model, a network or an event loop.

Every check returns *all* violations rather than raising on the first. The list
becomes the retry hint, and a model told about three problems at once fixes them
in one attempt instead of three.

## How `max_position_pct` and `min_cash_pct` are read

The golden fixtures settle an ambiguity that would otherwise be guesswork. The
golden mandate sets `max_position_pct: 0.6` and `min_cash_pct: 0.2`, and the
golden decision allocates USDC 0.7 / WETH 0.3 against `base_asset: "USDC"`.

Reading `max_position_pct` as a cap on *every* line would make the shared fixture
violate the shared mandate — so it is a cap on **risk positions**, meaning
allocations to assets other than the base asset. The base asset is the cash leg
and is governed by `min_cash_pct` from the other side. WETH 0.3 ≤ 0.6 and USDC
0.7 ≥ 0.2: consistent, and it matches what the two fields obviously mean.
"""

from __future__ import annotations

from dataclasses import dataclass

from curator_schema import AllocationDecision, ExecutionPlan, Mandate, VaultState

__all__ = [
    "Violation",
    "check_decision",
    "check_rebalance_direction",
    "check_projected_outcome",
    "check_plan",
    "describe",
]

#: Weights are model-generated decimals, so an exact sum to 1.0 is not a fair
#: requirement — three-way splits of 0.33 are correct in intent and 0.01 short in
#: arithmetic. One percentage point of slack costs nothing real and avoids
#: retrying a decision that is right.
WEIGHT_SUM_TOLERANCE = 0.01


@dataclass(frozen=True)
class Violation:
    """One breach, phrased so it can be handed straight back to the model."""

    field: str
    message: str

    def __str__(self) -> str:
        return f"{self.field}: {self.message}"


def describe(violations: list[Violation]) -> str:
    """Render violations as a retry instruction."""
    return "; ".join(str(v) for v in violations)


def check_decision(decision: AllocationDecision, mandate: Mandate) -> list[Violation]:
    """Every way this decision breaches its mandate."""
    problems: list[Violation] = []
    allowed = set(mandate.constraints.allowed_assets)
    problems += _check_allocations(decision, mandate, allowed)
    problems += _check_intents(decision, mandate, allowed)
    problems += _check_action_coherence(decision)
    return problems


def _check_allocations(
    decision: AllocationDecision, mandate: Mandate, allowed: set[str]
) -> list[Violation]:
    allocations = decision.target_allocations
    if not allocations:
        return []

    problems: list[Violation] = []
    limits = mandate.constraints

    unknown = sorted({a.asset for a in allocations} - allowed)
    if unknown:
        problems.append(
            Violation(
                "target_allocations",
                f"{', '.join(unknown)} not permitted; the mandate allows only "
                f"{', '.join(sorted(allowed))}",
            )
        )

    duplicates = sorted(
        {a.asset for a in allocations if sum(1 for b in allocations if b.asset == a.asset) > 1}
    )
    if duplicates:
        problems.append(
            Violation("target_allocations", f"{', '.join(duplicates)} appears more than once")
        )

    total = sum(a.weight for a in allocations)
    if abs(total - 1.0) > WEIGHT_SUM_TOLERANCE:
        problems.append(
            Violation("target_allocations", f"weights sum to {total:.4f}, but must sum to 1.0")
        )

    # Risk positions only — the base asset is the cash leg, capped from the
    # other side by min_cash_pct. See the module docstring.
    oversized = [
        a
        for a in allocations
        if a.asset != mandate.base_asset and a.weight > limits.max_position_pct
    ]
    for allocation in oversized:
        problems.append(
            Violation(
                "target_allocations",
                f"{allocation.asset} at {allocation.weight:.2%} exceeds the "
                f"{limits.max_position_pct:.0%} single-position ceiling",
            )
        )

    cash = sum(a.weight for a in allocations if a.asset == mandate.base_asset)
    if cash + WEIGHT_SUM_TOLERANCE < limits.min_cash_pct:
        problems.append(
            Violation(
                "target_allocations",
                f"holds {cash:.2%} in {mandate.base_asset} but the mandate requires at "
                f"least {limits.min_cash_pct:.0%} in cash",
            )
        )

    return problems


def _intent_assets(intent) -> list[str]:
    if intent.kind == "swap":
        return [intent.token_in, intent.token_out]
    if intent.kind == "ship":
        return list(intent.tokens)
    return []


def _check_intents(
    decision: AllocationDecision, mandate: Mandate, allowed: set[str]
) -> list[Violation]:
    intents = decision.venue_intents
    if not intents:
        return []

    problems: list[Violation] = []
    limits = mandate.constraints

    if len(intents) > limits.max_actions_per_tick:
        problems.append(
            Violation(
                "venue_intents",
                f"{len(intents)} actions requested but the mandate allows at most "
                f"{limits.max_actions_per_tick} per tick",
            )
        )

    permitted_venues = set(mandate.permitted_venues)
    used = {i.venue for i in intents}
    if forbidden := sorted(used - permitted_venues):
        problems.append(
            Violation(
                "venue_intents",
                f"venue {', '.join(forbidden)} not permitted; the mandate allows "
                f"{', '.join(sorted(permitted_venues))}",
            )
        )

    for position, intent in enumerate(intents):
        if unknown := sorted(set(_intent_assets(intent)) - allowed):
            problems.append(
                Violation(
                    f"venue_intents[{position}]",
                    f"{', '.join(unknown)} not in the mandate's allowed assets",
                )
            )
        if intent.kind == "swap":
            if intent.amount_in is None and intent.pct_of_holdings is None:
                problems.append(
                    Violation(
                        f"venue_intents[{position}]",
                        "a swap needs either amount_in or pct_of_holdings; neither was set",
                    )
                )
            if intent.token_in == intent.token_out:
                problems.append(
                    Violation(
                        f"venue_intents[{position}]",
                        f"cannot swap {intent.token_in} for itself",
                    )
                )
        elif intent.kind == "ship" and len(intent.tokens) != len(intent.amounts):
            problems.append(
                Violation(
                    f"venue_intents[{position}]",
                    f"{len(intent.tokens)} tokens but {len(intent.amounts)} amounts; "
                    "they must correspond one to one",
                )
            )

    return problems


def _check_action_coherence(decision: AllocationDecision) -> list[Violation]:
    """The stated action and the requested work must agree.

    Catches a real and expensive class of model error: a confident `rebalance`
    with nothing attached executes nothing while reporting that it acted, and a
    `hold` carrying swap intents would trade while claiming to have stood still.
    Either one makes the decision feed lie to the depositor.
    """
    intents = decision.venue_intents or []
    if decision.action == "hold" and intents:
        return [
            Violation(
                "action",
                f"action is 'hold' but {len(intents)} venue intent(s) were supplied; "
                "either hold and request nothing, or choose a different action",
            )
        ]
    if decision.action in {"rebalance", "enter", "exit"} and not intents:
        return [
            Violation(
                "action",
                f"action is '{decision.action}' but no venue_intents were supplied, so "
                "nothing would happen; supply intents or use 'hold'",
            )
        ]
    return []


#: Weights are noisy — a swap that closes a sub-percentage gap is not worth
#: rejecting, and rounding alone can flip the sign of a tiny difference.
_DIRECTION_TOLERANCE = 0.01


def _current_weights(vault: VaultState) -> dict[str, float]:
    """Each asset's share of the vault, by the vault's own valuation.

    Uses `value_in_asset` — the Chainlink figure `totalAssets()` is built from —
    so this agrees with the contract rather than with a second opinion. Holdings
    the vault could not price are omitted rather than counted as zero.
    """
    total = int(vault.total_assets or 0)
    if total <= 0:
        return {}
    return {
        h.symbol: int(h.value_in_asset) / total
        for h in vault.holdings
        if h.value_in_asset is not None
    }


def check_rebalance_direction(
    decision: AllocationDecision, vault: VaultState | None
) -> list[Violation]:
    """Every swap must move the vault *toward* its stated targets.

    Observed against the real model, and the reason this exists: shown a 70/30
    USDC/WETH book against a 50/50 target, it correctly wrote *"deviates from the
    target by more than the tolerance of 5 percentage points"* — and then swapped
    **WETH into USDC**, taking the book to 79/21. Right diagnosis, wrong
    direction, real money.

    Nothing else catches it. The intent is schema-valid, both assets are
    permitted, the weights sum to 1 and the action label matches the intent; the
    decision is internally consistent in every way except the one that matters.
    So this checks the sign: you may not sell an asset that is already below its
    target, nor buy one already above it.

    This is a property of the decision against reality, not of the mandate, so it
    holds whatever the mandate says.
    """
    intents = decision.venue_intents or []
    targets = {a.asset: a.weight for a in decision.target_allocations or []}
    if not intents or not targets or vault is None:
        return []

    current = _current_weights(vault)
    if not current:
        return []

    problems: list[Violation] = []
    for position, intent in enumerate(intents):
        if intent.kind != "swap":
            continue

        for symbol, side in ((intent.token_in, "sell"), (intent.token_out, "buy")):
            if symbol not in targets or symbol not in current:
                continue
            gap = targets[symbol] - current[symbol]  # positive => under target
            if abs(gap) <= _DIRECTION_TOLERANCE:
                continue

            if side == "sell" and gap > 0:
                problems.append(
                    Violation(
                        f"venue_intents[{position}]",
                        f"selling {symbol}, which is already at {current[symbol]:.1%} "
                        f"against a {targets[symbol]:.1%} target. Selling it moves the "
                        "vault further from your own target; swap the other way",
                    )
                )
            elif side == "buy" and gap < 0:
                problems.append(
                    Violation(
                        f"venue_intents[{position}]",
                        f"buying {symbol}, which is already at {current[symbol]:.1%} "
                        f"against a {targets[symbol]:.1%} target. Buying more moves the "
                        "vault further from your own target; swap the other way",
                    )
                )

    return problems


def _projected_weights(
    decision: AllocationDecision, vault: VaultState
) -> dict[str, float] | None:
    """Where the vault would end up if these swaps executed.

    Values are moved between assets at the current valuation, ignoring slippage
    and fees — those are basis points against limits expressed in whole
    percentage points, so they cannot change a verdict. `amount_in` is denominated
    in the *input token*, which this module cannot convert without a price, so a
    swap using it is not projected rather than guessed at.

    Returns None when the projection cannot be made honestly.
    """
    total = int(vault.total_assets or 0)
    if total <= 0:
        return None

    values = {
        h.symbol: float(int(h.value_in_asset))
        for h in vault.holdings
        if h.value_in_asset is not None
    }
    if not values:
        return None

    for intent in decision.venue_intents or []:
        if intent.kind != "swap":
            continue
        if intent.pct_of_holdings is None:
            return None  # sized in token units; cannot project without a price
        if intent.token_in not in values:
            return None
        moved = values[intent.token_in] * intent.pct_of_holdings
        values[intent.token_in] -= moved
        values[intent.token_out] = values.get(intent.token_out, 0.0) + moved

    return {asset: value / total for asset, value in values.items()}


def check_projected_outcome(
    decision: AllocationDecision, mandate: Mandate, vault: VaultState | None
) -> list[Violation]:
    """Validate where the trade *lands*, not just what it claims to want.

    Observed against the real model, and the reason this exists: on a 79/21
    USDC/WETH book against a 50/50 target it correctly identified the gap, chose
    the correct direction, and then sized the swap at `pct_of_holdings: 1.0`.
    That is every USDC in the vault. The result was **0% USDC / 100% WETH** —
    breaching both `min_cash_pct` (30%) and `max_position_pct` (60%), and
    overshooting the target it was aiming at by fifty percentage points.

    Every earlier layer passed it, and each was right to: the declared
    `target_allocations` were 50/50 and perfectly legal, the direction was
    correct, the assets were permitted, the facts were real. **The mandate limits
    were being checked against what the model said it wanted, never against what
    its trade would actually do.** Declared intent and realised effect are
    different things, and only the second one spends money.

    So the swaps are projected forward and the *result* is checked: the mandate's
    cash floor and position ceiling must survive, and the book must end closer to
    its target than it started.
    """
    projected = _projected_weights(decision, vault) if vault is not None else None
    if projected is None:
        return []

    limits = mandate.constraints
    problems: list[Violation] = []

    cash = projected.get(mandate.base_asset, 0.0)
    if cash + WEIGHT_SUM_TOLERANCE < limits.min_cash_pct:
        problems.append(
            Violation(
                "venue_intents",
                f"this trade would leave {cash:.1%} in {mandate.base_asset}, below the "
                f"{limits.min_cash_pct:.0%} cash floor. Sell less",
            )
        )

    for asset, weight in sorted(projected.items()):
        if asset == mandate.base_asset:
            continue
        if weight > limits.max_position_pct + WEIGHT_SUM_TOLERANCE:
            problems.append(
                Violation(
                    "venue_intents",
                    f"this trade would take {asset} to {weight:.1%}, above the "
                    f"{limits.max_position_pct:.0%} single-position ceiling. Buy less",
                )
            )

    # Overshooting is its own failure: a trade can respect every limit and still
    # sail past the target it was sized to reach.
    #
    # Only assets that were *already materially off* target are judged, matching
    # layer 5's threshold. The rule being enforced is "if you claim to be closing
    # a gap, close it" — where there is no gap the model is expressing a view
    # rather than correcting a drift, and the floor and ceiling above still bound
    # where it can land. The shared golden fixture is exactly that case: it
    # declares a 70/30 target on a book already at 70/30 and then trades, which
    # is legal but not a correction.
    targets = {a.asset: a.weight for a in decision.target_allocations or []}
    current = _current_weights(vault)
    for asset, target in targets.items():
        if asset not in projected or asset not in current:
            continue
        before, after = abs(current[asset] - target), abs(projected[asset] - target)
        if before <= _DIRECTION_TOLERANCE:
            continue
        if after > before + _DIRECTION_TOLERANCE:
            problems.append(
                Violation(
                    "venue_intents",
                    f"this trade moves {asset} from {current[asset]:.1%} to {projected[asset]:.1%} "
                    f"against a {target:.1%} target, ending further away than it started. "
                    "Size the swap to land on the target",
                )
            )

    return problems


def check_plan(plan: ExecutionPlan, mandate: Mandate) -> list[Violation]:
    """Check a venue's execution plan before it is submitted.

    Slippage is the mandate constraint that can only be evaluated here: the
    decision expresses intent, and only the venue knows the price impact of
    filling it.
    """
    limits = mandate.constraints
    if (
        plan.expected_slippage_bps is not None
        and plan.expected_slippage_bps > limits.max_slippage_bps
    ):
        return [
            Violation(
                "expected_slippage_bps",
                f"plan expects {plan.expected_slippage_bps}bps of slippage but the "
                f"mandate ceiling is {limits.max_slippage_bps}bps",
            )
        ]
    return []
