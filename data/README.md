# `/data` — the market data layer (Lane C)

**Everything the agent can see.** A pluggable source registry that merges partial contributions from
any number of providers into one source-agnostic `MarketSnapshot`.

Two Graph adapters ship today. The registry is the product; they are its first two consumers.

---

## Purpose

The agent decides where to put capital, so what it can see determines what it can do. This layer
owns that, with two goals held simultaneously:

1. **Win three Graph tracks now** — live Messari standardized subgraphs, the Token API, a standalone
   MCP server, and x402 pay-per-query.
2. **Make adding a non-Graph provider later a 30-minute job** — Chainlink, Pyth, DefiLlama.

Those goals conflict only if the Graph adapters drive the design. They don't: the registry and the
`MarketSnapshot` shape came first, and no provider name appears anywhere above `sources/`
(asserted by [`tests/test_source_agnostic.py`](tests/test_source_agnostic.py)).

---

## Public interface

### The one call Lane B needs

```python
from curator_data import build_registry

registry = build_registry()                              # reads .env
snapshot = await registry.snapshot(
    mandate.permitted_data_sources,                      # ["messari", "token_api"]
    mandate.constraints.allowed_assets,                  # ["USDC", "WETH"]
)
```

Implements the frozen [`DataSourceRegistry`](../packages/schema/python/curator_schema/ports.py)
port. Returns a [`MarketSnapshot`](../packages/schema/market-snapshot.schema.json).

| Method | Returns | Notes |
|---|---|---|
| `await registry.snapshot(source_keys, assets)` | `MarketSnapshot` | Fans out concurrently, merges, never raises for source failure |
| `registry.available()` | `list[str]` | Registered keys — the set the genesis UI offers |
| `registry.describe()` | `list[dict]` | Key, human description and capabilities, for a source picker |
| `registry.sources_providing(*kinds)` | `list[str]` | Capability lookup: who supplies `"price"`? |
| `registry.register(key, factory)` | `None` | Runtime registration, for embedders and tests |
| `await registry.aclose()` | `None` | Releases every source's HTTP client. Also an async context manager |

### For late-binding consumers (Lane B)

The agent harness resolves its data seam from configuration rather than importing this lane
directly, so it needs an *instance* at a stable path. That is:

```bash
AGENT_DATA_REGISTRY=curator_data.default:registry
```

[`curator_data/default.py`](curator_data/default.py) exposes a ready-made `Registry` built from the
environment. It satisfies the frozen `DataSourceRegistry` Protocol, and importing it cannot fail on
a missing `GRAPH_API_KEY` — sources are constructed lazily, so an absent credential degrades into
`snapshot.errors` rather than raising at import and dropping the caller back to fixtures.

### Market-level views

`MarketSnapshot` is a flat fact list, which is what keeps it source-agnostic — but that is not how
you render a table. Pivot it:

```python
from curator_data.queries import pivot_markets, pivot_pools, prices, errors_as_dicts

for row in pivot_markets(snapshot):        # sorted by APY, highest first
    print(row.protocol, row.supply_apy, row.tvl_usd, row.utilization, row.fact_ids)
```

`MarketRow` / `PoolRow` both expose `.to_dict()`. `row.fact_ids` is what belongs in
`AllocationDecision.facts_used`.

### Command line

```bash
uv run curator-data sources          # what a mandate may grant
uv run curator-data protocols        # what is configured, and how to add more
uv run curator-data snapshot --assets USDC,WETH [--json]
uv run curator-data verify-live      # prove the demo path hits live data (exit 1 if not)
```

`snapshot --json` emits a schema-valid `MarketSnapshot` on stdout, so another lane can consume real
data without importing any of this.

---

## Data shapes

Everything crossing the boundary is defined in [`packages/schema`](../packages/schema/). Nothing new
is invented here.

