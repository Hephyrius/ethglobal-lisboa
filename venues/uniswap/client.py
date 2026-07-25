"""HTTP client for the Uniswap Trading API.

Deliberately knows nothing about `ExecutionPlan` or any other project schema —
it speaks the API's shapes and returns them raw. `plan.py` does the translation.
That split is what lets the plan builder be tested against saved responses with
no network, and stops the API's response shape leaking into the frozen
interface (so a Uniswap API change touches one file).

API reference: https://trade-api.gateway.uniswap.org/v1 — `POST /quote`,
`POST /swap`. Auth is the `x-api-key` header.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Final, Literal

import httpx

from ..addresses import CHAIN_ID
from ..config import VenueConfig
from ..errors import NoRouteError, VenueAPIError

VENUE_KEY: Final[str] = "uniswap"

#: The live API rejects `CLASSIC` with HTTP 400
#: (`"routingPreference" must be one of [BEST_PRICE, FASTEST]`) even though it
#: then echoes `"routing": "CLASSIC"` back in the successful response. Verified
#: 2026-07-25; written up in FEEDBACK.md.
RoutingPreference = Literal["BEST_PRICE", "FASTEST"]

_RETRY_STATUSES: Final[frozenset[int]] = frozenset({429, 500, 502, 503, 504})
_MAX_ATTEMPTS: Final[int] = 3


@dataclass(frozen=True, slots=True)
class QuoteRequest:
    """One trade to price. Amounts are base units as an int — the caller has
    already resolved decimals, because guessing them here is how you build a
    swap 10^12 times too large."""

    token_in: str
    token_out: str
    amount: int
    swapper: str
    trade_type: Literal["EXACT_INPUT", "EXACT_OUTPUT"] = "EXACT_INPUT"
    #: From `Mandate.constraints.max_slippage_bps`. None lets the API pick.
    slippage_bps: int | None = None
    routing_preference: RoutingPreference = "BEST_PRICE"
    chain_id: int = CHAIN_ID

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "type": self.trade_type,
            "amount": str(self.amount),
            "tokenInChainId": self.chain_id,
            "tokenOutChainId": self.chain_id,
            "tokenIn": self.token_in,
            "tokenOut": self.token_out,
            "swapper": self.swapper,
            "routingPreference": self.routing_preference,
        }
        if self.slippage_bps is not None:
            # The API takes slippage as a PERCENT float (2.5 == 2.5%), while
            # our mandate speaks basis points. Convert at this boundary only.
            payload["slippageTolerance"] = self.slippage_bps / 100
        return payload


class UniswapClient:
    """Async client. Use as a context manager, or pass your own httpx client
    to share a connection pool with the rest of the harness."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str,
        client: httpx.AsyncClient | None = None,
        timeout: float = 20.0,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client = client
        self._owns_client = client is None

    @classmethod
    def from_config(
        cls, config: VenueConfig | None = None, **kwargs: Any
    ) -> UniswapClient:
        config = config or VenueConfig.from_env()
        return cls(
            config.require_uniswap_key(), base_url=config.uniswap_api_base, **kwargs
        )

    async def __aenter__(self) -> UniswapClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self._api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        last_error: Exception | None = None

        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                response = await self._http.post(
                    url, json=payload, headers=self._headers
                )
            except httpx.HTTPError as exc:  # timeouts, DNS, connection resets
                last_error = exc
                if attempt == _MAX_ATTEMPTS:
                    raise VenueAPIError(
                        VENUE_KEY, 0, code="transport", detail=str(exc)
                    ) from exc
                await asyncio.sleep(0.5 * attempt)
                continue

            if response.status_code == 200:
                return response.json()

            if response.status_code in _RETRY_STATUSES and attempt < _MAX_ATTEMPTS:
                await asyncio.sleep(0.5 * attempt)
                continue

            raise _api_error(response)

        raise VenueAPIError(  # unreachable in practice; keeps the type honest
            VENUE_KEY, 0, code="retries-exhausted", detail=str(last_error)
        )

    async def quote(self, request: QuoteRequest) -> dict[str, Any]:
        """Price a trade. Returns the raw response — the nested `quote` object
        must be handed back to `swap()` verbatim, so it is never reshaped."""
        return await self._post("/quote", request.to_payload())

    async def swap(self, quote: dict[str, Any]) -> dict[str, Any]:
        """Turn a quote into an unsigned transaction (`to`, `data`, `value`).

        No signature is passed. The API returns 200 without one when the flow
        is allowance-based Permit2, which is the only path available to us: the
        vault is a contract with no key of its own and cannot produce the
        EIP-712 `PermitSingle` signature that `permitData` asks for.
        """
        return await self._post(
            "/swap",
            {"quote": quote, "simulateTransaction": False, "refreshGasPrice": False},
        )


def _api_error(response: httpx.Response) -> VenueAPIError | NoRouteError:
    code: str | None = None
    detail: str | None = None
    try:
        body = response.json()
        code = body.get("errorCode")
        detail = body.get("detail") or body.get("message")
    except ValueError:
        detail = response.text[:300]

    # "no route" is a market condition, not a failure — the harness should
    # record it and carry on rather than treat the tick as broken.
    if code in {"QUOTE_ERROR", "NO_ROUTE"} or (detail and "no route" in detail.lower()):
        return NoRouteError(f"no Uniswap route: {detail or code}")

    return VenueAPIError(VENUE_KEY, response.status_code, code=code, detail=detail)
