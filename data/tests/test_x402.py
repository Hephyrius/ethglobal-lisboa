"""x402: the paid path, and — more importantly — that it cannot break the demo.

The master build plan flags hand-rolled x402 as this lane's risk item. The
mitigation is structural (a transport decorator that delegates on any failure),
so most of these tests are failure tests. Each one asserts the same property
from a different angle: **whatever goes wrong, the caller still gets its data
via the API-key path.**
"""

from __future__ import annotations

import base64
import json
import time

import httpx
import pytest

from curator_data.config import Settings
from curator_data.graph.factory import make_gateway
from curator_data.graph.gateway import GatewayClient
from curator_data.x402.client import X402GatewayClient
from curator_data.x402.payment import (
    MAX_PAYMENT_ATOMIC,
    PaymentError,
    PaymentRequirements,
    build_payment_header,
)

# anvil account #0 — a publicly known test key, never funded on mainnet.
TEST_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
USDC_BASE = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"

PAID = Settings(
    graph_api_key="fallback-key",
    x402_enabled=True,
    x402_private_key=TEST_KEY,
    x402_gateway_url="https://gateway.example/api/x402",
    gateway_url="https://gateway.example/api",
)

DATA = {"data": {"markets": [{"id": "m1"}]}}


def _terms(amount: int = 1000, **over) -> dict:
    offer = {
        "scheme": "exact",
        "network": "base",
        "maxAmountRequired": str(amount),
        "payTo": "0x0000000000000000000000000000000000000042",
        "asset": USDC_BASE,
        "resource": "https://gateway.example/api/x402/subgraphs/id/sub-1",
        "maxTimeoutSeconds": 60,
        "extra": {"name": "USD Coin", "version": "2"},
    }
    offer.update(over)
    return {"x402Version": 1, "accepts": [offer]}


def _client(handler) -> X402GatewayClient:
    shared = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return X402GatewayClient(PAID, client=shared)


# ── the happy path ────────────────────────────────────────────────────────


async def test_402_is_answered_with_a_signed_payment_and_the_data_returns():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if "X-PAYMENT" not in request.headers:
            return httpx.Response(402, json=_terms())
        return httpx.Response(200, json=DATA, headers={"X-PAYMENT-RESPONSE": "settled"})

    client = _client(handler)
    data = await client.query("sub-1", "{ markets { id } }")

    assert data == DATA["data"]
    assert client.paid_queries == 1
    assert client.fallback_reasons == []
    assert len(seen) == 2, "expected the 402 probe then the paid retry"
    assert "/x402/" in str(seen[0].url), "must hit the payment-gated endpoint"


async def test_the_payment_header_carries_a_well_formed_signed_authorization():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        header = request.headers.get("X-PAYMENT")
        if not header:
            return httpx.Response(402, json=_terms(amount=1500))
        captured.update(json.loads(base64.b64decode(header)))
        return httpx.Response(200, json=DATA)

    await _client(handler).query("sub-1", "{ markets { id } }")

    assert captured["scheme"] == "exact"
    assert captured["network"] == "base"
    authorization = captured["payload"]["authorization"]
    assert authorization["value"] == "1500"
    assert authorization["to"] == "0x0000000000000000000000000000000000000042"
    assert authorization["from"].startswith("0x")
    assert len(authorization["nonce"]) == 66  # 0x + 32 bytes
    assert captured["payload"]["signature"].startswith("0x")
    # Backdated slightly so clock skew cannot invalidate a good signature.
    assert int(authorization["validAfter"]) < int(time.time())
    assert int(authorization["validBefore"]) > int(time.time())


async def test_each_payment_uses_a_fresh_nonce():
    nonces = []

    def handler(request: httpx.Request) -> httpx.Response:
        header = request.headers.get("X-PAYMENT")
        if not header:
            return httpx.Response(402, json=_terms())
        nonces.append(json.loads(base64.b64decode(header))["payload"]["authorization"]["nonce"])
        return httpx.Response(200, json=DATA)

    client = _client(handler)
    await client.query("sub-1", "{ a }")
    await client.query("sub-2", "{ b }")

    assert len(set(nonces)) == 2


# ── every failure mode falls back and still returns data ──────────────────


async def _assert_falls_back(handler, *, expect_reason: str) -> X402GatewayClient:
    client = _client(handler)
    data = await client.query("sub-1", "{ markets { id } }")

    assert data == DATA["data"], "fallback must still return the caller's data"
    assert client.paid_queries == 0
    assert any(expect_reason in r for r in client.fallback_reasons), client.fallback_reasons
    return client


