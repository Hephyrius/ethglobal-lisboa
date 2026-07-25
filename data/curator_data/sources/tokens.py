"""Symbol → contract address, per chain. **Data, not code.**

Price APIs are keyed by contract address; mandates are written by humans in
symbols. This table is the join, and like `protocols.py` it is deliberately
configuration so that widening the agent's universe is an edit, not a change.

Only addresses that have been verified against a canonical source are listed.
An unknown symbol degrades into a `MarketSnapshot.errors` note naming the
symbol — which is far better than guessing an address and pricing the wrong
token. On a system that trades with a real key, a wrong address is the most
expensive possible bug.

## Adding a token

Confirm the address on https://basescan.org (or the chain's explorer), check
it against a second source, then add the line.
"""

from __future__ import annotations

#: Base mainnet (chain id 8453).
BASE: dict[str, str] = {
    # Circle-native USDC — the vault's base asset. Address per master build
    # plan §6 "Live contract addresses (Base — verified)".
    "USDC": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    # Canonical Base WETH predeploy.
    "WETH": "0x4200000000000000000000000000000000000006",
}

TOKENS: dict[str, dict[str, str]] = {"base": BASE}


def address_for(symbol: str, chain: str = "base") -> str | None:
    """Contract address for `symbol`, or None if we do not know it."""
    return TOKENS.get(chain.lower(), {}).get(symbol.strip().upper())


def known_symbols(chain: str = "base") -> list[str]:
    return sorted(TOKENS.get(chain.lower(), {}))


__all__ = ["TOKENS", "BASE", "address_for", "known_symbols"]
