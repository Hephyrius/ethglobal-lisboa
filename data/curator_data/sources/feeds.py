"""Chainlink price feeds, per chain. **Data, not code.**

Like `protocols.py` and `tokens.py`: widening what the agent can price is an
edit here, not a change anywhere else.

**Every address below was confirmed on-chain by calling its own
`description()`** rather than copied from a list. That matters more here than
anywhere else in the package — a wrong feed address does not error, it returns
a confident, well-formed, completely wrong price, and the vault values real
capital with it. Readings taken on the Base fork, 2026-07-25:

    0x71041ddd…16Bb70  "ETH / USD"    8 decimals   $1,858.9782
    0x7e860098…a2bc6B  "USDC / USD"   8 decimals   $0.9999
    0x07DA0E54…a59f9D  "cbBTC / USD"  8 decimals   $64,040.8870
    0x591e7923…64C78F  "DAI / USD"    8 decimals   $0.9997

`expect_description` is kept alongside each address so the source can verify at
runtime that the contract it is about to trust says it is what we think it is.

## Adding a feed

Find it in Chainlink's Base feed list, then **confirm before adding**:

    cast call <addr> "description()(string)" --rpc-url $BASE_RPC_URL

If the answer is not the pair you expect, you have the wrong address.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PriceFeed:
    """One Chainlink aggregator."""

    #: Token symbol this feed prices, matching `tokens.py`.
    symbol: str
    address: str
    #: What `description()` must return. Verified at runtime — see module docs.
    expect_description: str
    chain: str = "base"


BASE: tuple[PriceFeed, ...] = (
    PriceFeed("WETH", "0x71041dddad3595F9CEd3DcCFBe3D1F4b0a16Bb70", "ETH / USD"),
    PriceFeed("USDC", "0x7e860098F58bBFC8648a4311b374B1D669a2bc6B", "USDC / USD"),
    PriceFeed("cbBTC", "0x07DA0E54543a844a80ABE69c8A12F22B3aA59f9D", "cbBTC / USD"),
    PriceFeed("DAI", "0x591e79239a7d679378eC8c847e5038150364C78F", "DAI / USD"),
)

FEEDS: dict[str, tuple[PriceFeed, ...]] = {"base": BASE}


def feeds_for(chain: str = "base") -> tuple[PriceFeed, ...]:
    return FEEDS.get(chain.lower(), ())


def feed_for(symbol: str, chain: str = "base") -> PriceFeed | None:
    wanted = symbol.strip().upper()
    return next((f for f in feeds_for(chain) if f.symbol.upper() == wanted), None)


def known_symbols(chain: str = "base") -> list[str]:
    return sorted(f.symbol for f in feeds_for(chain))


__all__ = ["PriceFeed", "FEEDS", "BASE", "feeds_for", "feed_for", "known_symbols"]