def _fallback_handler(on_x402):
    """Route the x402 URL to `on_x402`; the API-key URL always succeeds."""

    def handler(request: httpx.Request) -> httpx.Response:
        if "/x402/" in str(request.url):
            return on_x402(request)
        assert request.headers.get("Authorization") == "Bearer fallback-key"
        return httpx.Response(200, json=DATA)

    return handler


async def test_no_signing_key_falls_back():
    client = X402GatewayClient(
        Settings(graph_api_key="fallback-key", x402_enabled=True),
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(_fallback_handler(lambda r: httpx.Response(500)))
        ),
    )
    assert await client.query("sub-1", "{ x }") == DATA["data"]
    assert any("X402_PRIVATE_KEY" in r for r in client.fallback_reasons)


async def test_an_amount_above_the_ceiling_is_refused_not_signed():
    """A gateway asking for 500 USDC per query must not be paid."""
    handler = _fallback_handler(
        lambda r: httpx.Response(402, json=_terms(amount=MAX_PAYMENT_ATOMIC + 1))
    )
    await _assert_falls_back(handler, expect_reason="refusing to sign")


async def test_an_unsupported_scheme_falls_back():
    handler = _fallback_handler(
        lambda r: httpx.Response(402, json=_terms(scheme="upto"))
    )
    await _assert_falls_back(handler, expect_reason="no 'exact' scheme")


async def test_an_unsupported_network_falls_back():
    handler = _fallback_handler(lambda r: httpx.Response(402, json=_terms(network="solana")))
    await _assert_falls_back(handler, expect_reason="unsupported network")


async def test_a_rejected_payment_falls_back():
    def on_x402(request: httpx.Request) -> httpx.Response:
        if "X-PAYMENT" in request.headers:
            return httpx.Response(402, text="insufficient funds")
        return httpx.Response(402, json=_terms())

    await _assert_falls_back(_fallback_handler(on_x402), expect_reason="payment rejected")


async def test_a_malformed_402_body_falls_back():
    handler = _fallback_handler(lambda r: httpx.Response(402, text="<html>nope</html>"))
    await _assert_falls_back(handler, expect_reason="")


async def test_an_empty_accepts_list_falls_back():
    handler = _fallback_handler(
        lambda r: httpx.Response(402, json={"x402Version": 1, "accepts": []})
    )
    await _assert_falls_back(handler, expect_reason="no payment options")


async def test_a_server_error_on_the_paid_endpoint_falls_back():
    handler = _fallback_handler(lambda r: httpx.Response(503, text="unavailable"))
    await _assert_falls_back(handler, expect_reason="expected 402")


async def test_a_network_error_on_the_paid_endpoint_falls_back():
    def on_x402(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dns failure")

    await _assert_falls_back(_fallback_handler(on_x402), expect_reason="")


async def test_an_ungated_endpoint_returns_data_without_inventing_a_payment():
    """A 200 without a 402 means it was never gated. Take the data."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=DATA)

    client = _client(handler)
    assert await client.query("sub-1", "{ x }") == DATA["data"]
    assert client.paid_queries == 1


# ── the feature flag ──────────────────────────────────────────────────────


def test_the_default_transport_is_the_api_key_client():
    gateway = make_gateway(Settings(graph_api_key="k"))
    assert type(gateway) is GatewayClient


def test_the_flag_alone_does_not_enable_payment():
    """Without a key it would fall back on every query — fail obvious instead."""
    gateway = make_gateway(Settings(graph_api_key="k", x402_enabled=True))
    assert type(gateway) is GatewayClient


def test_flag_plus_key_selects_the_paid_transport():
    gateway = make_gateway(PAID)
    assert isinstance(gateway, X402GatewayClient)


def test_status_reports_honestly_whether_the_agent_actually_paid():
    client = X402GatewayClient(PAID)
    status = client.status()
    assert status == {"enabled": True, "paid_queries": 0, "fell_back": False, "reasons": []}


# ── payment construction in isolation ─────────────────────────────────────


def test_requirements_reject_a_missing_recipient():
    with pytest.raises(PaymentError, match="payTo"):
        PaymentRequirements.from_response(_terms(payTo="")).validate()


def test_requirements_reject_a_nonsensical_amount():
    with pytest.raises(PaymentError, match="nonsensical"):
        PaymentRequirements.from_response(_terms(amount=0)).validate()


def test_a_missing_signing_stack_raises_a_recoverable_error():
    """PaymentError is caught by the client; anything else would not be."""
    with pytest.raises(PaymentError):
        build_payment_header(PaymentRequirements.from_response(_terms()), "not-a-key")