```jsonc
{
  "taken_at": "2026-07-25T14:05:00Z",
  "facts": [
    {
      "id": "messari:yield:aave-v3/usdc",   // stable across snapshots; cite this
      "kind": "yield",                       // yield|price|tvl|liquidity|volatility|utilization|volume
      "subject": { "protocol": "aave-v3", "market": "USDC", "chain": "base" },
      "value": 0.0432,                       // 4.32% — a FRACTION, never 4.32
      "unit": "apy_fraction",
      "source": "messari",                   // provenance — the UI shows this
      "observed_at": "2026-07-25T14:04:12Z"
    }
  ],
  "errors": [ { "source": "moonwell", "message": "HTTP 502" } ]
}
```

**`errors` is not decoration.** A non-empty `errors` means the snapshot is *partial*. Show it to the
model — an agent that treats a partial view as complete is the failure mode this layer is shaped to
avoid, and it holds a key.

---

## Sources that ship

| Key | Provides | Data |
|---|---|---|
| `messari` | `yield`, `tvl`, `utilization`, `liquidity` | Messari standardized subgraphs — lending markets and DEX pools on Base |
| `token_api` | `price` | The Graph Token API — USD spot prices |

Protocols behind `messari` live in [`curator_data/sources/protocols.py`](curator_data/sources/protocols.py):
Aave V3, Moonwell (lending) and Uniswap V3 (DEX), all on Base.

---

## Adding a data source

The extension point. **One new file, one new line.**

```python
# curator_data/sources/chainlink.py
from curator_data.ports import BaseSource
from curator_data.facts import FactBuilder

class ChainlinkSource(BaseSource):
    key = "chainlink"
    provides = ("price",)
    description = "Chainlink price feeds on Base"

    async def fetch(self, assets):
        builder = FactBuilder(self.key)
        return [builder.usd("price", builder.subject(token=a), await self._read(a))
                for a in assets]

def make_chainlink_source(settings):
    return ChainlinkSource(settings)
```

```python
# curator_data/sources/__init__.py — the ONLY other edit
SOURCE_FACTORIES = {
    "messari": make_messari_source,
    "token_api": make_token_api_source,
    "chainlink": make_chainlink_source,      # ← this line
}
```

Then name `"chainlink"` in a mandate's `permitted_data_sources`. Nothing else changes — not the
registry, not the schema, not the agent, not the dApp. Because sources are selected by *capability*
(`provides`), the new source immediately participates in price queries and in the MCP server's
`get_token_price`.

**Adding a protocol to an existing source is even smaller** — one `Protocol(...)` line in
`protocols.py`. That is the point of Messari standardized subgraphs: every lending market answers
the same GraphQL document, so a new protocol needs no adapter at all.

### What a source must guarantee

- **Never raise for expected failure** — a timeout, a rate limit, a missing market. Return what you
  have and call `self.note("...")` for the rest; notes surface in `snapshot.errors`.
- **Normalise at the boundary.** `apy_fraction` is `0.0432` for 4.32%. Use
  `FactBuilder.apy_from_percent()` when the upstream reports percentages — Messari does.
- **Never guess an identifier.** An unknown token symbol is a note naming the fix, not a guessed
  contract address. This system trades with a real key.

---

## Dependencies

**Requires:** `curator-schema` (the frozen interface), `httpx`, `pydantic`, `python-dotenv`.
Optional: `eth-account` for x402 (`pip install curator-data[x402]`).

**Depends on no other lane.** Lane B consumes this through the `DataSourceRegistry` port; nothing
here imports `agent/`, `venues/`, `web/` or `contracts/`.

