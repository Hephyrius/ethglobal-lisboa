"""Decode the revert selectors an `ExecutionPlan` can produce.

**Why this exists.** R5 failed for hours with `ContractCustomError 0x39d35496`
and nobody could identify it. The search was thorough — 426 error signatures
hashed across the deployed vault ABIs, all of OpenZeppelin, and every one of the
307 errors in the vendored `@1inch/{aqua,swap-vm,solidity-utils}` — and it found
nothing, which led to the reasonable but wrong conclusion that the revert came
from deployed 1inch bytecode whose source we lack.

It was `V3TooLittleReceived()`, from Uniswap's UniversalRouter. Aqua was never
involved.

The lesson is that **a plan touches contracts from several protocols, so the
error can come from any of them**, and the one place that knows which contracts
a plan touches is the lane that built it. Hence this table lives here.

Each entry says what happened, and what to do — a selector alone is a lookup
task for whoever hits it at 3am.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from eth_utils import keccak


@dataclass(frozen=True, slots=True)
class KnownRevert:
    selector: str
    signature: str
    source: str
    meaning: str
    fix: str

    def describe(self) -> str:
        return (
            f"{self.signature} (0x{self.selector}) from {self.source}\n"
            f"  what it means: {self.meaning}\n"
            f"  what to do:    {self.fix}"
        )


def _entry(signature: str, source: str, meaning: str, fix: str) -> KnownRevert:
    return KnownRevert(keccak(text=signature)[:4].hex(), signature, source, meaning, fix)


#: Selectors a plan from this lane can realistically produce. Keyed by the
#: 4-byte selector without `0x`.
KNOWN_REVERTS: Final[dict[str, KnownRevert]] = {
    r.selector: r
    for r in (
        _entry(
            "V3TooLittleReceived()",
            "Uniswap UniversalRouter (V3 leg)",
            "the swap produced less output than the transaction's minimum, so it "
            "reverted rather than fill at a worse price",
            "On MAINNET this is real market movement — re-quote and retry; the quote "
            "went stale. On a PINNED FORK it is almost always fork staleness instead: "
            "the Trading API prices against live Base while the fork executes at a "
            "block hours behind, so the minimum is computed for a market the fork "
            "cannot deliver. Measured on this stack: 15.5h of drift = 72 bps of price "
            "gap against a 50 bps band. Raise UNISWAP_SLIPPAGE_BPS for fork runs, or "
            "re-fork nearer head. See venues/README.md.",
        ),
        _entry(
            "V4TooLittleReceived(uint256,uint256)",
            "Uniswap UniversalRouter (V4 leg)",
            "the V4 leg of a split route produced less than its minimum; the two "
            "arguments are (minimum, actual)",
            "Same causes as V3TooLittleReceived — real movement on mainnet, fork "
            "staleness on a pinned fork. Note routes mix V3 and V4 legs, so which "
            "of the two errors you see depends on the route the API chose that "
            "minute, not on anything you changed. Raise UNISWAP_SLIPPAGE_BPS for "
            "fork runs or re-fork nearer head.",
        ),
        _entry(
            "TransactionDeadlinePassed()",
            "Uniswap UniversalRouter",
            "the router's deadline elapsed before the transaction mined",
            "Quotes carry a short deadline. On a fork whose timestamp has advanced "
            "past the quote, re-quote immediately before submitting.",
        ),
        _entry(
            "InsufficientToken()",
            "Uniswap UniversalRouter",
            "the router held less of the input token than the plan assumed",
            "Usually a missing or insufficient approval step — check the plan still "
            "carries both the ERC-20 approve and the Permit2 approve, in that order.",
        ),
        _entry(
            "AllowanceExpired(uint256)",
            "Permit2",
            "the Permit2 allowance expired before the swap executed",
            "Plans set a 30-minute Permit2 expiry. If the fork's clock has jumped, "
            "rebuild the plan rather than resubmitting the old calldata.",
        ),
        _entry(
            "InsufficientAllowance(uint256)",
            "Permit2",
            "Permit2 was not approved for enough of the input token",
            "The plan's second step grants this. It must not be dropped or reordered.",
        ),
        _entry(
            "SafeBalancesForTokenNotInActiveStrategy(address,address,bytes32,address)",
            "1inch Aqua",
            "the strategy is not active for that token — docked, never shipped, or "
            "the token is not part of it",
            "Check the strategy hash came from the ship() return value. "
            "`venues.aqua.read_position` returns None for exactly this case.",
        ),
        _entry(
            "StrategiesMustBeImmutable(address,bytes32)",
            "1inch Aqua",
            "a strategy with that hash already exists and cannot be re-shipped",
            "Salts are derived from vault state, so re-shipping an identical position "
            "collides by design. Dock first, or change the fee/pair.",
        ),
        _entry(
            "TargetNotAllowed(address)",
            "CuratedVault (Lane A)",
            "execute() refused a target that is not on the vault's allowlist",
            "`addresses.allowlist()` reads the deployment manifest; the deployed "
            "vault is authoritative. If a venue was added recently, its contracts "
            "need registering and a NEW vault created — valuations and targets are "
            "set at deploy time.",
        ),
    )
}


def normalise(selector: str) -> str:
    """Accept `0x39d35496`, `39d35496`, or full revert data."""
    cleaned = selector.lower().removeprefix("0x")
    return cleaned[:8]


def explain(selector: str) -> KnownRevert | None:
    """Identify a revert selector, or None if this lane does not know it."""
    return KNOWN_REVERTS.get(normalise(selector))


def describe(selector: str) -> str:
    """Always returns something useful — including when the selector is unknown,
    because "not one of ours" is itself worth knowing and narrows the search."""
    known = explain(selector)
    if known:
        return known.describe()
    return (
        f"0x{normalise(selector)} is not a revert this lane's plans produce.\n"
        f"  Next step: extract PUSH4 selectors from `eth_getCode` on each contract "
        f"the transaction touched to find which one raises it, and try "
        f"4byte.directory — that is how V3TooLittleReceived was identified after "
        f"426 local signatures failed to match."
    )
