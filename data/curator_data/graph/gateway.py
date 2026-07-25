"""GraphQL client for subgraphs on The Graph's decentralised gateway.

Small on purpose. A GraphQL client library would buy schema validation and a
DSL we don't want — our queries are three fixed strings — at the cost of a
dependency and its own error taxonomy to translate. `httpx.AsyncClient` plus a
POST is the whole protocol.

Auth travels as `Authorization: Bearer <key>`. The gateway also accepts the key
in the path (`/api/<key>/subgraphs/id/<id>`), which we deliberately do not use:
a URL ends up in logs, tracebacks and screen shares, and this repo is public.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ..config import Settings
from .errors import GatewayAuthError, GatewayError, GatewayQueryError

logger = logging.getLogger(__name__)

#: Substrings that mark a GraphQL-level error as a credential problem rather
#: than a bad query. The gateway answers an unauthenticated request with
#: HTTP 200 and {"errors":[{"message":"auth error: missing authorization
#: header"}]}, so status code alone cannot tell these apart.
_AUTH_ERROR_MARKERS = (
    "auth error",
    "missing authorization",
    "invalid api key",
    "unauthorized",
    "payment required",
    "rate limit",
)


def _looks_like_auth_failure(message: str) -> bool:
    lowered = message.lower()
    return any(marker in lowered for marker in _AUTH_ERROR_MARKERS)


class GatewayClient:
    """Executes GraphQL documents against subgraphs by id.

    One client is shared by every source that needs a subgraph, so connection
    pooling and timeouts are configured in exactly one place.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.AsyncClient | None = None,
    ):
        self.settings = settings
        # An injected client is how tests reach this without a network or a
        # credential — `httpx.MockTransport` needs no new dependency.
        self._client = client
        self._owns_client = client is None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.settings.request_timeout_s)
        return self._client

    @property
    def label(self) -> str:
        """How this transport identifies itself in logs and in the CLI."""
        return "api-key"

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.settings.graph_api_key:
            headers["Authorization"] = f"Bearer {self.settings.graph_api_key}"
        return headers

    def _url(self, subgraph_id: str) -> str:
        return self.settings.subgraph_url(subgraph_id)

    async def query(
        self,
        subgraph_id: str,
        document: str,
        variables: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run `document` against `subgraph_id`, returning the `data` object.

        Raises `GatewayAuthError` / `GatewayQueryError` / `GatewayError`. Sources
        let these propagate to the registry, which turns them into
        `MarketSnapshot.errors` entries.
        """
        if not self.settings.graph_api_key:
            # ASCII only in messages that reach a terminal: Windows consoles
            # default to cp1252 and turn a stray em dash into a mojibake box
            # mid-demo.
            raise GatewayAuthError(
                "GRAPH_API_KEY is not set - get one free at https://thegraph.com/studio "
                "-> API Keys and put it in .env",
                subgraph_id=subgraph_id,
            )

        payload = {"query": document, "variables": variables or {}}
        return await self._post(self._url(subgraph_id), payload, subgraph_id)

    async def _post(
        self, url: str, payload: dict[str, Any], subgraph_id: str
    ) -> dict[str, Any]:
        try:
            response = await self.client.post(url, json=payload, headers=self._headers())
        except httpx.TimeoutException as exc:
            raise GatewayError(f"gateway timed out: {exc}", subgraph_id=subgraph_id) from exc
        except httpx.HTTPError as exc:
            raise GatewayError(f"gateway unreachable: {exc}", subgraph_id=subgraph_id) from exc

        return self._read(response, subgraph_id)

    @staticmethod
    def _read(response: httpx.Response, subgraph_id: str) -> dict[str, Any]:
        if response.status_code in (401, 403):
            raise GatewayAuthError(
                f"gateway rejected the API key (HTTP {response.status_code})",
                subgraph_id=subgraph_id,
            )
        if response.status_code == 402:
            raise GatewayAuthError(
                "gateway requires payment (HTTP 402) — this endpoint is x402-gated",
                subgraph_id=subgraph_id,
            )
        if response.status_code >= 400:
            raise GatewayError(
                f"gateway returned HTTP {response.status_code}: {response.text[:200]}",
                subgraph_id=subgraph_id,
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise GatewayError(
                f"gateway returned non-JSON: {response.text[:200]}", subgraph_id=subgraph_id
            ) from exc

        if isinstance(body, dict) and body.get("errors"):
            errors = body["errors"]
            first = errors[0].get("message", "unknown") if errors else "unknown"
            # Verified against the live gateway: a missing or rejected key comes
            # back as HTTP *200* with {"errors":[{"message":"auth error: ..."}]},
            # not as a 401. Classifying that as a query error would send someone
            # to debug our GraphQL when the real fix is a credential.
            if _looks_like_auth_failure(first):
                raise GatewayAuthError(f"gateway rejected the request: {first}",
                                       subgraph_id=subgraph_id)
            raise GatewayQueryError(
                f"GraphQL error: {first}", subgraph_id=subgraph_id, errors=errors
            )

        data = body.get("data") if isinstance(body, dict) else None
        if data is None:
            raise GatewayError(
                "gateway response contained no data", subgraph_id=subgraph_id
            )
        return data

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
        self._client = None


__all__ = ["GatewayClient"]
