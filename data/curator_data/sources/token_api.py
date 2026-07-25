"""Graph · Token API — spot prices for the assets a mandate permits.

Separate from `messari` on purpose, and the separation is the point: this
source knows nothing about subgraphs, speaks REST rather than GraphQL, uses a
*different credential*, and contributes a different `Fact.kind`. Two sources
that share no code path merging into one snapshot is the registry design
working, demonstrated with providers we actually ship rather than a hypothetical.

## Credential

The Token API is not the subgraph gateway. It authenticates with its own
bearer JWT from The Graph Market. `Settings` falls back to `GRAPH_API_KEY`
when `TOKEN_API_KEY` is unset because one credential often covers both, but a
401 here does not mean the gateway key is wrong.

## Endpoint discovery

The Token API moved hosts and path layout during its beta (its documentation
currently redirects to Pinax, a Graph core developer). Rather than hard-code
one guess, the source tries a short ordered list of known path shapes and
remembers the first that answers. `curator-data verify-live` prints which one
worked, so the list can be trimmed to the survivor once confirmed. This costs
at most a couple of 404s on the first call of a process, and it means a path
change degrades to "slightly slower" instead of "source is dead".
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from curator_schema.models import Fact

from ..config import Settings
from ..facts import FactBuilder
from ..ports import BaseSource
from .tokens import address_for, known_symbols

logger = logging.getLogger(__name__)

#: Tried in order; `{address}` and `{network}` are substituted. The first that
#: returns a parseable price wins and is reused for the rest of the process.
#:
#: Order verified by probe on 2026-07-25 against the live host: the first two
#: return HTTP 401 (route exists, needs a credential) while the older
#: `/prices/evm/{address}` shape returns 404 (route does not exist). The 404
#: shapes are kept last rather than deleted — this API moved hosts and layout
#: once already during its beta, and a stale entry costs one wasted request
#: while a missing one costs the whole source.
PRICE_PATHS: tuple[str, ...] = (
    "/evm/prices?network={network}&contract={address}",
    "/evm/ohlc/prices?network={network}&contract={address}&interval=1h&limit=1",
    "/prices/evm/{address}?network_id={network}",
    "/ohlc/prices/evm/{address}?network_id={network}&interval=1h&limit=1",
)

#: The Token API's identifier for Base mainnet.
NETWORK_IDS: dict[str, str] = {"base": "base"}


def _first_number(payload: Any, keys: tuple[str, ...]) -> float | None:
    """Pull the first numeric value under any of `keys`, at any depth.

    The OHLC and spot endpoints return differently-shaped bodies (`data[]` of
    candles vs a flat object), and the shape has changed at least once during
    the beta. Searching by key name rather than by path means both work and a
    third shape probably will too.
    """
    if isinstance(payload, dict):
        for key in keys:
            if key in payload:
                value = payload[key]
                if isinstance(value, (int, float)):
                    return float(value)
                if isinstance(value, str):
                    try:
                        return float(value)
                    except ValueError:
                        pass
        for value in payload.values():
            found = _first_number(value, keys)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = _first_number(item, keys)
            if found is not None:
                return found
    return None


class TokenApiSource(BaseSource):
    """USD spot prices for permitted assets."""

    key = "token_api"
    provides = ("price",)
    description = (
        "USD spot prices and token metadata from The Graph's Token API. Prices the "
        "assets a mandate permits so the agent can value non-base holdings."
    )

    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.AsyncClient | None = None,
    ):
        super().__init__()
        self.settings = settings
        self._client = client
        self._owns_client = client is None
        #: Sticky once discovered — see "Endpoint discovery" above.
        self._working_path: str | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.settings.request_timeout_s)
        return self._client

    async def fetch(self, assets: list[str]) -> list[Fact]:
        if not self.settings.token_api_key:
            # Raising is right here, unlike a per-token failure: with no
            # credential *nothing* can be fetched, so this is a whole-source
            # failure and belongs in errors[] as one clear line.
            raise RuntimeError(
                "TOKEN_API_KEY (or GRAPH_API_KEY) is not set - the Token API needs a "
                "bearer token from The Graph Market"
            )

        network = NETWORK_IDS.get(self.settings.chain, self.settings.chain)
        builder = FactBuilder(self.key, chain=self.settings.chain)

        facts: list[Fact] = []
        for symbol in dict.fromkeys(a.strip().upper() for a in assets if a and a.strip()):
            address = address_for(symbol, self.settings.chain)
            if address is None:
                self.note(
                    f"no known contract address for {symbol} on {self.settings.chain} "
                    f"(known: {', '.join(known_symbols(self.settings.chain))}) — "
                    f"add it to curator_data/sources/tokens.py"
                )
                continue

            price = await self._price(address, network, symbol)
            if price is None:
                continue
            facts.append(
                builder.usd("price", builder.subject(token=symbol), price)
            )
        return facts

    async def _price(self, address: str, network: str, symbol: str) -> float | None:
        """USD price for one token, or None with a note explaining why not."""
        paths = (
            (self._working_path,) if self._working_path else PRICE_PATHS
        )
        last_problem = "no endpoint answered"

        for template in paths:
            url = self.settings.token_api_url.rstrip("/") + template.format(
                address=address, network=network
            )
            try:
                response = await self.client.get(url, headers=self._headers())
            except httpx.HTTPError as exc:
                last_problem = f"{type(exc).__name__}: {exc}"
                continue

            if response.status_code in (401, 403):
                # Credential problems are not per-path; stop trying.
                raise RuntimeError(
                    f"Token API rejected the credential (HTTP {response.status_code})"
                )
            if response.status_code >= 400:
                last_problem = f"HTTP {response.status_code}"
                continue

            try:
                body = response.json()
            except ValueError:
                last_problem = "non-JSON response"
                continue

            price = _first_number(body, ("price_usd", "priceUsd", "usd", "close", "price"))
            if price is None or price <= 0:
                last_problem = "response contained no usable price"
                continue

            self._working_path = template
            return price

        self.note(f"price for {symbol} unavailable: {last_problem}")
        return None

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.settings.token_api_key}",
        }

    async def close(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
        self._client = None


def make_token_api_source(settings: Settings) -> TokenApiSource:
    """Registration factory. Referenced from `sources/__init__.py`."""
    return TokenApiSource(settings)


__all__ = ["TokenApiSource", "make_token_api_source", "PRICE_PATHS"]
