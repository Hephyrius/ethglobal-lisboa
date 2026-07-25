"""MetaMorpho vaults on Base, and the calls this lane makes against them.

**Why MetaMorpho rather than Morpho Blue.** Morpho Blue
(`0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb`) is verified, contract-callable
and needs no signature — but it exposes no `balanceOf` and issues **no receipt
token at all**; a supply position lives in `position(bytes32,address)`. The
curated vault values ERC-20 balances, so supplying there would move USDC out and
return nothing valuable: `totalAssets()` falls by the amount supplied and every
depositor's share price with it.

MetaMorpho vaults sit on top of Morpho Blue and *are* ERC-4626, so the vault
receives a real ERC-20 share it can hold. Those shares **appreciate** rather
than rebasing 1:1 like an aToken, which is why they need
`ERC4626PriceFeed` (in this lane's Foundry project) rather than the underlying's
Chainlink feed. Measured on Base: valuing a share as plain USDC understates the
position by **760 bps** and grows worse every block.

Every address below was confirmed on a Base fork rather than taken from a
listing: bytecode present, `asset() == USDC`, and a share price read live.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from .. import addresses
from ..abi import encode_call

#: Morpho Blue itself. Recorded so nobody re-derives that it is unusable here,
#: and because it is a useful landmark — it is also the USDC whale the fork
#: seeding script impersonates.
MORPHO_BLUE: Final[str] = "0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb"

#: Chainlink USDC/USD on Base, the asset leg of the share price.
USDC_USD_FEED: Final[str] = "0x7e860098F58bBFC8648a4311b374B1D669a2bc6B"


@dataclass(frozen=True, slots=True)
class MetaMorphoVault:
    key: str
    address: str
    asset: str
    #: ERC-4626 share decimals. 18 on every vault checked, and *not* the same as
    #: the asset's 6 — conflating them is a 10^12 error.
    share_decimals: int
    #: Chainlink feed for the underlying, composed by ERC4626PriceFeed.
    asset_feed: str
    description: str


#: Verified on a Base fork on 2026-07-25. Both: 19,340 bytes of code,
#: `asset() == USDC`, 18-decimal shares, share price > 1.0 USDC.
VAULTS: Final[dict[str, MetaMorphoVault]] = {
    "moonwell-usdc": MetaMorphoVault(
        key="moonwell-usdc",
        address="0xc1256Ae5FF1cf2719D4937adb3bbCCab2E00A2Ca",
        asset=addresses.USDC,
        share_decimals=18,
        asset_feed=USDC_USD_FEED,
        description="Moonwell Flagship USDC",
    ),
    "gauntlet-usdc-prime": MetaMorphoVault(
        key="gauntlet-usdc-prime",
        address="0xeE8F4eC5672F09119b96Ab6fB59C27E1b7e44b61",
        asset=addresses.USDC,
        share_decimals=18,
        asset_feed=USDC_USD_FEED,
        description="Gauntlet USDC Prime",
    ),
}

#: Which vault a bare `SupplyIntent(asset="USDC")` lands in. Gauntlet USDC Prime
#: holds ~$426M against Moonwell's ~$9M, so it is the deeper and less
#: slippage-sensitive book for a vault of our size.
DEFAULT_VAULT: Final[str] = "gauntlet-usdc-prime"

# ── canonical signatures ──────────────────────────────────────────────────
# Standard ERC-4626. Do not reformat: keccak of a cosmetically different string
# is a different, silently wrong selector.

DEPOSIT: Final[str] = "deposit(uint256,address)"
WITHDRAW: Final[str] = "withdraw(uint256,address,address)"
REDEEM: Final[str] = "redeem(uint256,address,address)"


def vault_for_asset(asset: str) -> MetaMorphoVault | None:
    """The default vault for an underlying, or None if none is configured."""
    resolved = addresses.resolve_token(asset).lower()
    default = VAULTS[DEFAULT_VAULT]
    if default.asset.lower() == resolved:
        return default
    return next((v for v in VAULTS.values() if v.asset.lower() == resolved), None)


def deposit(assets: int, receiver: str) -> str:
    """`receiver` is the curated vault: the shares must land with the custodian."""
    return encode_call(DEPOSIT, assets, receiver)


def withdraw(assets: int, receiver: str, owner: str) -> str:
    """Exact-asset exit. `owner` is the vault, which holds the shares."""
    return encode_call(WITHDRAW, assets, receiver, owner)


def redeem(shares: int, receiver: str, owner: str) -> str:
    """Exact-share exit — the form a *full* exit must use.

    ERC-4626 has no `type(uint256).max` sentinel the way Aave does, so
    "withdraw everything" cannot be expressed in asset terms without racing
    interest accrual: a figure computed off-chain is already stale when the
    transaction mines, leaving dust or reverting. Redeeming the exact share
    balance is precise, because shares do not accrue — their *value* does.
    """
    return encode_call(REDEEM, shares, receiver, owner)
