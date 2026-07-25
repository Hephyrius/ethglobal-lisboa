"""One depositor's position across every vault on the deployment.

The vault page answers "how is this vault doing?". Nobody could answer **"how am
*I* doing?"** — which is the first question an actual depositor asks, and the
only one that spans vaults.

    VaultFactory.vaults() -> balanceOf(owner) per vault -> convertToAssets

## Cost basis is deliberately not computed

The obvious next field is P&L, and it needs a cost basis: what the depositor
*paid*. That means replaying `Deposit` and `Withdraw` events per vault per owner
and handling partial withdrawals, transfers of shares between wallets, and the
share-price drift between them. Every one of those is a way to be quietly wrong
about someone's money.

What is reported instead is exact and needs no history: **shares held, what they
are worth now, and the vault's return since inception.** A depositor who entered
at inception can read their P&L straight off the last column; one who entered
later can see the vault's record without being told a number about themselves
that we cannot stand behind.

Adding cost basis later is a strictly additive change. Guessing at it now is not.

## Why this reads the chain rather than the performance store

The performance series is per *vault*. Ownership is per *wallet*, and nothing
records it — `balanceOf` is the only authority, and it is one call. Reading it
live also means a deposit made ten seconds ago appears, which is exactly when
someone opens this page.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

__all__ = ["Position", "Portfolio", "read_portfolio"]

log = logging.getLogger(__name__)

#: Selectors, each keccak-derived and asserted in the tests. A wrong one does
#: not error — a call to a missing function on a contract with no fallback
#: returns `0x`, which would read as "this wallet holds nothing".
SELECTOR_VAULTS = "0x8220ef5b"  # VaultFactory.vaults()
SELECTOR_BALANCE_OF = "0x70a08231"  # balanceOf(address)
SELECTOR_CONVERT = "0x07a2d13a"  # convertToAssets(uint256)
SELECTOR_SYMBOL = "0x95d89b41"  # symbol()
SELECTOR_DECIMALS = "0x313ce567"  # decimals()

_INCEPTION_PRICE = 10**6  # convertToAssets(1e18) for a vault that has never traded
_ONE_SHARE = 10**18


@dataclass(frozen=True)
class Position:
    """What one wallet holds in one vault."""

    vault: str
    symbol: str
    shares: str
    #: Current worth in the vault's base asset, from `convertToAssets`.
    value_in_asset: str
    asset_decimals: int
    #: The vault's return since inception — a property of the vault, not of this
    #: holder. Named so it cannot be mistaken for the depositor's own P&L, which
    #: would need a cost basis we deliberately do not compute.
    vault_return_pct: float | None


@dataclass(frozen=True)
class Portfolio:
    owner: str
    positions: list[Position]
    #: Summed across vaults. Safe only because every vault on this deployment is
    #: USDC-based; a mixed-asset deployment would need conversion, and adding
    #: numbers in different units is exactly the bug this note exists to stop.
    total_value: str
    asset_decimals: int


def _uint(raw: bytes) -> int:
    return int.from_bytes(raw, "big")


async def read_portfolio(rpc, factory: str, owner: str) -> Portfolio:
    """Every vault where `owner` holds shares.

    `rpc` is anything with `async call(to, selector) -> bytes` — the same duck
    type the data lane's `RpcClient` satisfies, so this needs no client of its
    own and no second RPC configuration to drift.
    """
    positions: list[Position] = []
    total = 0
    decimals = 6

    raw = await rpc.call(factory, SELECTOR_VAULTS)
    if len(raw) < 64:
        return Portfolio(owner=owner, positions=[], total_value="0", asset_decimals=decimals)

    count = _uint(raw[32:64])
    vaults = [
        "0x" + raw[64 + i * 32 + 12 : 64 + (i + 1) * 32].hex()
        for i in range(count)
        if len(raw) >= 64 + (i + 1) * 32
    ]

    argument = owner.lower().removeprefix("0x").rjust(64, "0")
    for vault in vaults:
        try:
            shares = _uint(await rpc.call(vault, SELECTOR_BALANCE_OF + argument))
        except Exception as exc:  # noqa: BLE001 - one odd vault must not empty a portfolio
            log.debug("could not read %s balance in %s: %s", owner, vault, exc)
            continue
        if shares == 0:
            continue

        try:
            share_argument = hex(_ONE_SHARE)[2:].rjust(64, "0")
            price = _uint(await rpc.call(vault, SELECTOR_CONVERT + share_argument))
            # Value the holding through the vault's own conversion rather than
            # multiplying shares by a price we computed: the vault applies
            # ERC-4626 rounding, and a redemption will use its answer, not ours.
            holder_argument = hex(shares)[2:].rjust(64, "0")
            value = _uint(await rpc.call(vault, SELECTOR_CONVERT + holder_argument))
        except Exception as exc:  # noqa: BLE001
            log.debug("could not value %s in %s: %s", owner, vault, exc)
            continue

        symbol = "shares"
        try:
            from curator_data.chain.rpc import decode_string

            symbol = decode_string(await rpc.call(vault, SELECTOR_SYMBOL)) or symbol
        except Exception:  # noqa: BLE001 - a label, not data
            pass

        positions.append(
            Position(
                vault=vault,
                symbol=symbol,
                shares=str(shares),
                value_in_asset=str(value),
                asset_decimals=decimals,
                vault_return_pct=(
                    price / _INCEPTION_PRICE - 1.0 if price > 0 else None
                ),
            )
        )
        total += value

    positions.sort(key=lambda p: int(p.value_in_asset), reverse=True)
    return Portfolio(
        owner=owner,
        positions=positions,
        total_value=str(total),
        asset_decimals=decimals,
    )
