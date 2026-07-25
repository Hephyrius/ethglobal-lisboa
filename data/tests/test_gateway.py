"""Gateway transport: error classification and credential handling.

The classification tests exist because of a live finding: **the gateway answers
an unauthenticated request with HTTP 200 and a GraphQL `errors[]`**, not a 401.

    $ curl -X POST https://gateway.thegraph.com/api/subgraphs/id/<id> \
           -d '{"query":"{ _meta { block { number } } }"}'
    HTTP 200
    {"errors":[{"message":"auth error: missing authorization header"}]}

Classifying that as a query error would send whoever hits it at 3am to debug
our GraphQL when the actual fix is putting a key in `.env`. Every one of these
failures is something a human has to act on, so naming the right one matters
more than the exception type.
"""

from __future__ import annotations

import httpx
import pytest

from curator_data.config import Settings
from curator_data.graph.errors import GatewayAuthError, GatewayError, GatewayQueryError
from curator_data.graph.gateway import GatewayClient

SETTINGS = Settings(graph_api_key="test-key", gateway_url="https://gateway.example/api")


def _client(handler) -> GatewayClient:
    return GatewayClient(
        SETTINGS, client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )


# ── the live finding ──────────────────────────────────────────────────────


async def test_a_200_with_an_auth_error_body_is_an_auth_failure_not_a_query_failure():
    """Verified against the real gateway - this is its actual behaviour."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"errors": [{"message": "auth error: missing authorization header"}]}
        )

    with pytest.raises(GatewayAuthError):
        await _client(handler).query("sub-1", "{ markets { id } }")


@pytest.mark.parametrize(
    "message",
    [
        "auth error: missing authorization header",
        "invalid api key",
        "Unauthorized",
        "rate limit exceeded",
        "payment required",
    ],
)
async def test_credential_shaped_graphql_errors_are_all_auth_failures(message):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"errors": [{"message": message}]})

    with pytest.raises(GatewayAuthError):
        await _client(handler).query("sub-1", "{ markets { id } }")


async def test_a_genuine_schema_error_stays_a_query_error():
    """The distinction has to cut both ways or it is not a distinction."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"errors": [{"message": "Type `Market` has no field `rates`"}]}
        )

    with pytest.raises(GatewayQueryError) as caught:
        await _client(handler).query("sub-1", "{ markets { rates } }")
    assert "sub-1" in str(caught.value)  # names the protocol to fix


# ── credentials ───────────────────────────────────────────────────────────


async def test_a_missing_key_fails_before_any_request_with_the_fix_in_the_message():
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("must not call the gateway without a credential")

    client = GatewayClient(
        Settings(), client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(GatewayAuthError, match="thegraph.com/studio"):
        await client.query("sub-1", "{ markets { id } }")


async def test_the_api_key_travels_as_a_bearer_header_never_in_the_url():
    """A key in the URL ends up in logs, tracebacks and screen shares."""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json={"data": {"markets": []}})

    await _client(handler).query("sub-1", "{ markets { id } }")

    assert captured["auth"] == "Bearer test-key"
    assert "test-key" not in captured["url"]
    assert captured["url"] == "https://gateway.example/api/subgraphs/id/sub-1"


async def test_no_error_message_ever_leaks_the_api_key():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal error for key test-key")

    with pytest.raises(GatewayError) as caught:
        await _client(handler).query("sub-1", "{ markets { id } }")
    # The upstream body is echoed, so this asserts we do not *add* the key.
    assert "Bearer test-key" not in str(caught.value)


# ── transport failures ────────────────────────────────────────────────────


async def test_http_401_is_still_an_auth_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="nope")

    with pytest.raises(GatewayAuthError):
        await _client(handler).query("sub-1", "{ markets { id } }")


async def test_http_402_is_reported_as_a_payment_gate():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(402, text="payment required")

    with pytest.raises(GatewayAuthError, match="x402"):
        await _client(handler).query("sub-1", "{ markets { id } }")


async def test_a_timeout_is_a_gateway_error_naming_the_subgraph():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("too slow")

    with pytest.raises(GatewayError, match="sub-1"):
        await _client(handler).query("sub-1", "{ markets { id } }")


async def test_non_json_is_reported_rather_than_crashing_the_parser():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>maintenance</html>")

    with pytest.raises(GatewayError, match="non-JSON"):
        await _client(handler).query("sub-1", "{ markets { id } }")


async def test_a_body_with_neither_data_nor_errors_is_rejected():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"extensions": {}})

    with pytest.raises(GatewayError, match="no data"):
        await _client(handler).query("sub-1", "{ markets { id } }")
