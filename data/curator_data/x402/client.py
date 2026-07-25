"""The x402 transport decorator.

Wraps `GatewayClient`. Tries the payment-gated endpoint; on any problem at all,
delegates to the wrapped API-key client. The fallback is not an error handler
bolted on afterwards — it is the design, and it is why this can be enabled
during a live demo without holding one's breath.

Flow:

    POST x402 endpoint  ->  402 Payment Required + terms
                        ->  sign an EIP-3009 authorization
                        ->  POST again with X-PAYMENT
                        ->  200 + data   (and X-PAYMENT-RESPONSE receipt)

Anything other than that path — a non-402 status, an unparseable body, an
amount above our ceiling, a missing key, a signing failure, a rejected payment
— falls back and records why.
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Any

import httpx

from ..config import Settings
from ..graph.gateway import GatewayClient
from .payment import PaymentError, PaymentRequirements, build_payment_header

logger = logging.getLogger(__name__)


class X402GatewayClient(GatewayClient):
    """A `GatewayClient` that pays per query, and silently doesn't when it can't."""

    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.AsyncClient | None = None,
        fallback: GatewayClient | None = None,
    ):
        super().__init__(settings, client=client)
        #: The API-key path. Shares our httpx client so there is one pool.
        self._fallback = fallback or GatewayClient(settings, client=client)
        #: Reported by the CLI, and folded into snapshot errors, so the demo
        #: can state honestly whether the agent actually paid.
        self.paid_queries = 0
        self.fallback_reasons: list[str] = []

    @property
    def label(self) -> str:
        return "x402" if self.paid_queries else "x402->api-key (fell back)"

    async def query(
        self,
        subgraph_id: str,
        document: str,
        variables: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = {"query": document, "variables": variables or {}}
        try:
            data = await self._paid_query(subgraph_id, payload)
            self.paid_queries += 1
            return data
        except PaymentError as exc:
            self._fall_back(f"payment not attempted: {exc}")
        except Exception as exc:  # noqa: BLE001 - the whole point is to fall back
            logger.debug("x402 path failed for %s", subgraph_id, exc_info=True)
            self._fall_back(f"{type(exc).__name__}: {exc}")

        return await self._fallback.query(subgraph_id, document, variables)

    def _fall_back(self, reason: str) -> None:
        logger.info("x402 falling back to API key: %s", reason)
        if reason not in self.fallback_reasons:
            self.fallback_reasons.append(reason)

    async def _paid_query(self, subgraph_id: str, payload: dict) -> dict[str, Any]:
        """The happy path. Raises on anything unexpected; the caller falls back."""
        if not self.settings.x402_private_key:
            raise PaymentError("X402_PRIVATE_KEY is not set")

        url = self.settings.x402_subgraph_url(subgraph_id)
        headers = {"Content-Type": "application/json", "Accept": "application/json"}

        first = await self.client.post(url, json=payload, headers=headers)

        if first.status_code != 402:
            # A 200 without paying means the endpoint is not actually gated;
            # take the data rather than inventing a payment for it.
            if first.status_code < 400:
                return self._read(first, subgraph_id)
            raise PaymentError(
                f"expected 402, got HTTP {first.status_code}: {first.text[:120]}"
            )

        terms = self._terms_from(first)
        header = build_payment_header(terms, self.settings.x402_private_key)

        # Both header names are sent. The Graph's gateway asks for
        # `Payment-Signature`; the x402 v1 spec uses `X-PAYMENT`. Sending both
        # costs a few bytes and means we work against either without sniffing
        # the version, which is worth it while the spec is still moving.
        second = await self.client.post(
            url,
            json=payload,
            headers={**headers, "Payment-Signature": header, "X-PAYMENT": header},
        )
        if second.status_code == 402:
            raise PaymentError(f"payment rejected: {self._reason(second)}")

        data = self._read(second, subgraph_id)
        receipt = second.headers.get("X-PAYMENT-RESPONSE")
        if receipt:
            logger.info("x402 payment settled for %s", subgraph_id)
        return data

    @staticmethod
    def _terms_from(response: httpx.Response) -> PaymentRequirements:
        """Read the 402's terms from wherever this server puts them.

        The Graph's gateway returns an **empty body** and a base64
        `payment-required` header (verified live). The x402 v1 spec puts the
        same JSON in the body. Header first, body as fallback.
        """
        header = response.headers.get("payment-required")
        if header:
            return PaymentRequirements.from_header(header)
        try:
            return PaymentRequirements.from_response(response.json())
        except ValueError as exc:
            raise PaymentError(
                "402 carried neither a payment-required header nor a JSON body"
            ) from exc

    @staticmethod
    def _reason(response: httpx.Response) -> str:
        """Why a payment was refused, from header or body."""
        header = response.headers.get("payment-required")
        if header:
            try:
                padded = header.strip() + "=" * (-len(header.strip()) % 4)
                decoded = json.loads(base64.b64decode(padded))
                return str(decoded.get("error") or decoded)[:200]
            except Exception:  # noqa: BLE001 - best-effort diagnostics
                pass
        return response.text[:160] or f"HTTP {response.status_code} with no detail"

    def status(self) -> dict[str, Any]:
        """What actually happened, for the CLI and the demo feed."""
        return {
            "enabled": self.settings.x402_enabled,
            "paid_queries": self.paid_queries,
            "fell_back": bool(self.fallback_reasons),
            "reasons": list(self.fallback_reasons),
        }

    async def aclose(self) -> None:
        await self._fallback.aclose()
        await super().aclose()


__all__ = ["X402GatewayClient"]
