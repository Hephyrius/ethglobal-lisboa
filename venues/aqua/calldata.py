"""`ship()` / `dock()` calldata for the Aqua registry.

Signatures taken from 1inch's `IAqua`:

    ship(address app, bytes strategy, address[] tokens, uint256[] amounts)
        returns (bytes32 strategyHash)
    dock(address app, bytes32 strategyHash, address[] tokens)

`app` is the SwapVM contract — the "app" Aqua permits to pull against the
strategy's virtual balances.

**Nothing here moves capital.** `ship()` records
`balances[maker][app][strategyHash][token]` while the tokens remain in the
maker's wallet — the vault. That is what makes a live market-making position
compatible with our locked Pattern 1 custody decision, and it is why `ship()`
takes amounts but no transfer.
"""

from __future__ import annotations

from typing import Final

from curator_schema.models import ExecutionStep

from .. import addresses
from ..abi import ERC20_APPROVE, encode_call

AQUA_SHIP: Final[str] = "ship(address,bytes,address[],uint256[])"
AQUA_DOCK: Final[str] = "dock(address,bytes32,address[])"


def approve_step(token: str, amount: int) -> ExecutionStep:
    """Let Aqua pull `amount` of `token` from the vault when a taker fills.

    **Not optional, and its absence is silent.** Verified on a fork: `ship()`
    succeeds with no allowance at all — it records full virtual balances and
    returns a valid strategy hash — because shipping moves nothing and the
    allowance is only consumed later, when a taker fills and Aqua `pull()`s.
    A plan that omitted these steps would look completely successful and then
    quietly never be filled. So these are what make the position real, not
    defensive ordering.

    Approved for exactly the shipped amount rather than `type(uint256).max`
    (which is what 1inch's own tests use). A vault holds other people's money;
    an unbounded standing allowance to any contract is a worse default than
    re-approving on the next ship.
    """
    return ExecutionStep(
        target=token,
        value="0",
        calldata=encode_call(ERC20_APPROVE, addresses.AQUA, amount),
        why=f"approve Aqua to pull up to {amount} of {token[:10]}… when filled",
    )


def ship_step(
    strategy: str,
    tokens: list[str],
    amounts: list[int],
    *,
    app: str = addresses.SWAPVM,
) -> ExecutionStep:
    """Open the position.

    `tokens` and `amounts` must be index-aligned and in the strategy's own token
    order — `ProgramBuilder.build_strategy` returns that order for exactly this
    reason.
    """
    if len(tokens) != len(amounts):
        raise ValueError(
            f"ship() needs one amount per token; got {len(tokens)} tokens "
            f"and {len(amounts)} amounts"
        )

    return ExecutionStep(
        target=addresses.AQUA,
        value="0",
        calldata=encode_call(
            AQUA_SHIP,
            app,
            bytes.fromhex(strategy[2:]),
            [t.lower() for t in tokens],
            amounts,
        ),
        why="ship the SwapVM strategy into Aqua — tokens stay in the vault",
    )


def dock_step(
    strategy_hash: str,
    tokens: list[str],
    *,
    app: str = addresses.SWAPVM,
) -> ExecutionStep:
    """Close the position by zeroing its virtual balances.

    Also capital-neutral: there is nothing to withdraw, because nothing ever
    left. Docking simply stops takers being able to fill against the strategy.
    """
    return ExecutionStep(
        target=addresses.AQUA,
        value="0",
        calldata=encode_call(
            AQUA_DOCK,
            app,
            bytes.fromhex(strategy_hash[2:]),
            [t.lower() for t in tokens],
        ),
        why="dock the Aqua strategy — clears virtual balances, moves no capital",
    )
