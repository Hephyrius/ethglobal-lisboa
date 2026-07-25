"""Base mainnet addresses. One source of truth for the whole lane.

Every address here is either published by the sponsor or verified live against
the running API — the provenance note on each is deliberate. A wrong address in
this file is a silent revert at demo time, so nothing lands here unverified.

Chain is Base mainnet (8453) throughout, including the anvil fork of it.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Final

CHAIN_ID: Final[int] = 8453

# ── 1inch (master plan §6, "Live contract addresses (Base — verified)") ────

#: Aqua shared-liquidity registry. The vault is the *maker*: it approves Aqua
#: once and thereafter only virtual balances move. Tokens never leave the vault,
#: which is what makes Aqua compatible with our Pattern 1 custody decision.
AQUA: Final[str] = "0x499943E74FB0cE105688beeE8Ef2ABec5D936d31"

#: SwapVM — executes the strategy program shipped into Aqua.
SWAPVM: Final[str] = "0x8fDD04Dbf6111437B44bbca99C28882434e0958f"

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

# ── Wave 1 universe expansion ─────────────────────────────────────────────
#
# Verified live against the running Base fork: `symbol()` and `decimals()` read
# off each contract, and each has a Chainlink USD feed confirmed by its own
# `description()`. An asset the vault cannot price is an asset it cannot hold,
# so a token with no verified feed does not go in this file.
#
# cbBTC is **8 decimals**, not 18. That is the trap in this group: an amount
# computed as if it were 18-decimal is off by 10^10, and the vault would be
# asking to swap a hundred million bitcoin.
CBBTC: Final[str] = "0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf"
DAI: Final[str] = "0x50c5725949A6F0c72E6C4a641F24049A917DB0Cb"
AERO: Final[str] = "0x940181a94A35A4569E4529A3CDfB74e38FD98631"

#: Symbol → address, for resolving the symbols a mandate and an LLM speak in.
#: VenueIntent carries symbols ("USDC"), not addresses, because that is what a
#: model reliably produces; resolution to an address happens here and nowhere
#: else. Extend deliberately: an unresolvable symbol must fail loudly rather
#: than silently route to the wrong token.
TOKENS: Final[dict[str, str]] = {
    "USDC": USDC,
    "WETH": WETH,
    "ETH": WETH,  # the vault holds wrapped ETH; native ETH is never a position
    "CBBTC": CBBTC,
    "DAI": DAI,
    "AERO": AERO,
}

DECIMALS: Final[dict[str, int]] = {
    USDC.lower(): 6,
    WETH.lower(): 18,
    CBBTC.lower(): 8,
    DAI.lower(): 18,
    AERO.lower(): 18,
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


#: Fallback allowlist, used only when no deployment manifest is available (a
#: fresh clone before Lane A has deployed, or an unfamiliar network). The
#: deployed vault is authoritative — see `allowlist()`.
FALLBACK_ALLOWLIST: Final[frozenset[str]] = frozenset(
    a.lower()
    for a in (
        AQUA,
        SWAPVM,
        UNIVERSAL_ROUTER,
        UNIVERSAL_ROUTER_LEGACY,
        PERMIT2,
        WETH,
        USDC,
        # Tokens are `execute()` targets because an approval step targets the
        # token, not the venue (cross-lane request #8). Every asset in TOKENS
        # therefore has to be here, or its first swap reverts on step 1.
        CBBTC,
        DAI,
        AERO,
    )
)

#: Where Lane A publishes deployed addresses and the vault's real `execute()`
#: allowlist. Overridable so a mainnet manifest can be pointed at without a
#: code change.
DEPLOYMENTS_ENV_VAR: Final[str] = "DEPLOYMENTS_FILE"
DEFAULT_DEPLOYMENTS: Final[Path] = (
    Path(__file__).resolve().parents[1] / "deployments" / "base-fork.json"
)


def deployments_path() -> Path:
    override = os.environ.get(DEPLOYMENTS_ENV_VAR)
    return Path(override) if override else DEFAULT_DEPLOYMENTS


@lru_cache(maxsize=4)
def _allowlist_from(path: Path, mtime: float) -> frozenset[str] | None:
    """`mtime` is part of the cache key only, so a redeploy is picked up
    without a restart."""
    del mtime
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        targets = manifest["executeAllowlist"]["targets"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return frozenset(t.lower() for t in targets) or None


def allowlist() -> frozenset[str]:
    """Targets an `ExecutionPlan` step may legitimately address.

    Read from Lane A's `deployments/base-fork.json` rather than hardcoded, at
    their explicit request (cross-lane request 1): the deployed vault's
    `allowedTargets()` is the only authority, and it is *mutable* — a guardian
    can widen or narrow it after deploy, so a constant compiled into this lane
    would silently drift out of date and the symptom would be an on-chain
    revert rather than a clear failure here.

    Falls back to `FALLBACK_ALLOWLIST` when no manifest is present, so this
    lane still works on a fresh clone and in isolation.
    """
    path = deployments_path()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return FALLBACK_ALLOWLIST
    return _allowlist_from(path, mtime) or FALLBACK_ALLOWLIST
