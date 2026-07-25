"""The MCP server as a standalone product.

Graph Track 1 asks for reusable tooling rather than a single end-user app, so
these tests treat the server the way an outside consumer would: build it, list
its tools, call them, and check the response contract holds — including when
the upstream data is unavailable.

The degradation tests run with no credentials on purpose. That is the state a
new user is in thirty seconds after installing, and the server must answer them
with a well-formed response naming what is missing, not a stack trace.
"""

from __future__ import annotations

import json

from curator_mcp.server import build_server

from curator_data.config import Settings

#: No credentials: every upstream call fails, so responses must degrade.
NO_CREDS = Settings()

EXPECTED_TOOLS = {"list_markets", "get_market_yields", "compare_protocols", "get_token_price"}


async def test_server_responds_to_tools_list():
    tools = await build_server(NO_CREDS).list_tools()
    assert {t.name for t in tools} == EXPECTED_TOOLS


async def test_every_tool_is_documented_for_the_model_that_will_call_it():
    """A tool an agent cannot understand from its description is not reusable."""
    for tool in await build_server(NO_CREDS).list_tools():
        assert tool.description and len(tool.description) > 40, tool.name
        assert tool.inputSchema is not None, tool.name


async def test_tool_arguments_match_the_documented_interface():
    tools = {t.name: t for t in await build_server(NO_CREDS).list_tools()}
    assert "asset" in tools["compare_protocols"].inputSchema["properties"]
    assert "symbol" in tools["get_token_price"].inputSchema["properties"]
    # `assets` is optional — a survey with no arguments must work.
    assert "assets" not in (tools["list_markets"].inputSchema.get("required") or [])


async def test_protocols_resource_lists_what_the_server_can_see():
    server = build_server(NO_CREDS)
    resources = await server.list_resources()
    assert [str(r.uri) for r in resources] == ["curator://protocols"]

    rendered = await server.read_resource("curator://protocols")
    body = next(iter(rendered)).content
    assert "aave-v3" in body and "lending" in body


# ── the response contract ─────────────────────────────────────────────────


async def _call(server, name: str, args: dict) -> dict:
    """Call a tool the way a client does and return the parsed payload."""
    result = await server.call_tool(name, args)
    # FastMCP returns (content_blocks, structured_result) across recent
    # versions; accept either rather than pinning to one SDK minor.
    if isinstance(result, tuple):
        blocks, structured = result
        if isinstance(structured, dict):
            return structured
        return json.loads(blocks[0].text)
    return json.loads(result[0].text)


async def test_missing_credentials_degrade_into_errors_not_an_exception():
    """The thirty-seconds-after-install experience must be a clear message.

    It no longer has to be an *empty* one. Before Wave 1 every registered
    source needed a Graph credential, so an uncredentialled install answered
    every question with nothing. `defillama`, `feargreed` and `gas` need no
    key, so a partial answer plus a clear note about what is missing is now the
    honest degraded state — and a much better first impression than a blank.

    What must not change: the missing credential is still *reported*. A
    partial answer presented as a complete one is the failure this test exists
    to catch.
    """
    payload = await _call(build_server(NO_CREDS), "compare_protocols", {"asset": "USDC"})

    assert payload["asset"] == "USDC"
    assert payload["errors"], "a failure must be reported, never silently empty"
    assert any("GRAPH_API_KEY" in e["message"] for e in payload["errors"])


async def test_every_tool_reports_errors_rather_than_returning_a_bare_empty_result():
    server = build_server(NO_CREDS)
    for name, args in (
        ("list_markets", {}),
        ("get_market_yields", {"asset": "USDC"}),
        ("compare_protocols", {"asset": "USDC"}),
        ("get_token_price", {"symbol": "WETH"}),
    ):
        payload = await _call(server, name, args)
        assert "errors" in payload, name
        assert payload["errors"], f"{name} hid a total failure"
        assert "taken_at" in payload, name


async def test_price_tool_lists_the_symbols_it_can_price():
    payload = await _call(build_server(NO_CREDS), "get_token_price", {"symbol": "WETH"})
    assert "USDC" in payload["known_symbols"]
    assert "WETH" in payload["known_symbols"]


async def test_compare_protocols_explains_the_tradeoff_it_exists_to_surface():
    payload = await _call(build_server(NO_CREDS), "compare_protocols", {"asset": "USDC"})
    assert "best_apy" in payload and "deepest_tvl" in payload
    assert "utilization" in payload["note"].lower()


async def test_server_instructions_warn_about_the_two_apy_units():
    """A 100x unit error is the most damaging mistake a caller can make."""
    server = build_server(NO_CREDS)
    instructions = (server.instructions or "").lower()
    assert "supply_apy" in instructions
    assert "0.0432" in instructions and "4.32" in instructions