### Credentials

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `GRAPH_API_KEY` | **yes** | — | Subgraph gateway. Free at [thegraph.com/studio](https://thegraph.com/studio) → API Keys |
| `TOKEN_API_KEY` | no | falls back to `GRAPH_API_KEY` | Token API bearer token — a *separate* credential |
| `DATA_CHAIN` | no | `base` | Chain to query |
| `DATA_REQUEST_TIMEOUT_S` | no | `15` | Per-HTTP-request timeout |
| `DATA_SOURCE_TIMEOUT_S` | no | `20` | Per-source ceiling inside `snapshot()` |
| `X402_ENABLED` | no | `false` | Pay-per-query. Needs `X402_PRIVATE_KEY` too |
| `X402_PRIVATE_KEY` | no | — | Wallet with a few dollars of USDC on Base |

---

## The MCP server

[`curator_mcp/`](curator_mcp/) is a **separate distribution** — its own `pyproject.toml`,
`README.md` and [`SKILL.md`](curator_mcp/SKILL.md), installable and runnable with no part of this
repo:

```jsonc
{ "mcpServers": { "curator": { "command": "uvx", "args": ["curator-mcp"],
                               "env": { "GRAPH_API_KEY": "..." } } } }
```

Tools: `compare_protocols`, `get_market_yields`, `list_markets`, `get_token_price`.

It shares this package's sources rather than reimplementing them, so the reusable product runs the
same code as our demo. Our agent talks to the registry directly (in-process, no stdio hop) — it is
visibly *a* consumer, not *the* consumer.

---

## x402 — pay-per-query

Off by default. Enabled only by `X402_ENABLED=true` **and** `X402_PRIVATE_KEY`.

It is a **decorator over the gateway transport**, not a data source:

```
GatewayClient         API-key auth. Always works. The default.
X402GatewayClient     wraps it. Tries to pay; delegates on ANY failure.
```

There is no code path where enabling x402 loses data the API-key path would have returned. Worst
case is a wasted round-trip and a note in `errors`. A client-side ceiling refuses to sign anything
above 1 USDC — a market-data query costs a fraction of a cent, so a larger demand means something is
wrong.

---

## Assumptions & invariants

Callers may rely on all of these:

- **`snapshot()` never raises** for source failure, timeout or an unknown source key. Those degrade
  into `errors[]`. It raises only for programmer error.
- **Every `Fact.source` is the registry key that produced it.** Enforced at merge; a mislabelled
  fact is corrected *and* reported.
- **Fact ids are unique within a snapshot** and stable across snapshots for the same subject, so
  `facts_used` citations are unambiguous and decisions can be diffed over time.
- **APY is always a fraction.** `0.0432` means 4.32%.
- **Amounts in USD are floats; no `uint256` crosses this boundary** — this layer reports market
  observations, not balances.
- **A source is constructed once** and reused across ticks, so connection pools survive. Call
  `aclose()` when finished.
- **`permitted_data_sources` is access control.** A registered source not named is never consulted.

---

## Tests

```bash
uv run pytest data/tests -q          # 109 tests, no network, no credentials
uv run curator-data verify-live      # the live path — needs GRAPH_API_KEY
```

The unit suite never touches the network (`httpx.MockTransport`); `verify-live` only touches the
network. Live gateway data on the demo path is a Graph submission gate, so it is a command rather
than an assumption.

> ⚠️ **Shared-venv trap.** `uv sync --extra data` *prunes* every package not in the named extras,
> which silently uninstalls other lanes' dependencies. Always sync all of them:
> `uv sync --extra dev --extra data --extra agent --extra venues`.

---

## Layout

```
curator_data/
  config.py         Settings — every env value resolved in one place
  ports.py          BaseSource: the class a new source subclasses
  facts.py          FactBuilder — unit-safe, provenance-stamped Fact construction
  registry.py       fan-out, merge, degradation, capability lookup  ← the extension point
  queries.py        pivots from flat facts back into market rows
  verify.py         live-path checks (importable; the CLI just prints them)
  cli.py            curator-data: sources / protocols / snapshot / verify-live
  graph/            gateway transport (GraphQL over httpx) + transport factory
  sources/
    __init__.py     THE REGISTRATION TABLE — one line per source
    protocols.py    protocol -> subgraph id      (data, not code)
    tokens.py       symbol -> contract address   (data, not code)
    messari.py      Messari standardized subgraphs
    token_api.py    Graph Token API
  x402/             pay-per-query transport decorator, feature-flagged
curator_mcp/        SEPARATE DISTRIBUTION — the standalone MCP server
tests/
```

Plan: [`plans/2026-07-25-lane-c-data.md`](../plans/2026-07-25-lane-c-data.md).
Decisions and their reasoning: [`docs/build-log.md`](../docs/build-log.md).
