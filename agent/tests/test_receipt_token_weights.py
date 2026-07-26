"""A receipt token is not a position, in *both* weight functions.

`_exposure_symbol` exists because supplying USDC to Aave does not make the vault
less long USDC — it makes it long USDC *and* earning. Its docstring states the
consequence of getting this wrong:

    Without this a mandate allowing ["USDC", "WETH"] sees a vault holding 50% of
    an asset it never permitted, and every layer below fights a position that is
    exactly what the mandate asked for.

`_current_weights` applied it. `_projected_weights` did not, and nothing here
tested `represents` at all, so the two disagreed in silence for a whole wave.

**What that cost, observed on the live demo vault** (25,000 USDC total: 5,000
liquid, 20,000 supplied to Aave as aBasUSDC): layer 6 projected an *80% position
in aBasUSDC*, measured it against `max_position_pct = 0.6`, and rejected the
decision. Three attempts, the same rejection each time, `status="rejected"` with
no decision attached. And the rejection is unescapable by construction — the
breach is in the book, not in the trade, so a decision that *unwinds* it is
rejected on the same arithmetic as one that worsens it. Wave 2's whole point was
to get idle capital deployed into lending markets; doing so is what pushed the
vault past a ceiling it could then never come back under.

The two directions below are the test. The first is the bug. The second is the
one that must not be "fixed" along with it: folding must not make the projection
forget that a swap is sized against the *liquid* token balance.
"""

from __future__ import annotations

import json
import pathlib

from curator_schema import (
    AllocationDecision,
    Holding,
    Mandate,
    SupplyIntent,
    SwapIntent,
    TargetAllocation,
    VaultState,
    WithdrawIntent,
)

from agent.mandate.constraints import (
    _current_weights,
    _projected_weights,
    check_projected_outcome,
)

PRESETS = pathlib.Path(__file__).resolve().parents[2] / "packages" / "schema" / "presets"

USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
WETH = "0x4200000000000000000000000000000000000006"
ABASUSDC = "0x4e65fE4DbA92790696d040ac24Aa414708F5c0AB"

#: The live demo vault's shape: a fifth liquid, four fifths earning in Aave.
LIQUID = 5_000_000_000
SUPPLIED = 20_000_000_000
TOTAL = LIQUID + SUPPLIED


def _vault(*, paused: bool = False) -> VaultState:
    return VaultState(
        address="0xc90E6473df8371416c362D70fe2E6335E1c31414",
        asset=USDC,
        asset_decimals=6,
        total_assets=str(TOTAL),
        total_supply=str(TOTAL * 10**12),
        paused=paused,
        holdings=[
            Holding(
                token=USDC,
                symbol="USDC",
                balance=str(LIQUID),
                decimals=6,
                value_in_asset=str(LIQUID),
            ),
            Holding(
                token=ABASUSDC,
                symbol="aBasUSDC",
                # The chain client sets this; it is the entire mechanism.
                represents="USDC",
                balance=str(SUPPLIED),
                decimals=6,
                value_in_asset=str(SUPPLIED),
            ),
        ],
    )


def _mandate() -> Mandate:
    """The shipped preset the live demo vault runs — a 60% ceiling, 20% floor.

    Read from `packages/schema/presets/` rather than hand-built, so the limits
    under test are the ones a real vault actually carries.
    """
    preset = json.loads(
        (PRESETS / "balanced-two-asset.json").read_text(encoding="utf-8")
    )
    mandate = Mandate.model_validate(preset)
    assert mandate.constraints.max_position_pct == 0.6
    assert mandate.constraints.min_cash_pct == 0.2
    return mandate


def test_the_two_weight_functions_speak_the_same_language():
    """The invariant that was violated: a decision that moves nothing must
    project the book the vault already reports.

    Asserted as equality between the two functions rather than against literal
    numbers, because the failure was never a wrong number — it was two functions
    answering the same question in different symbol spaces.
    """
    vault = _vault()
    hold = AllocationDecision(action="hold", reasoning="Nothing worth doing.")

    assert _projected_weights(hold, vault) == _current_weights(vault)


def test_a_supplied_position_is_not_a_position_in_the_projection():
    """4/5 of the book sitting in Aave reads as USDC, not as 80% of `aBasUSDC`."""
    projected = _projected_weights(
        AllocationDecision(action="hold", reasoning="Nothing worth doing."), _vault()
    )

    assert projected == {"USDC": 1.0}
    assert "aBasUSDC" not in projected, (
        "the receipt token appeared as an exposure of its own — this is the shape that "
        "made layer 6 reject every decision on the demo vault"
    )


