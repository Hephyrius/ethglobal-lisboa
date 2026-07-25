"""Recognising a receipt token for what it is.

An aToken is not a new exposure. Supplying USDC to Aave does not make the vault
less long USDC — it makes it long USDC *and* earning. So every weight the
harness computes has to fold `aBasUSDC` back into `USDC`, and the frozen
`Holding.represents` field is where that fact travels.

Without it, a mandate allowing `["USDC", "WETH"]` looks at a vault that just
supplied half its cash and sees 50% of an asset it never permitted. Every
constraint layer then fights a position that is exactly what the mandate asked
for, and the agent can never lend twice.

## Why the map is imported rather than restated

`venues/aave/markets.py` owns the aToken addresses and each one was confirmed
two ways on-chain. A second copy here would be a second thing to keep right, and
the failure mode of getting it wrong is a holding valued as the wrong asset.

The import is lazy and falls back to empty: the harness has to start with no
venue package present (that is the whole point of the late-binding seams), and a
vault that has never lent is unaffected by an empty map.
"""

from __future__ import annotations

import logging
from functools import lru_cache

__all__ = ["receipt_map", "underlying_symbol"]

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def receipt_map() -> dict[str, str]:
    """aToken address (lowercase) → underlying token address (lowercase)."""
    try:
        from venues.aave.markets import ATOKENS
    except Exception as exc:  # noqa: BLE001 - venues is an optional seam
        log.debug("no venue package for receipt-token mapping (%s)", exc)
        return {}
    return {atoken.lower(): underlying.lower() for underlying, atoken in ATOKENS.items()}


def underlying_symbol(token: str, symbols: dict[str, str]) -> str | None:
    """The symbol a receipt token stands for, or None if it is not one.

    `symbols` maps token address (lowercase) → symbol, and is built from the
    vault's own holdings. Resolving through what the vault actually holds rather
    than through a static table means the answer is the symbol the rest of the
    system is already using for that asset — no chance of reporting "USDC" when
    every other line says "USDbC".

    Falls back to a chain-side lookup only when the underlying is not itself a
    holding, which happens when the vault has supplied *all* of an asset.
    """
    underlying = receipt_map().get(token.lower())
    if underlying is None:
        return None
    if (symbol := symbols.get(underlying)) is not None:
        return symbol

    try:
        from venues.addresses import TOKENS
    except Exception:  # noqa: BLE001
        return None
    for candidate, address in TOKENS.items():
        if address.lower() == underlying:
            return candidate
    return None
