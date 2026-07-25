"""Read an Aqua position's virtual balances back off-chain.

**This is the module that makes an Aqua ship verifiable.** Everything else in
this lane *builds* the transaction; this reads the result.

Why it exists as its own thing: `Aqua.ship()` succeeds with zero allowance and
returns a valid strategy hash, so a successful transaction proves only that the
registry accepted some bytes. The position may be live, or it may be an
accounting entry nothing can ever fill (cross-lane request 17). The only
observable that distinguishes them is `safeBalances()`.

Rung R5 of the e2e plan asserts exactly this, and deliberately: *"a successful
tx is not evidence here — the balance assertion is the whole rung."*
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from eth_abi import decode as abi_decode

from .. import addresses
from ..abi import encode_call
from ..rpc import RpcClient, RpcError

#: `safeBalances` REVERTS when a token is not part of an active strategy,
#: rather than returning zero. That is a useful property — it distinguishes
#: "docked or never shipped" from "shipped with nothing in it" — so the revert
#: is caught and mapped to `None` instead of being treated as an error.
AQUA_SAFE_BALANCES: Final[str] = (
    "safeBalances(address,address,bytes32,address,address)"
)

#: Balance-per-token without the active-strategy check. Returns zeros rather
#: than reverting, so it cannot distinguish docked from empty — prefer
#: `safeBalances` and use this only to inspect a single token.
AQUA_RAW_BALANCES: Final[str] = "rawBalances(address,address,bytes32,address)"


@dataclass(frozen=True, slots=True)
class PositionBalances:
    """What a taker can actually fill against.

    `live` is the assertion R5 needs: the strategy is active *and* holds
    non-zero balances on both sides.
    """

    token_a: str
    token_b: str
    balance_a: int
    balance_b: int

    @property
    def live(self) -> bool:
        return self.balance_a > 0 and self.balance_b > 0

    def describe(self) -> str:
        return (
            f"{self.balance_a} {self.token_a[:10]}… / "
            f"{self.balance_b} {self.token_b[:10]}… "
            f"({'fillable' if self.live else 'NOT fillable'})"
        )


async def read_position(
    rpc: RpcClient,
    *,
    maker: str,
    strategy_hash: str,
    token_a: str,
    token_b: str,
    app: str = addresses.SWAPVM,
) -> PositionBalances | None:
    """Virtual balances for one shipped strategy, or `None` if it is not active.

    `maker` is the vault. `None` means the strategy has been docked, was never
    shipped, or does not cover these tokens — all of which present identically
    from outside, and all of which mean "nothing can fill this".

    Distinguish carefully: `None` is *not* an error, and a returned object with
    zero balances is a different (worse) state — shipped, active, and empty.
    """
    token_a = addresses.resolve_token(token_a)
    token_b = addresses.resolve_token(token_b)
    calldata = encode_call(
        AQUA_SAFE_BALANCES, maker, app, bytes.fromhex(strategy_hash[2:]), token_a, token_b
    )

    try:
        raw = await rpc.eth_call(addresses.AQUA, calldata)
    except RpcError:
        # The documented revert for a non-active strategy. Any other RPC
        # failure looks the same from here, which is the cost of not parsing
        # revert data — acceptable because the caller's next move (treat the
        # position as not live) is identical either way.
        return None

    if len(raw) < 2 + 128:  # two uint256 words
        return None

    balance_a, balance_b = abi_decode(["uint256", "uint256"], bytes.fromhex(raw[2:]))
    return PositionBalances(
        token_a=token_a, token_b=token_b, balance_a=balance_a, balance_b=balance_b
    )


async def assert_position_live(
    rpc: RpcClient,
    *,
    maker: str,
    strategy_hash: str,
    token_a: str,
    token_b: str,
    app: str = addresses.SWAPVM,
) -> PositionBalances:
    """`read_position`, but raises with a diagnosis instead of returning `None`.

    For tests and the e2e suite, where "the ship transaction succeeded" must not
    be allowed to stand in for "the position exists".
    """
    balances = await read_position(
        rpc,
        maker=maker,
        strategy_hash=strategy_hash,
        token_a=token_a,
        token_b=token_b,
        app=app,
    )

    if balances is None:
        raise AssertionError(
            f"Aqua reports no active strategy {strategy_hash} for maker {maker}. "
            f"The ship transaction may have succeeded regardless — ship() does "
            f"not validate much. Check the strategy hash came from the ship() "
            f"return value, and that dock() has not since been called."
        )

    if not balances.live:
        raise AssertionError(
            f"Aqua strategy {strategy_hash} is active but holds "
            f"{balances.balance_a}/{balances.balance_b} — nothing can fill it. "
            f"The usual cause is shipping with amounts of zero; note that a "
            f"missing ERC-20 approval does NOT cause this (it leaves balances "
            f"intact and fails only at fill time — see cross-lane request 17)."
        )

    return balances
