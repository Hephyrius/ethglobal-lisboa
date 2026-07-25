"""Environment and endpoint configuration for the venue adapters.

All machine-specific values arrive through the environment (master plan §3 —
nothing absolute or OS-specific in the committed tree, because macOS takes over
at 10:00).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Final

from dotenv import find_dotenv, load_dotenv

UNISWAP_API_BASE: Final[str] = "https://trade-api.gateway.uniswap.org/v1"

#: The repo shipped `Example.env` with a lowercase `uniswap_key` before Wave 0
#: standardised on `UNISWAP_API_KEY` in `.env.example`. Both names are still in
#: circulation, so accept either rather than making a teammate debug an empty
#: string — whoever copies `.env.example` on macOS gets the canonical name, and
#: whoever still has the original `.env` keeps working.
_UNISWAP_KEY_NAMES: Final[tuple[str, ...]] = ("UNISWAP_API_KEY", "uniswap_key")

#: Read-only RPC for the one eth_call this lane makes (SwapVM program bytes).
#: The anvil fork is preferred when present; a public Base endpoint is an
#: acceptable last resort here because a view call is not the archive-heavy
#: workload that made BASE_RPC_URL a blocking credential.
_RPC_NAMES: Final[tuple[str, ...]] = ("ANVIL_RPC_URL", "BASE_RPC_URL")
_PUBLIC_BASE_RPC: Final[str] = "https://mainnet.base.org"


def _first_set(names: tuple[str, ...]) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()
    return None


def load_env() -> None:
    """Load the repo-root .env if one exists. Idempotent; never overrides a
    variable already exported, so CI and containers win over the file."""
    path = find_dotenv(usecwd=True)
    if path:
        load_dotenv(path, override=False)


class MissingCredentialError(RuntimeError):
    """A required credential is absent. Raised with the variable name and where
    to get it, because 'None' three frames deep is not a diagnosis."""


def _int_or_none(name: str) -> int | None:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return None
    try:
        value = int(raw.strip())
    except ValueError:
        raise ValueError(
            f"{name}={raw!r} is not an integer number of basis points"
        ) from None
    if not 0 <= value <= 10_000:
        raise ValueError(f"{name}={value} is outside 0..10000 basis points")
    return value


@dataclass(frozen=True, slots=True)
class VenueConfig:
    uniswap_api_key: str | None
    uniswap_api_base: str
    rpc_url: str
    #: Slippage tolerance requested from the Uniswap API, in basis points.
    #:
    #: Set this to the mandate's `max_slippage_bps`. Without it the API applies
    #: its own default — 250 bps — and the harness then rejects the plan for
    #: exceeding a tighter mandate ceiling, which is how a 50 bps mandate ends
    #: up refusing every trade even though the real price impact is ~5 bps.
    #:
    #: Requesting it is also the *honest* form: the agent tells Uniswap the
    #: bound it is actually under, and that bound is baked into the swap
    #: calldata's `minimumAmount`, rather than accepting a looser one and
    #: checking afterwards.
    uniswap_slippage_bps: int | None

    @classmethod
    def from_env(cls) -> VenueConfig:
        load_env()
        return cls(
            uniswap_api_key=_first_set(_UNISWAP_KEY_NAMES),
            uniswap_api_base=os.environ.get("UNISWAP_API_BASE", UNISWAP_API_BASE).rstrip("/"),
            rpc_url=_first_set(_RPC_NAMES) or _PUBLIC_BASE_RPC,
            uniswap_slippage_bps=_int_or_none("UNISWAP_SLIPPAGE_BPS"),
        )

    def require_uniswap_key(self) -> str:
        if not self.uniswap_api_key:
            raise MissingCredentialError(
                "UNISWAP_API_KEY is not set. Register at "
                "https://developers.uniswap.org/dashboard, then put it in the repo-root .env "
                "(which is gitignored). `uniswap_key` is also accepted for the legacy name."
            )
        return self.uniswap_api_key
