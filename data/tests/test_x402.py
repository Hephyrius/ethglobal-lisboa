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


def _terms_v2(amount: int = 10000, **over) -> dict:
    """The Graph's gateway terms, verbatim from a live 402 (2026-07-25)."""
    offer = {
        "scheme": "exact",
        "network": "eip155:8453",          # CAIP-2, not "base"
        "amount": str(amount),             # not "maxAmountRequired"
        "payTo": "0x79DC34E41B2b591078d3dE222C43EcaaBD52FcCB",
        "maxTimeoutSeconds": 300,
        "asset": USDC_BASE,
        "extra": {"assetTransferMethod": "eip3009", "name": "USD Coin", "version": "2"},
    }
    offer.update(over)
    return {
        "x402Version": 2,
        "error": "Payment-Signature header is required",
        "resource": {"url": "http://indexer.example/subgraphs/id/sub-1"},
        "accepts": [offer],
    }


def _header(terms: dict) -> str:
    return base64.b64encode(json.dumps(terms).encode()).decode()


def _client(handler) -> X402GatewayClient:
    shared = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return X402GatewayClient(PAID, client=shared)


# ── The Graph's gateway: x402 v2, terms in a header ───────────────────────
#
# Every value in these tests came off the live gateway. Body-only parsing and
# the X-PAYMENT header both silently fell back on every single request until
# this was found.


async def test_terms_are_read_from_the_payment_required_header_with_an_empty_body():
    """The live 402 carries NO body at all - everything is in the header."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if "Payment-Signature" not in request.headers:
            return httpx.Response(
                402, content=b"", headers={"payment-required": _header(_terms_v2())}
            )
        return httpx.Response(200, json=DATA)

    client = _client(handler)
    assert await client.query("sub-1", "{ markets { id } }") == DATA["data"]
    assert client.paid_queries == 1
    assert client.fallback_reasons == []


async def test_the_payment_travels_in_the_payment_signature_header():
    """The gateway asks for `Payment-Signature`; v1's `X-PAYMENT` alone got
    'Payment-Signature header is required'."""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if "Payment-Signature" not in request.headers:
            return httpx.Response(402, headers={"payment-required": _header(_terms_v2())})
        captured["payload"] = json.loads(base64.b64decode(request.headers["Payment-Signature"]))
        return httpx.Response(200, json=DATA)

    await _client(handler).query("sub-1", "{ markets { id } }")
    assert captured, "Payment-Signature header was never sent"


async def test_the_v2_payload_echoes_the_accepted_offer():
    """v2 replaces v1's flat scheme/network with the offer echoed back."""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        header = request.headers.get("Payment-Signature")
        if not header:
            return httpx.Response(402, headers={"payment-required": _header(_terms_v2())})
        captured.update(json.loads(base64.b64decode(header)))
        return httpx.Response(200, json=DATA)

    await _client(handler).query("sub-1", "{ markets { id } }")

    assert captured["x402Version"] == 2
    assert captured["accepted"]["network"] == "eip155:8453"
    assert captured["accepted"]["amount"] == "10000"
    assert captured["resource"]["url"].endswith("sub-1")
    assert "extensions" in captured
    # The signed authorization is still the same EIP-3009 object.
    assert captured["payload"]["authorization"]["value"] == "10000"
    assert captured["payload"]["signature"].startswith("0x")


async def test_a_caip2_network_resolves_to_the_right_chain_id():
    """`eip155:8453` must sign against chain 8453, or the signature is void."""
    terms = PaymentRequirements.from_header(_header(_terms_v2()))
    assert terms.chain_id == 8453


def test_both_amount_spellings_are_accepted():
    """v2 says `amount`; v1 says `maxAmountRequired`."""
    v2 = PaymentRequirements.from_header(_header(_terms_v2(amount=10000)))
    assert v2.max_amount_required == 10000

    v1 = PaymentRequirements.from_response(_terms(amount=1500))
    assert v1.max_amount_required == 1500


async def test_a_rejection_reason_is_read_out_of_the_header():
    """The live refusal ('insufficient_balance') arrives base64 in a header."""
    refusal = {
        "x402Version": 2,
        "error": "Verification failed: invalid_exact_evm_insufficient_balance",
        "accepts": [_terms_v2()["accepts"][0]],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if "/x402/" in str(request.url):
            if "Payment-Signature" not in request.headers:
                return httpx.Response(402, headers={"payment-required": _header(_terms_v2())})
            return httpx.Response(402, headers={"payment-required": _header(refusal)})
        return httpx.Response(200, json=DATA)

    client = _client(handler)
    assert await client.query("sub-1", "{ markets { id } }") == DATA["data"]
    assert any("insufficient_balance" in r for r in client.fallback_reasons)


# ── the happy path (x402 v1: terms in the body, X-PAYMENT) ────────────────


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
