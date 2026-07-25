"""Every environment-dependent value, resolved in one place.

Scattered `os.getenv` calls are how a lane ends up with three different
opinions about which gateway URL is current. One `Settings` object, loaded
once, passed explicitly.

Loading `.env` is opt-in via `Settings.from_env()` so importing this module
never has a side effect on a caller's process environment.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# The Graph's decentralised gateway. The API key travels as a Bearer header
# rather than in the path (`/api/{key}/subgraphs/id/{id}`, also supported) so
# it cannot leak into an access log, a traceback or a screen share during the
# demo.
DEFAULT_GATEWAY_URL = "https://gateway.thegraph.com/api"

# Token API is a REST service on its own host with its own credential — it is
# NOT the same key as the subgraph gateway. See README "Credentials".
#
# Host verified by probe on 2026-07-25: `token-api.thegraph.com` (the name in
# The Graph's own docs) does not resolve at all, and the docs now redirect to
# Pinax, a Graph core developer who operates the service. `GET /health` here
# returns {"status":"OK"}.
DEFAULT_TOKEN_API_URL = "https://api.pinax.network/v1"

# x402: the same subgraph gateway, on the payment-gated route. Deliberately
# needs no API key — that is the entire point of the path.
DEFAULT_X402_GATEWAY_URL = "https://gateway.thegraph.com/api/x402"

DEFAULT_CHAIN = "base"


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _find_dotenv(start: Path | None = None) -> Path | None:
    """Walk up from `start` looking for a .env.

    Relative to the file, never to the process CWD — the MCP server is launched
    from whatever directory the host client happens to be in, and a teammate on
    macOS must get the same answer as we do on Windows.
    """
    here = (start or Path(__file__).resolve()).parent
    for candidate in [here, *here.parents]:
        dotenv = candidate / ".env"
        if dotenv.is_file():
            return dotenv
    return None


@dataclass(frozen=True)
class Settings:
    """Resolved configuration. Immutable — construct a new one to change it."""

    graph_api_key: str | None = None
    gateway_url: str = DEFAULT_GATEWAY_URL
    token_api_url: str = DEFAULT_TOKEN_API_URL
    token_api_key: str | None = None
    chain: str = DEFAULT_CHAIN
    #: 30s, not 15: the live Uniswap V3 Base subgraph repeatedly answered in
    #: ~20s during testing (its indexers are slow and intermittently
    #: unavailable). A timeout below that turns a working source into a
    #: permanently failing one.
    request_timeout_s: float = 30.0

    #: Per-source ceiling inside `Registry.snapshot`. A source that hangs must
    #: not hold the decision loop open; it lands in `errors[]` instead. Sits
    #: above `request_timeout_s` so a slow *request* fails with a useful
    #: message rather than being cut off by the outer deadline.
    source_timeout_s: float = 45.0

    # ── x402 (feature-flagged, default off) ───────────────────────────────
    x402_enabled: bool = False
    x402_gateway_url: str = DEFAULT_X402_GATEWAY_URL
    x402_private_key: str | None = None
    x402_chain: str = DEFAULT_CHAIN

    #: Extra registry keys are inert unless a mandate names them, so carrying
    #: unknown config here is harmless.
    extra: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_env(cls, *, load_dotenv: bool = True) -> Settings:
        """Read the environment, optionally loading the repo-root `.env` first.

        Real process environment always wins over the file, so a teammate can
        override any single value without editing a committed template.
        """
        if load_dotenv:
            dotenv_path = _find_dotenv()
            if dotenv_path is not None:
                try:
                    from dotenv import load_dotenv as _load

                    _load(dotenv_path, override=False)
                except ImportError:  # pragma: no cover - dotenv is a hard dep
                    pass

        return cls(
            graph_api_key=os.getenv("GRAPH_API_KEY") or None,
            gateway_url=os.getenv("GRAPH_GATEWAY_URL") or DEFAULT_GATEWAY_URL,
            token_api_url=os.getenv("TOKEN_API_URL") or DEFAULT_TOKEN_API_URL,
            # Falls back to the gateway key: The Graph Market issues one
            # credential that works for both in the common case, and a
            # confusing 401 is worse than an attempt.
            token_api_key=os.getenv("TOKEN_API_KEY") or os.getenv("GRAPH_API_KEY") or None,
            chain=os.getenv("DATA_CHAIN") or DEFAULT_CHAIN,
            request_timeout_s=_env_float("DATA_REQUEST_TIMEOUT_S", 15.0),
            source_timeout_s=_env_float("DATA_SOURCE_TIMEOUT_S", 20.0),
            x402_enabled=_env_flag("X402_ENABLED", False),
            x402_gateway_url=os.getenv("X402_GATEWAY_URL") or DEFAULT_X402_GATEWAY_URL,
            x402_private_key=os.getenv("X402_PRIVATE_KEY") or None,
            x402_chain=os.getenv("X402_CHAIN") or DEFAULT_CHAIN,
        )

    # ── Capability checks, so callers report rather than guess ────────────

    @property
    def has_gateway_credential(self) -> bool:
        return bool(self.graph_api_key)

    @property
    def has_token_api_credential(self) -> bool:
        return bool(self.token_api_key)

    @property
    def x402_ready(self) -> bool:
        """Flag on AND a key to sign with. Either missing means fall back."""
        return self.x402_enabled and bool(self.x402_private_key)

    def subgraph_url(self, subgraph_id: str) -> str:
        return f"{self.gateway_url.rstrip('/')}/subgraphs/id/{subgraph_id}"

    def x402_subgraph_url(self, subgraph_id: str) -> str:
        return f"{self.x402_gateway_url.rstrip('/')}/subgraphs/id/{subgraph_id}"


__all__ = [
    "Settings",
    "DEFAULT_GATEWAY_URL",
    "DEFAULT_TOKEN_API_URL",
    "DEFAULT_X402_GATEWAY_URL",
    "DEFAULT_CHAIN",
]
