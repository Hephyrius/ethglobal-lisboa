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
from typing import Literal


@dataclass(frozen=True)
class PriceFeed:
    """One Chainlink aggregator."""

    #: Token symbol this feed prices, matching `tokens.py`.
    symbol: str
    address: str
    #: What `description()` must return. Verified at runtime — see module docs.
    expect_description: str
    chain: str = "base"
    #: **What the answer is denominated in.** Not every Chainlink feed quotes
    #: USD, and assuming otherwise is a 10^10 error rather than a wrong-looking
    #: number: an ETH-quoted feed returns ~1.24 at 18 decimals, which read as
    #: an 8-decimal USD price is $12,400,000,000.
    #:
    #: An `ETH` feed is composed with ETH/USD to reach a USD price. That is why
    #: wstETH was excluded in Wave 1 rather than shipped wrong.
    quote: Literal["USD", "ETH"] = "USD"


#: The symbol whose USD feed is used to convert every ETH-quoted feed.
ETH_QUOTE_SYMBOL = "WETH"


BASE: tuple[PriceFeed, ...] = (
    PriceFeed("WETH", "0x71041dddad3595F9CEd3DcCFBe3D1F4b0a16Bb70", "ETH / USD"),
    PriceFeed("USDC", "0x7e860098F58bBFC8648a4311b374B1D669a2bc6B", "USDC / USD"),
    PriceFeed("cbBTC", "0x07DA0E54543a844a80ABE69c8A12F22B3aA59f9D", "cbBTC / USD"),
    PriceFeed("DAI", "0x591e79239a7d679378eC8c847e5038150364C78F", "DAI / USD"),
    # Added in the Wave 1 universe expansion, verified the same way:
    #     0x4EC5970f…fcfF0  "AERO / USD"  8 decimals  $0.4164
    PriceFeed("AERO", "0x4EC5970fC728C5f65ba413992CD5fF6FD70fcfF0", "AERO / USD"),
    # ── liquid staking tokens: ETH-quoted, 18 decimals ────────────────────
    #
    # The trap the Wave 2 plan names, and it is not one feed but all of them.
    # Read live on the Base fork 2026-07-25 — note every `description()` ends
    # in `/ ETH`, and every one is 18 decimals rather than the USD feeds' 8:
    #
    #     0x43a5C292…4251a  "WSTETH / ETH"   18dp  1.2399811
    #     0x806b4Ac0…41440b "CBETH / ETH"    18dp  1.1353907
    #     0xf397bF97…e9a5   "RETH / ETH"     18dp  1.1680353
    #
    # Each is an exchange RATE, not a price: 1 wstETH is worth 1.24 ETH. The
    # ratio drifting upward over time IS the staking yield accruing.
    PriceFeed(
        "wstETH", "0x43a5C292A453A3bF3606fa856197f09D7B74251a", "WSTETH / ETH", quote="ETH"
    ),
    PriceFeed(
        "cbETH", "0x806b4Ac04501c29769051e42783cF04dCE41440b", "CBETH / ETH", quote="ETH"
    ),
    PriceFeed(
        "rETH", "0xf397bF97280B488cA19ee3093E81C0a77F02e9a5", "RETH / ETH", quote="ETH"
    ),
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
