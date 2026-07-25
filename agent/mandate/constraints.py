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

from curator_schema import (
    AllocationDecision,
    ConstraintWarning,
    ExecutionPlan,
    Mandate,
    VaultState,
)

__all__ = [
    "Violation",
    "check_decision",
    "check_rebalance_direction",
    "check_projected_outcome",
    "check_plan",
    "describe",
    "apply_band",
    "banded_warnings",
    "BANDABLE",
]

#: Weights are model-generated decimals, so an exact sum to 1.0 is not a fair
#: requirement — three-way splits of 0.33 are correct in intent and 0.01 short in
#: arithmetic. One percentage point of slack costs nothing real and avoids
#: retrying a decision that is right.
WEIGHT_SUM_TOLERANCE = 0.01


#: The only constraints the tolerance band may bend, and the reason each one
#: qualifies: they are **aims**, so landing at 61% against a 60% cap is the
#: rounding artefact of a swap that priced a hair differently, not a breach of
#: intent.
#:
#: Everything absent from this set is outside the band **by design**, and the
#: omissions carry more weight than the inclusions:
#:
#: - `max_slippage_bps` — a ceiling that was already compared against a bound
#:   rather than an estimate (#33). Banding it means paying 5% more than the
#:   mandate's stated maximum cost, silently.
#: - `allowed_assets`, `permitted_venues`, `permitted_data_sources` — not
#:   numeric. There is no "5% of an asset that is not permitted".
#: - `max_actions_per_tick`, `rebalance_cooldown_seconds` — anti-churn limits.
#:   A band on those is just a bigger limit.
BANDABLE = frozenset({"max_position_pct", "min_cash_pct", "target_allocation"})


@dataclass(frozen=True)
class Violation:
    """One breach, phrased so it can be handed straight back to the model.

    The numeric fields are what let a breach be *banded* rather than rejected.
    A violation that cannot state its limit and its actual value is never
    banded, whatever its name — the band has to be measurable to be applied,
    and guessing the magnitude of a breach in order to forgive it is worse than
    rejecting it.
    """

    field: str
    message: str
    #: The `MandateConstraints` field that bent, or "target_allocation" for
    #: drift. `None` means this violation is not a candidate for the band.
    constraint: str | None = None
    #: Asset symbol when the constraint is per-asset.
    subject: str | None = None
    #: The mandate's own value, and the value that breached it.
    limit: float | None = None
    actual: float | None = None

    def __str__(self) -> str:
        return f"{self.field}: {self.message}"

    @property
    def bandable(self) -> bool:
        return (
            self.constraint in BANDABLE
            and self.limit is not None
            and self.actual is not None
        )

    def overage(self) -> float | None:
        """How far past the limit, as a fraction of the limit.

        Relative rather than absolute: a 1pp overshoot on a 60% cap is a 1.7%
        miss, while the same point on a 5% floor is a 20% one, and a band
        expressed in percent has to mean the same thing in both.
        """
        if self.limit is None or self.actual is None:
            return None
        if self.limit == 0:
            # No proportion of zero. A floor of zero cannot be breached, and a
            # cap of zero admits no band at all.
            return None if self.actual == 0 else float("inf")
        return abs(self.actual - self.limit) / abs(self.limit)


def apply_band(
    violations: list[Violation], mandate: Mandate
) -> tuple[list[Violation], list[ConstraintWarning]]:
    """Split breaches into those that still reject and those the band forgives.

    Wave 2 §3.1: *"make the rules less rigid — violation allowed within a
    threshold of mandate ±5%."* The danger is that "less rigid" becomes "no
    rules", so three things hold:

    - Only `BANDABLE` constraints bend. See that set for why each omission is an
      omission and not an oversight.
    - The overage is measured **against the mandate**, never against last tick.
      Comparing to the previous state is what lets a ratchet walk the book away
      from its mandate 5% at a time without ever tripping a rejection.
    - Every forgiveness produces a `ConstraintWarning`, so a banded acceptance
      reaches the action, the feed and the reflection. A band nobody can see is
      indistinguishable from no rule at all.
    """
    band = mandate.constraints.tolerance_band_pct
    if band <= 0:
        return violations, []

    hard: list[Violation] = []
    warnings: list[ConstraintWarning] = []

    for violation in violations:
        overage = violation.overage() if violation.bandable else None
        if overage is None or overage > band:
            hard.append(violation)
            continue

        warnings.append(
            ConstraintWarning(
                constraint=violation.constraint,
                subject=violation.subject,
                limit=violation.limit,
                actual=violation.actual,
                band_pct=band,
                message=(
                    f"{violation.constraint} bent by {overage:.1%} of its limit "
                    f"({violation.actual:.2%} against {violation.limit:.2%}), inside the "
                    f"{band:.0%} tolerance band. Accepted, and still steering back."
                )[:300],
            )
        )

    return hard, warnings


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
                constraint="max_position_pct",
                subject=allocation.asset,
                limit=limits.max_position_pct,
                actual=allocation.weight,
            )
        )

    cash = sum(a.weight for a in allocations if a.asset == mandate.base_asset)
    if cash + WEIGHT_SUM_TOLERANCE < limits.min_cash_pct:
        problems.append(
            Violation(
                "target_allocations",
                f"holds {cash:.2%} in {mandate.base_asset} but the mandate requires at "
                f"least {limits.min_cash_pct:.0%} in cash",
                constraint="min_cash_pct",
                subject=mandate.base_asset,
                limit=limits.min_cash_pct,
                actual=cash,
            )
        )

    return problems


