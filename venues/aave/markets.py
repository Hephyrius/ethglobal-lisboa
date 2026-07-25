"""Aave v3 on Base: addresses and calldata. **Data, not logic.**

Every address here was read off the running fork, not recalled, and each aToken
was confirmed **two independent ways** — because an aToken address that looks
right and is wrong produces a vault holding a token nothing can value, and
`totalAssets()` silently drops by the amount supplied.

Readings taken 2026-07-25 against the Base fork:

    Pool            0xA238Dd80C259a72e81d7e4664a9801593F98d1c5   has code
    aBasUSDC        0x4e65fE4DbA92790696d040ac24Aa414708F5c0AB   6 dec
        UNDERLYING_ASSET_ADDRESS()      -> 0x8335…2913 (USDC)      ✓
        Pool.getReserveData(USDC)[8]    -> 0x4e65…c0AB             ✓
    aBasWETH        0xD4a0e0b9149BCee3C920d2E00b5dE09138fd8bb7   18 dec
        UNDERLYING_ASSET_ADDRESS()      -> 0x4200…0006 (WETH)      ✓

## Adding a market

Confirm both ways before adding the line:

    cast call <aToken> "UNDERLYING_ASSET_ADDRESS()(address)" --rpc-url $RPC
    cast call 0xA238Dd80C259a72e81d7e4664a9801593F98d1c5 \\
         "getReserveData(address)" <asset> --rpc-url $RPC     # word [8]

Then register its valuation so the vault can price it — an aToken is a 1:1
rebasing claim, so the feed is the **underlying's**:

    ./scripts/expand-universe.sh
"""

from __future__ import annotations

from typing import Final

from .. import addresses
from ..abi import encode_call

#: Aave v3 `Pool` on Base. The `PoolAddressesProvider` at
#: 0xe20fCBdBfFC4Dd138cE8b2E6FBb6CB49777ad64D resolves to this; pinned directly
#: because the vault's execute() allowlist has to name a concrete address
#: anyway, so an indirection that could change under us buys nothing.
POOL: Final[str] = "0xA238Dd80C259a72e81d7e4664a9801593F98d1c5"

#: underlying (lowercase) → aToken.
ATOKENS: Final[dict[str, str]] = {
    addresses.USDC.lower(): "0x4e65fE4DbA92790696d040ac24Aa414708F5c0AB",
    addresses.WETH.lower(): "0xD4a0e0b9149BCee3C920d2E00b5dE09138fd8bb7",
}

#: Canonical signatures. Do not reformat — keccak of a cosmetically different
#: string is a different, silently wrong selector.
SUPPLY: Final[str] = "supply(address,uint256,address,uint16)"
WITHDRAW: Final[str] = "withdraw(address,uint256,address)"

#: Aave's referral programme is inactive; 0 is the documented no-referral value.
_NO_REFERRAL: Final[int] = 0


def aave_pool_supply(asset: str, amount: int, on_behalf_of: str) -> str:
    """`Pool.supply(asset, amount, onBehalfOf, 0)` calldata.

    `on_behalf_of` must be the vault. Aave credits the aToken to that address,
    so passing anything else hands the position to a party that is not the
    custodian — which would break the whole trust model, silently, on a call
    that succeeds.
    """
    return encode_call(SUPPLY, asset, amount, on_behalf_of, _NO_REFERRAL)


def aave_pool_withdraw(asset: str, amount: int, to: str) -> str:
    """`Pool.withdraw(asset, amount, to)` calldata.

    `to` must be the vault, for the same reason. Pass
    `venue.UINT256_MAX` as `amount` for a full exit — an aToken balance grows
    every block, so any concrete figure computed off-chain is stale by the time
    the transaction mines.
    """
    return encode_call(WITHDRAW, asset, amount, to)


def atoken_for(asset: str) -> str | None:
    """The aToken a supply of `asset` returns, or None if we have not confirmed one."""
    return ATOKENS.get(asset.lower())


__all__ = [
    "ATOKENS",
    "POOL",
    "SUPPLY",
    "WITHDRAW",
    "aave_pool_supply",
    "aave_pool_withdraw",
    "atoken_for",
]
