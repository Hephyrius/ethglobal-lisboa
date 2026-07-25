"""Known DEX pools for pricing, per chain. **Data, not code.**

Pool *discovery* works — ask the Token API which pools hold a token and pick
the busiest one paired with a stablecoin — but it costs a round trip against an
API whose calls take 8–10 seconds, and `/evm/pools` was observed returning
**HTTP 500** on 2026-07-25 (their bug; `/evm/tokens` does the same). So a pinned
pool is both faster and more reliable than discovering it every run.

Discovery remains the fallback for anything not listed here, so adding a token
still needs no code change — this table is an optimisation, not a requirement.

**Every entry is verified live.** The pool must actually pair the token with a
USD stablecoin, or prices come out in the wrong unit.

## Adding a pool

    GET /evm/pools?network=base&token=<address>&limit=10

Pick the entry with the highest `transactions` whose other leg is USDC, then
record it below with the date it was checked.
"""

from __future__ import annotations

#: (token symbol, chain) -> (pool address, quote token address)
#:
#: base, verified 2026-07-25: uniswap_v3 WETH/USDC fee-100 pool, 34,002,146
#: transactions — the busiest WETH pool on the chain.
BASE: dict[str, tuple[str, str]] = {
    "WETH": (
        "0xb4cb800910b228ed3d0834cf79d697127bbb00e5",
        "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",  # USDC
    ),
}

POOLS: dict[str, dict[str, tuple[str, str]]] = {"base": BASE}


def pool_for(symbol: str, chain: str = "base") -> tuple[str, str] | None:
    """(pool address, quote token address) for `symbol`, if pinned."""
    return POOLS.get(chain.lower(), {}).get(symbol.strip().upper())


__all__ = ["POOLS", "BASE", "pool_for"]
