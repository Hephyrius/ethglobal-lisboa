"""Read an Aqua position back off-chain and decide whether it can actually be filled.

**This is the module that makes an Aqua ship verifiable.** Everything else in
this lane *builds* the transaction; this reads the result.

Why it exists: `Aqua.ship()` succeeds with zero allowance and returns a valid
strategy hash, so a successful transaction proves only that the registry
accepted some bytes.

**And `safeBalances()` alone does not close the gap** — cross-lane request 39,
from Lane B, correcting this module and the e2e plan's original R5 criterion.
The reasoning is our own finding 17 turned back on us: a ship with no approvals
produces a position with **non-zero `safeBalances`**, a valid hash, no error and
a successful tx, which is silently unfillable. So asserting `safeBalances` is
non-zero would *pass on a dead position* — worse than no check, because it
manufactures confidence in the 1inch centrepiece.

The observable that actually separates the two cases is the **ERC-20 allowance
from the vault to Aqua**: zero in the broken case, at least the shipped amount
in the good one. Aqua pulls against that allowance when a taker fills, so it is
the real precondition.

Hence two layers, and the naming keeps them apart:

* `read_position()` — virtual balances. *Liveness*: is the strategy active.
* `read_health()` / `assert_position_fillable()` — balances **and** allowances.
  *Fillability*: can a taker actually be served. **This is the R5 gate.**
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from eth_abi import decode as abi_decode

from .. import addresses
from ..abi import encode_call
from ..rpc import RpcClient, RpcError

#: Standard ERC-20. The allowance from the vault to Aqua is what decides
#: whether a shipped position can be filled — see the module docstring.
ERC20_ALLOWANCE: Final[str] = "allowance(address,address)"

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


async def read_allowance(rpc: RpcClient, *, token: str, owner: str) -> int:
    """How much of `token` Aqua may pull from `owner`.

    This is the number that decides whether a shipped position can be filled.
    Standard ERC-20 `allowance`, no Aqua ABI involved.
    """
    token = addresses.resolve_token(token)
    raw = await rpc.eth_call(
        token, encode_call(ERC20_ALLOWANCE, owner, addresses.AQUA)
    )
    if len(raw) < 2 + 64:
        return 0
    (value,) = abi_decode(["uint256"], bytes.fromhex(raw[2:]))
    return value


@dataclass(frozen=True, slots=True)
class PositionHealth:
    """Balances *and* allowances — everything needed to say whether a taker can
    actually be served."""

    balances: PositionBalances
    allowance_a: int
    allowance_b: int

    @property
    def fillable(self) -> bool:
        """Aqua can pull the full shipped amount on both sides."""
        return (
            self.balances.live
            and self.allowance_a >= self.balances.balance_a
            and self.allowance_b >= self.balances.balance_b
        )

    @property
    def dead(self) -> bool:
        """Shipped, looks healthy, and nothing can ever be pulled. The exact
        failure mode `safeBalances` cannot see."""
        return self.balances.live and (self.allowance_a == 0 or self.allowance_b == 0)

    def describe(self) -> str:
        if self.dead:
            state = "DEAD — approvals missing, nothing can fill this"
        elif self.fillable:
            state = "fillable"
        else:
            state = "partially fillable — allowance below the shipped amount"
        return (
            f"{self.balances.balance_a}/{self.balances.balance_b} shipped, "
            f"{self.allowance_a}/{self.allowance_b} approved ({state})"
        )


async def read_health(
    rpc: RpcClient,
    *,
    maker: str,
    strategy_hash: str,
    token_a: str,
    token_b: str,
    app: str = addresses.SWAPVM,
) -> PositionHealth | None:
    """Balances plus the allowances that make them mean something.

    `None` if the strategy is not active at all.
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
        return None

    return PositionHealth(
        balances=balances,
        allowance_a=await read_allowance(rpc, token=balances.token_a, owner=maker),
        allowance_b=await read_allowance(rpc, token=balances.token_b, owner=maker),
    )


async def assert_position_fillable(
    rpc: RpcClient,
    *,
    maker: str,
    strategy_hash: str,
    token_a: str,
    token_b: str,
    app: str = addresses.SWAPVM,
) -> PositionHealth:
    """**The R5 gate.** Raises unless a taker could actually be served.

    Checks the allowance, not just the balances, because a ship with no
    approvals leaves balances looking perfect (cross-lane requests 17 and 39).
    "The ship transaction succeeded" and "`safeBalances` is non-zero" are both
    true of a dead position.
    """
    health = await read_health(
        rpc,
        maker=maker,
        strategy_hash=strategy_hash,
        token_a=token_a,
        token_b=token_b,
        app=app,
    )

    if health is None:
        raise AssertionError(
            f"Aqua reports no active strategy {strategy_hash} for maker {maker}. "
            f"The ship transaction may have succeeded regardless — ship() does "
            f"not validate much. Check the strategy hash came from the ship() "
            f"return value, and that dock() has not since been called."
        )

    if not health.balances.live:
        raise AssertionError(
            f"Aqua strategy {strategy_hash} is active but holds "
            f"{health.balances.balance_a}/{health.balances.balance_b} — nothing "
            f"to trade against. The usual cause is shipping amounts of zero."
        )

    if health.dead:
        raise AssertionError(
            f"Aqua strategy {strategy_hash} looks healthy and is NOT fillable: "
            f"{health.describe()}. Aqua pulls from the maker's wallet on fill, "
            f"so a zero allowance means every fill reverts while the position "
            f"reports perfect balances. The plan's approve steps were dropped or "
            f"reordered — see cross-lane requests 17 and 39."
        )

    if not health.fillable:
        raise AssertionError(
            f"Aqua strategy {strategy_hash} is only partially fillable: "
            f"{health.describe()}. A taker can be served up to the allowance and "
            f"no further, so the position is smaller than it appears."
        )

    return health


async def assert_position_live(
    rpc: RpcClient,
    *,
    maker: str,
    strategy_hash: str,
    token_a: str,
    token_b: str,
    app: str = addresses.SWAPVM,
) -> PositionHealth:
    """Deprecated alias for `assert_position_fillable`.

    Kept because this name was published to other lanes before request 39
    established that balances alone prove nothing. It now performs the **full**
    check, so existing callers are strengthened rather than broken — the failure
    mode of leaving it as-is (silently weaker than its name implies) is exactly
    what the correction was about. Prefer `assert_position_fillable` in new code.
    """
    return await assert_position_fillable(
        rpc,
        maker=maker,
        strategy_hash=strategy_hash,
        token_a=token_a,
        token_b=token_b,
        app=app,
    )