def test_the_aave_balance_is_no_longer_a_ceiling_breach():
    """The failure exactly as it happened, end to end through the layer.

    The vault's four fifths in Aave was reported as an 80% position in
    `aBasUSDC` against a 60% ceiling, on **every** decision — a breach in the
    book rather than in the trade, and therefore one no trade could cure.

    Asserted on the constraint rather than on an empty list, because this vault
    sits exactly on its cash floor and a `supply` that consumes free USDC
    *should* still be refused. Those are different objections and only one of
    them was a bug.
    """
    decision = AllocationDecision(
        action="rebalance",
        reasoning="Put the remaining idle USDC to work in the deepest lending market.",
        target_allocations=[TargetAllocation(asset="USDC", weight=1.0)],
        venue_intents=[SupplyIntent(asset="USDC", pct_of_holdings=0.5)],
    )

    violations = check_projected_outcome(decision, _mandate(), _vault())
    assert not [v for v in violations if v.constraint == "max_position_pct"], (
        "the receipt token is still being counted as a position of its own"
    )


def test_a_vault_at_its_floor_may_not_deploy_the_last_of_its_cash():
    """The other half of the same tick, and the reason the fold alone was not enough.

    Once receipt tokens fold into their underlying, a USDC vault reads as 100%
    USDC however much of it is locked in Aave — so a floor read off exposure can
    never bind, and `min_cash_pct` would silently stop protecting anything. The
    frozen schema is explicit that it is a floor on *unencumbered* base asset:
    "Protects withdrawal liquidity."

    This vault holds exactly its 20% floor in free USDC. Supplying half of that
    leaves 10%, and the depositor's ability to redeem is what the other 10% was.
    """
    supply_half = AllocationDecision(
        action="rebalance",
        reasoning="Put the remaining idle USDC to work.",
        target_allocations=[TargetAllocation(asset="USDC", weight=1.0)],
        venue_intents=[SupplyIntent(asset="USDC", pct_of_holdings=0.5)],
    )

    breaches = check_projected_outcome(supply_half, _mandate(), _vault())
    assert [v.constraint for v in breaches] == ["min_cash_pct"]
    assert breaches[0].actual == 0.1


def test_a_withdrawal_that_raises_cash_is_accepted():
    """The escape hatch has to exist, or the vault is stuck by a different door.

    A rule that judged every decision on pre-trade cash would reject the
    withdrawal that cures a shortfall — the same shape of unescapable rejection
    as the ceiling bug, pointed at the floor.
    """
    unwind = AllocationDecision(
        action="exit",
        reasoning="Pull half the Aave position back so redemptions stay comfortable.",
        target_allocations=[TargetAllocation(asset="USDC", weight=1.0)],
        venue_intents=[WithdrawIntent(asset="USDC", amount=str(SUPPLIED // 2))],
    )

    assert check_projected_outcome(unwind, _mandate(), _vault()) == []


def test_the_projection_still_sizes_a_swap_against_the_liquid_balance():
    """The half that must survive the fix.

    `UniswapVenue._resolve_amount` sizes `pct_of_holdings` against the balance of
    the *token itself*, so "100% of USDC" on this book moves the 5,000 liquid,
    not the 25,000 total. Folding before the arithmetic rather than after would
    have projected a swap five times the size the venue will actually build —
    which is the same class of mistake as the one being fixed, pointed the other
    way, and it would understate every ceiling breach a real swap causes.
    """
    projected = _projected_weights(
        AllocationDecision(
            action="rebalance",
            reasoning="Rotate the free cash into WETH.",
            target_allocations=[
                TargetAllocation(asset="USDC", weight=0.8),
                TargetAllocation(asset="WETH", weight=0.2),
            ],
            venue_intents=[
                SwapIntent(token_in="USDC", token_out="WETH", pct_of_holdings=1.0)
            ],
        ),
        _vault(),
    )

    assert projected is not None
    assert projected["WETH"] == LIQUID / TOTAL == 0.2
    assert projected["USDC"] == SUPPLIED / TOTAL == 0.8


def test_a_swap_that_really_would_breach_the_ceiling_is_still_caught():
    """The fix must not become an exemption.

    Same book, but the swap takes WETH past 60%. Sized in the input token this
    cannot happen from the liquid 20% alone, so the vault is given a book that
    can reach it — proof the ceiling still bites once the breach is genuinely
    caused by the trade rather than inherited from the book.
    """
    vault = VaultState(
        address="0xc90E6473df8371416c362D70fe2E6335E1c31414",
        asset=USDC,
        asset_decimals=6,
        total_assets=str(TOTAL),
        total_supply=str(TOTAL * 10**12),
        holdings=[
            Holding(
                token=USDC,
                symbol="USDC",
                balance=str(TOTAL),
                decimals=6,
                value_in_asset=str(TOTAL),
            )
        ],
    )
    breaching = AllocationDecision(
        action="rebalance",
        reasoning="Go long WETH with almost everything.",
        target_allocations=[
            TargetAllocation(asset="USDC", weight=0.1),
            TargetAllocation(asset="WETH", weight=0.9),
        ],
        venue_intents=[
            SwapIntent(token_in="USDC", token_out="WETH", pct_of_holdings=0.9)
        ],
    )

    violations = check_projected_outcome(breaching, _mandate(), vault)
    assert any(v.constraint == "max_position_pct" for v in violations), violations
    assert any(v.constraint == "min_cash_pct" for v in violations), violations
