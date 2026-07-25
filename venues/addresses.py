"""Base mainnet addresses. One source of truth for the whole lane.

Every address here is either published by the sponsor or verified live against
the running API — the provenance note on each is deliberate. A wrong address in
this file is a silent revert at demo time, so nothing lands here unverified.

Chain is Base mainnet (8453) throughout, including the anvil fork of it.
"""

from __future__ import annotations

from typing import Final

CHAIN_ID: Final[int] = 8453

# ── 1inch (master plan §6, "Live contract addresses (Base — verified)") ────

#: Aqua shared-liquidity registry. The vault is the *maker*: it approves Aqua
#: once and thereafter only virtual balances move. Tokens never leave the vault,
#: which is what makes Aqua compatible with our Pattern 1 custody decision.
AQUA: Final[str] = "0x499943e74Fb0ce105688bEEe8ef2ABEc5d936d31"

#: SwapVM — executes the strategy program shipped into Aqua.
SWAPVM: Final[str] = "0x8fdD04dbF6111437b44BbCa99c28882434E0958f"

# ── Uniswap ───────────────────────────────────────────────────────────────

#: The address the Trading API actually returns as the swap tx `to` on Base,
#: and as the Permit2 `spender`. VERIFIED LIVE 2026-07-25 via POST /swap
#: (calldata selector 0x3593564c = UniversalRouter.execute).
#:
#: NOT the same as the 0x2626664c…e481 UniversalRouter that appears in
#: packages/schema/fixtures/execution-plan.json. Allowlisting only the fixture
#: address would revert every swap — filed as cross-lane request 7 to Lane A.
UNIVERSAL_ROUTER: Final[str] = "0x6fF5693b99212Da76ad316178A184AB56D299b43"

#: The older UniversalRouter deployment, kept only so a plan built against the
#: golden fixture is still recognised as a legitimate Uniswap target.
UNIVERSAL_ROUTER_LEGACY: Final[str] = "0x2626664c2603336E57B271c5C0b26F421741e481"

#: Canonical across every chain Uniswap deploys to.
PERMIT2: Final[str] = "0x000000000022D473030F116dDEE9F6B43aC78BA3"

# ── Tokens ────────────────────────────────────────────────────────────────

USDC: Final[str] = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
WETH: Final[str] = "0x4200000000000000000000000000000000000006"

#: Symbol → address, for resolving the symbols a mandate and an LLM speak in.
#: VenueIntent carries symbols ("USDC"), not addresses, because that is what a
#: model reliably produces; resolution to an address happens here and nowhere
#: else. Extend deliberately: an unresolvable symbol must fail loudly rather
#: than silently route to the wrong token.
TOKENS: Final[dict[str, str]] = {
    "USDC": USDC,
    "WETH": WETH,
    "ETH": WETH,  # the vault holds wrapped ETH; native ETH is never a position
}

DECIMALS: Final[dict[str, int]] = {
    USDC.lower(): 6,
    WETH.lower(): 18,
}


class UnknownTokenError(ValueError):
    """A symbol no adapter can resolve. Deliberately fatal — routing a swap to
    the wrong token because a lookup quietly returned None is unrecoverable."""


def resolve_token(symbol_or_address: str) -> str:
    """Symbol or address in, checksum-cased address out.

    Accepts an address directly so a mandate can name a token this file has
    never heard of, which keeps the token list from becoming a bottleneck.
    """
    value = symbol_or_address.strip()
    if value.startswith("0x") and len(value) == 42:
        return value
    try:
        return TOKENS[value.upper()]
    except KeyError:
        raise UnknownTokenError(
            f"cannot resolve token {symbol_or_address!r}; "
            f"known symbols: {sorted(TOKENS)} (or pass a 0x address)"
        ) from None


def decimals_for(address: str) -> int | None:
    """Token decimals where known. None means "ask the chain" — callers must
    not assume 18, which is how amounts silently become 10^12 times wrong."""
    return DECIMALS.get(address.lower())


#: Targets an ExecutionPlan step may legitimately address. This mirrors what we
#: have ASKED Lane A to allowlist on the vault's execute(); it is not the
#: contract's own list and cannot be — Lane D never reads contracts/. It exists
#: so a plan that would revert on-chain fails here instead, with a message that
#: names the seam. See cross-lane requests 7 and 8 in docs/active-work.md.
EXPECTED_ALLOWLIST: Final[frozenset[str]] = frozenset(
    a.lower()
    for a in (
        AQUA,
        SWAPVM,
        UNIVERSAL_ROUTER,
        UNIVERSAL_ROUTER_LEGACY,
        PERMIT2,
        WETH,
        USDC,
    )
)
