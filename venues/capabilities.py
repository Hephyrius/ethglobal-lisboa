"""What each venue can actually do — the manifest the UI and genesis read.

**Why this exists as a first-class thing rather than a docstring.** In Wave 1
`get_venue(key)` could construct an adapter and nothing else. There was no way
to ask *what does this venue do* or *is it usable right now*, so genesis offered
a hardcoded pair and the fully-built Aave venue **could never be granted in a
mandate** — an entire venue invisible for a wave because the only list of venues
was a literal somewhere else. Patching that list fixes the symptom; publishing
capabilities fixes the cause, because the list now cannot disagree with reality.

The manifest answers four questions per venue:

* **What intents does it serve?** So a mandate naming it cannot produce trades
  the harness can only reject.
* **What tokens?** So genesis offers a universe that is real.
* **Where does the capital sit?** The distinction that carries the whole
  Pattern 1 claim — see `Custody` below.
* **Is it usable right now, and if not why?** A missing API key and an
  unregistered aToken are different problems with different fixes.

Availability is **configuration-level and does not touch the network.** Genesis
and the UI call this on every page load; a probe per venue would put third-party
latency on a render path. `probe()` is the opt-in live version.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .config import VenueConfig

#: How the vault's capital is held while the position is open. This is the most
#: load-bearing field in the manifest, because it is what a reader needs to not
#: misjudge `totalAssets()`.
#:
#: * ``virtual``     — tokens never leave the vault. Aqua records
#:                     ``balances[maker][app][strategyHash][token]`` and pulls
#:                     only when a taker fills. This *is* the Pattern 1 claim.
#: * ``claim``       — the underlying really does move, and the vault holds a
#:                     receipt token instead. Still sole custody, different
#:                     shape, and it only works if the vault can value the
#:                     receipt.
#: * ``rotational``  — no position is held at all; the venue changes *what* the
#:                     vault holds and then it is over.
Custody = Literal["virtual", "claim", "rotational"]

#: What the venue is *for*. Two venues that both "earn yield" are not
#: interchangeable if one is passive-fill and the other is a lending pool.
Role = Literal["taker", "maker", "lender"]


@dataclass(frozen=True, slots=True)
class VenueCapability:
    key: str
    role: Role
    summary: str
    #: `VenueIntent` kinds this venue serves, matching the schema's `kind`
    #: literals: swap · ship · dock · supply · withdraw.
    intents: tuple[str, ...]
    #: Token symbols, resolvable by `addresses.resolve_token`.
    tokens: tuple[str, ...]
    custody: Custody
    custody_note: str
    #: Environment variables required for this venue to function at all.
    requires: tuple[str, ...] = ()
    available: bool = True
    #: Present exactly when `available` is False. Names the fix, not the symptom.
    unavailable_reason: str | None = None
    #: Contracts this venue calls. Useful for the UI, and it is also what must
    #: appear on the vault's execute() allowlist.
    contracts: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict:
        """Plain JSON for the API and the UI. No pydantic — this shape is Lane
        D's own, not part of the frozen interface, so it stays a dataclass and
        no schema request is needed to change it."""
        return {
            "key": self.key,
            "role": self.role,
            "summary": self.summary,
            "intents": list(self.intents),
            "tokens": list(self.tokens),
            "custody": self.custody,
            "custody_note": self.custody_note,
            "requires": list(self.requires),
            "available": self.available,
            "unavailable_reason": self.unavailable_reason,
            "contracts": dict(self.contracts),
        }


def _uniswap(config: VenueConfig) -> VenueCapability:
    from . import addresses

    has_key = bool(config.uniswap_api_key)
    return VenueCapability(
        key="uniswap",
        role="taker",
        summary="Executes spot swaps. The only venue that changes the vault's exposure.",
        intents=("swap",),
        # The Trading API routes far more than this; these are the tokens this
        # lane can resolve by symbol and the vault can value.
        tokens=tuple(sorted(set(addresses.TOKENS) - {"ETH"})),
        custody="rotational",
        custody_note=(
            "Settles in full at execution. The vault is left holding a different "
            "token, with no open position and no counterparty claim."
        ),
        requires=("UNISWAP_API_KEY",),
        available=has_key,
        unavailable_reason=(
            None
            if has_key
            else "UNISWAP_API_KEY is not set — register at developers.uniswap.org/dashboard"
        ),
        contracts={
            "router": addresses.UNIVERSAL_ROUTER,
            "permit2": addresses.PERMIT2,
        },
    )


def _aqua(config: VenueConfig) -> VenueCapability:
    from . import addresses

    return VenueCapability(
        key="aqua",
        role="maker",
        summary="Quotes resting liquidity and earns the spread on inventory the vault already holds.",
        intents=("ship", "dock"),
        tokens=("USDC", "WETH"),
        custody="virtual",
        custody_note=(
            "Tokens never leave the vault. Aqua tracks a virtual balance and "
            "debits the vault only on fill, so totalAssets() still reads from "
            "balanceOf."
        ),
        # The program builder runs through an eth_call state override, so no
        # deployment and no key — only an endpoint. Public Base works.
        requires=("BASE_RPC_URL or ANVIL_RPC_URL",),
        available=bool(config.rpc_url),
        unavailable_reason=None if config.rpc_url else "no RPC endpoint configured",
        contracts={"aqua": addresses.AQUA, "swapvm": addresses.SWAPVM},
    )


def _aave(config: VenueConfig) -> VenueCapability:
    from . import addresses
    from .aave.markets import ATOKENS, POOL

    del config  # availability here is on-chain registration, not credentials

    # An aToken the deployment cannot value is worse than an absent venue: the
    # supply succeeds and the share price collapses. Report it as unavailable
    # rather than letting genesis offer it.
    allowed = addresses.allowlist()
    valuable = [
        symbol
        for symbol in ("USDC", "WETH")
        if (ATOKENS.get(addresses.resolve_token(symbol).lower()) or "").lower() in allowed
    ]
    return VenueCapability(
        key="aave",
        role="lender",
        summary="Lends idle assets to Aave v3 at the variable supply rate.",
        intents=("supply", "withdraw"),
        tokens=tuple(valuable),
        custody="claim",
        custody_note=(
            "Principal moves to the Aave pool and the vault receives an aToken "
            "claim opened in its own name. Custody is retained, provided the "
            "aToken carries a registered price feed."
        ),
        available=bool(valuable),
        unavailable_reason=(
            None
            if valuable
            else (
                "no aToken is registered in this deployment's allowlist, so a supply "
                "would collapse the share price — run scripts/expand-universe.sh and "
                "create a new vault (valuations are immutable per vault)"
            )
        ),
        contracts={"pool": POOL},
    )


def _morpho(config: VenueConfig) -> VenueCapability:
    from . import addresses
    from .morpho.markets import VAULTS

    del config  # availability is on-chain registration, not credentials

    allowed = addresses.allowlist()
    # A MetaMorpho share needs ERC4626PriceFeed registered, not merely an
    # allowlist entry — an unvalued share collapses the vault's share price.
    usable = [v for v in VAULTS.values() if v.address.lower() in allowed]
    return VenueCapability(
        key="morpho",
        role="lender",
        summary="Lends idle assets through a curated MetaMorpho vault.",
        intents=("supply", "withdraw"),
        tokens=tuple(sorted({"USDC"} if usable else set())),
        custody="claim",
        custody_note=(
            "Principal moves to the MetaMorpho vault and the vault receives "
            "ERC-4626 shares in its own name. Those shares appreciate rather "
            "than rebase, so valuing them requires an ERC4626PriceFeed."
        ),
        available=bool(usable),
        unavailable_reason=(
            None
            if usable
            else (
                "no MetaMorpho share token is registered in this deployment's "
                "allowlist. Deploy ERC4626PriceFeed from venues/aqua/solidity, register "
                "it with VaultFactory.setDefaultValuation, then create a new vault — "
                "per-vault valuations are immutable"
            )
        ),
        contracts={v.key: v.address for v in VAULTS.values()},
    )


#: One entry per registered venue. A new venue adds a builder here and a factory
#: line in `registry.py` — deliberately the same two-line shape as adding a data
#: source, so "extensible" stays a property rather than a claim.
_BUILDERS = {
    "uniswap": _uniswap,
    "aqua": _aqua,
    "aave": _aave,
    "morpho": _morpho,
}


def capability(key: str, config: VenueConfig | None = None) -> VenueCapability:
    """What one venue can do. Raises `KeyError` for an unregistered key."""
    config = config or VenueConfig.from_env()
    try:
        build = _BUILDERS[key.strip().lower()]
    except KeyError:
        raise KeyError(
            f"no capability manifest for venue {key!r}; registered: {sorted(_BUILDERS)}"
        ) from None
    return build(config)


def capabilities(config: VenueConfig | None = None) -> list[VenueCapability]:
    """Every registered venue, in registry order.

    Genesis and the UI read this instead of a hardcoded list. Unavailable
    venues are **included, not filtered** — "Aave is here but this deployment
    cannot value the aToken" is a far more useful thing to render than silence,
    and silence is exactly how the venue went missing for a wave.
    """
    config = config or VenueConfig.from_env()
    return [build(config) for build in _BUILDERS.values()]


def manifest(config: VenueConfig | None = None) -> list[dict]:
    """`capabilities()` as plain JSON, for the API boundary."""
    return [c.as_dict() for c in capabilities(config)]


async def probe(key: str, config: VenueConfig | None = None) -> VenueCapability:
    """Live reachability for one venue. Opt-in, because it costs a round trip.

    Use this in preflight and diagnostics; never on a page render. Downgrades
    `available` on failure and keeps everything else, so the caller still gets
    the full description of a venue that happens to be down.
    """
    from .errors import VenueError

    base = capability(key, config)
    if not base.available:
        return base

    try:
        if base.key == "uniswap":
            from . import addresses
            from .uniswap.client import QuoteRequest, UniswapClient

            async with UniswapClient.from_config(config) as client:
                await client.quote(
                    QuoteRequest(
                        token_in=addresses.USDC,
                        token_out=addresses.WETH,
                        # 1,000 USDC: the API will not price a trade of 1 USDC
                        # and fails with a 504 HTML page when asked to.
                        amount=1_000_000_000,
                        swapper="0x0000000000000000000000000000000000000001",
                    )
                )
        elif base.key == "aqua":
            from .aqua.program import ProgramBuilder
            from .rpc import RpcClient

            cfg = config or VenueConfig.from_env()
            async with RpcClient(cfg.rpc_url) as rpc:
                await ProgramBuilder(rpc).build_program(fee_bps=0, salt=0)
        # aave builds static calldata; there is nothing to reach.
    except (VenueError, OSError) as exc:
        return VenueCapability(
            **{
                **{f.name: getattr(base, f.name) for f in base.__dataclass_fields__.values()},
                "available": False,
                "unavailable_reason": f"unreachable right now: {exc}",
            }
        )

    return base