def _intent_assets(intent) -> list[str]:
    if intent.kind == "swap":
        return [intent.token_in, intent.token_out]
    if intent.kind == "ship":
        return list(intent.tokens)
    if intent.kind in {"supply", "withdraw"}:
        # Named as the UNDERLYING, never the aToken. The mandate grants "USDC",
        # and supplying it is still a USDC decision — requiring the mandate to
        # also list "aBasUSDC" would leak a protocol's receipt-token naming into
        # a document a human wrote.
        return [intent.asset]
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
        elif intent.kind == "supply":
            if intent.amount is None and intent.pct_of_holdings is None:
                problems.append(
                    Violation(
                        f"venue_intents[{position}]",
                        "a supply needs either amount or pct_of_holdings; neither was set",
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


#: Intent kinds that change what the vault is *exposed to*.
#:
#: A supply moves USDC into aUSDC and a ship posts a balance as liquidity;
#: neither changes how long the vault is any asset. Only a swap does. The
#: distinction matters because the target-closing rule below asks "if you claim
#: to be closing an allocation gap, close it" — a question that is incoherent
#: for an intent that was never about allocation.
_EXPOSURE_MOVING_KINDS = {"swap"}


def _exposure_symbol(holding) -> str:
    """The symbol a holding should be weighed under.

    A receipt token is not a new exposure: supplying USDC to Aave does not make
    the vault less long USDC, it makes it long USDC *and* earning. So aBasUSDC
    weighs as USDC, via `Holding.represents`, which the chain client sets.

    Without this a mandate allowing ["USDC", "WETH"] sees a vault holding 50% of
    an asset it never permitted, and every layer below fights a position that is
    exactly what the mandate asked for.
    """
    return holding.represents or holding.symbol


def _current_weights(vault: VaultState) -> dict[str, float]:
    """Each asset's share of the vault, by the vault's own valuation.

    Uses `value_in_asset` — the Chainlink figure `totalAssets()` is built from —
    so this agrees with the contract rather than with a second opinion. Holdings
    the vault could not price are omitted rather than counted as zero.

    Receipt tokens are folded into their underlying (`_exposure_symbol`), so a
    vault holding 500 USDC and 500 aBasUSDC reads as 100% USDC — which is what
    it is.
    """
    total = int(vault.total_assets or 0)
    if total <= 0:
        return {}

    weights: dict[str, float] = {}
    for holding in vault.holdings:
        if holding.value_in_asset is None:
            continue
        symbol = _exposure_symbol(holding)
        weights[symbol] = weights.get(symbol, 0.0) + int(holding.value_in_asset) / total
    return weights


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
                constraint="min_cash_pct",
                subject=mandate.base_asset,
                limit=limits.min_cash_pct,
                actual=cash,
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
                    constraint="max_position_pct",
                    subject=asset,
                    limit=limits.max_position_pct,
                    actual=weight,
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
    # Only judged when the decision actually moves exposure. A supply or a ship
    # leaves every weight exactly where it was, so `after == before` for every
    # asset — and without this gate the rule below would reject *every* deploy
    # into a lending market on any vault not already sitting precisely on its
    # target. The rule is "if you claim to be closing a gap, close it"; an
    # intent that was never about allocation makes no such claim.
    moves_exposure = any(
        intent.kind in _EXPOSURE_MOVING_KINDS for intent in decision.venue_intents or []
    )
    if not moves_exposure:
        return problems

    targets = {a.asset: a.weight for a in decision.target_allocations or []}
    current = _current_weights(vault)
    for asset, target in targets.items():
        if asset not in projected or asset not in current:
            continue
        before, after = abs(current[asset] - target), abs(projected[asset] - target)
        # The trade must *close* the gap. Two earlier versions of this rule were
        # each too weak, and each was caught by a real trade rather than by
        # reasoning:
        #
        #   "reject if it gets worse"      let a 50pp-under book swing to 50pp
        #                                  over — the same distance, mirrored.
        #   "...unless already on target"  let a book sitting exactly on 50/50
        #                                  liquidate 100% of one leg, because a
        #                                  zero starting gap skipped the check
        #                                  and 100/0 breaches no floor or cap.
        #
        # The second exemption existed to let the golden fixture pass, which
        # pairs a 70/30 target with a 70/30 book and then trades. That pairing is
        # simply incoherent — `target_allocations` is *where you want the vault
        # to be*, so trading away from it means the stated target is not the
        # target. There is no legitimate case for it, so there is no exemption.
        if after >= before - _DIRECTION_TOLERANCE:
            problems.append(
                Violation(
                    "venue_intents",
                    f"this trade moves {asset} from {current[asset]:.1%} to {projected[asset]:.1%} "
                    f"against a {target:.1%} target, which is no closer than it started "
                    f"({before:.1%} away before, {after:.1%} after). Size the swap to land "
                    "on the target",
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


def banded_warnings(
    decision: AllocationDecision, mandate: Mandate, vault: VaultState | None
) -> list[ConstraintWarning]:
    """Every constraint this decision bent and was forgiven for.

    Recomputed after validation rather than threaded out of it. The checks are
    pure functions over data the caller already holds, so a second pass costs
    nothing measurable and keeps `validate_decision`'s signature — which several
    dozen tests and the whole retry loop are written against.
    """
    _, from_targets = apply_band(check_decision(decision, mandate), mandate)
    _, from_outcome = apply_band(check_projected_outcome(decision, mandate, vault), mandate)
    return [*from_targets, *from_outcome]
