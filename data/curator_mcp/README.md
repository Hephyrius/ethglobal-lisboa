# curator-mcp

**Live DeFi lending yields, TVL, utilization and token prices on Base — as MCP tools.**

An MCP server that answers the questions an agent actually asks about DeFi markets: *where should
this asset sit, what does it earn, and how deep is the liquidity?* Data comes from
[The Graph](https://thegraph.com) — Messari standardized subgraphs for lending and DEX markets, and
the Token API for spot prices.

Standalone and dependency-light. It knows nothing about any particular agent; it was extracted from
one, which is the only relationship it has to the vault curator that first used it.

---

## Install

Requires Python ≥ 3.10 and a free Graph API key from
[thegraph.com/studio](https://thegraph.com/studio) → API Keys.

```bash
uvx curator-mcp                  # run without installing
# or
pip install curator-mcp
```

Published on PyPI — no clone required. Verified from a machine that has never seen this repo.

**From a clone**, if you want to modify it:

```bash
git clone <this-repo> && cd <this-repo>
uv pip install ./data/curator_mcp
```

## Configure your MCP client

```jsonc
{
  "mcpServers": {
    "curator": {
      "command": "uvx",
      "args": ["curator-mcp"],
      "env": { "GRAPH_API_KEY": "your-key-here" }
    }
  }
}
```

That is the whole setup. Claude Desktop, Claude Code, Cursor, Zed and anything else speaking MCP
over stdio will pick the tools up.

---

## Tools

| Tool | Arguments | Answers |
|---|---|---|
| `compare_protocols` | `asset` | Where should this asset sit? Ranks every protocol, and names the best-APY and deepest-TVL ones separately because they are usually not the same. |
| `get_market_yields` | `asset` | What does this asset earn, and where? Supply-side APYs across every protocol listing it. |
| `list_markets` | `assets?` | Broad survey of lending markets and DEX pools. |
| `get_token_price` | `symbol` | Spot USD price. |

Plus a `curator://protocols` resource listing which protocols are configured.

### Response shape

Every tool returns the same three guarantees:

```jsonc
{
  "asset": "USDC",
  "protocols": [
    {
      "protocol": "aave-v3",
      "supply_apy": 0.0432,        // fraction — use this for arithmetic
      "supply_apy_pct": 4.32,      // percent  — use this for display
      "tvl_usd": 84200000.0,
      "utilization": 0.91,
      "fact_ids": ["messari:yield:aave-v3/usdc", "messari:tvl:aave-v3/usdc"],
      "sources": ["messari"]
    }
  ],
  "best_apy": "aave-v3",
  "deepest_tvl": "moonwell",
  "taken_at": "2026-07-25T14:05:00+00:00",
  "errors": []                     // non-empty means your view is PARTIAL
}
```

1. **`fact_ids` and `sources` on every number.** Provenance travels with the data, so a model can
   cite what it saw and a human can check it.
2. **`errors` on every response.** If a protocol could not be reached it is named here. A non-empty
   `errors` means the answer is partial and should be described that way — never silently treated as
   the whole market.
3. **APY twice, in both units.** `supply_apy` is a fraction (`0.0432`); `supply_apy_pct` is a
   percentage (`4.32`). Mixing them up is a 100× error, so neither has to be inferred.

See [SKILL.md](SKILL.md) for how an agent should use these tools well.

---

## Configuration

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `GRAPH_API_KEY` | **yes** | — | Subgraph gateway credential ([thegraph.com/studio](https://thegraph.com/studio)) |
| `TOKEN_API_KEY` | no | `GRAPH_API_KEY` | Token API bearer token, if different |
| `TOKEN_API_URL` | no | `https://api.pinax.network/v1` | Token API host. Pinax operates it — `token-api.thegraph.com` does not resolve |
| `DATA_CHAIN` | no | `base` | Chain to query |
| `DATA_REQUEST_TIMEOUT_S` | no | `15` | Per-request timeout |
| `CURATOR_MCP_LOG_LEVEL` | no | `WARNING` | Logs go to stderr; stdout is the MCP transport |

Values are read from the environment, or from a `.env` found by walking up from the package.

---

## Extending it

Protocols are configuration, not code. Because Messari publishes one standardized schema per
protocol *type*, every lending market answers the same GraphQL query — so adding one is a single
line in [`curator_data/sources/protocols.py`](../curator_data/sources/protocols.py):

```python
Protocol(key="moonwell", subgraph_id="33ex…sBrg", family="lending", label="Moonwell (Base)"),
```

Adding a whole new *provider* (Chainlink, Pyth, DefiLlama) is one file plus one registration line —
see the [curator-data README](../README.md). New sources appear in these tools automatically,
because tools resolve sources by capability (`provides = ("price",)`) rather than by name.

---

## Verify it works

```bash
GRAPH_API_KEY=… curator-data verify-live      # live gateway check, names any failing protocol
uv run pytest data/tests -q                   # offline test suite
```

## License

MIT.
