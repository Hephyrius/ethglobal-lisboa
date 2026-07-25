# `/data` — the market data layer (Lane C)

**Everything the agent can see.** A pluggable source registry that merges partial contributions from
any number of providers into one source-agnostic `MarketSnapshot`.

Four sources ship today — three over HTTP, one reading a contract on-chain. The registry is the
product; they are its consumers.

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

| Key | Provides | Data | Live status |
|---|---|---|---|
| `messari` | `yield`, `tvl`, `utilization`, `liquidity` | Messari standardized subgraphs — lending markets and DEX pools on Base | ✅ Moonwell verified live (~15% USDC APY on $14.5M). Uniswap V3 works but its indexers are slow/intermittent |
| `aave` | `yield`, `tvl`, `utilization` | Aave V3 on Base, via **Aave's own** subgraph schema | ✅ verified live (3.41% USDC APY on $174.9M, 0.84 utilization) |
| `chainlink` | `price` | Chainlink feeds, read **on-chain** over JSON-RPC | ✅ verified live (WETH $1,858.98, USDC $0.9999). **Needs no credential** |
| `token_api` | `price` | The Graph Token API — prices derived from executed DEX swaps | ✅ verified live (WETH $1,857.95). Needs its own Graph Market JWT, *not* `GRAPH_API_KEY` |

All subgraph IDs live in [`curator_data/sources/protocols.py`](curator_data/sources/protocols.py),
including a list of candidates **rejected after live testing**, so nobody re-adds them.

### Two independent price sources, on purpose

`chainlink` reads an oracle; `token_api` derives price from executed DEX swaps. The mechanisms share
nothing, so agreement corroborates and **disagreement is a signal** — a stale oracle, a manipulated
pool, or a genuinely dislocated market. Live they sat 0.19% apart.

`prices(snapshot)` therefore returns every observation rather than one winner:

```python
{"WETH": {"price_usd": 1857.18,          # median consensus
          "sources": ["chainlink", "token_api"],
          "observations": [{"source": "chainlink", "price_usd": 1858.98, ...}, ...],
          "spread_pct": 0.19, "disagreement": False}}
```

`chainlink` also reads the **same feeds `totalAssets()` uses**, so the agent and the vault contract
can never disagree about what the portfolio is worth.

### Why Aave is a separate source rather than a branch in `messari`

Live introspection showed the published *Aave V3 Base* subgraph exposes `reserves`, not the
standardized `markets` — so one query shape genuinely cannot read it. It could have been a second
query inside the Messari adapter, but **`Fact.source` is provenance**: labelling data pulled from
Aave's own subgraph as `messari` would be false to anyone reading the dApp.

Adding it was `sources/aave.py` plus one line in `sources/__init__.py`. Nothing else changed — not
the registry, the schema, the MCP server or the agent. That is the extension-point claim exercised
on a real provider rather than a test double.

---

## Adding a data source

The extension point. **One new file, one new line.**

```python
# curator_data/sources/pyth.py
from curator_data.ports import BaseSource
from curator_data.facts import FactBuilder

class PythSource(BaseSource):
    key = "pyth"
    provides = ("price",)
    description = "Pyth price feeds on Base"

    async def fetch(self, assets):
        builder = FactBuilder(self.key)
        return [builder.usd("price", builder.subject(token=a), await self._read(a))
                for a in assets]

def make_pyth_source(settings):
    return PythSource(settings)
```

```python
# curator_data/sources/__init__.py — the ONLY other edit
SOURCE_FACTORIES = {
    "messari": make_messari_source,
    "token_api": make_token_api_source,
    "aave": make_aave_source,
    "chainlink": make_chainlink_source,
    "pyth": make_pyth_source,                # ← this line
}
```

Then name `"pyth"` in a mandate's `permitted_data_sources`. Nothing else changes — not the registry,
not the schema, not the agent, not the dApp. Because sources are selected by *capability*
(`provides`), the new source immediately participates in price queries and in the MCP server's
`get_token_price` — and it is cross-checked against the existing price sources for free.

**This is not a hypothetical.** `aave` and `chainlink` were both added this way *after* the registry
shipped, and `chainlink` is not even an HTTP API — it reads a contract over JSON-RPC. Neither
required a change outside its own file plus one line here.

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
| `TOKEN_API_URL` | no | `https://api.pinax.network/v1` | ⚠️ **not** `token-api.thegraph.com` — that host, named in The Graph's own docs, does not resolve. Verified live |
| `DATA_CHAIN` | no | `base` | Chain to query |
| `DATA_REQUEST_TIMEOUT_S` | no | `15` | Per-HTTP-request timeout |
| `DATA_SOURCE_TIMEOUT_S` | no | `20` | Per-source ceiling inside `snapshot()` |
| `X402_ENABLED` | no | `false` | Pay-per-query. Needs `X402_PRIVATE_KEY` too |
| `X402_PRIVATE_KEY` | no | — | Wallet with a few dollars of USDC on Base |

---

## The MCP server

[`curator_mcp/`](curator_mcp/) is a **separate distribution** — its own `pyproject.toml`,
`README.md` and [`SKILL.md`](curator_mcp/SKILL.md). It installs standalone from a clone:

```bash
uv pip install ./data/curator_mcp     # siblings resolve from the repo; verified in a clean 3.10 venv
```

```jsonc
{ "mcpServers": { "curator": {
    "command": "uv", "args": ["run", "--directory", "/abs/path/to/repo", "curator-mcp"],
    "env": { "GRAPH_API_KEY": "..." } } } }
```

Publishing to PyPI turns that into `uvx curator-mcp` with no clone at all. The distributions are
built and verified to install from wheels alone; only the upload is outstanding — see
[PUBLISHING.md](PUBLISHING.md).

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
uv run pytest data/tests -q          # 180 tests, no network, no credentials
uv run curator-data verify-live      # the live path — needs GRAPH_API_KEY
```

The unit suite never touches the network (`httpx.MockTransport`); `verify-live` only touches the
network. Live gateway data on the demo path is a Graph submission gate, so it is a command rather
than an assumption.

`tests/conftest.py` strips credentials and disables `.env` discovery for every test. That is
deliberate: when a real `GRAPH_API_KEY` first landed in `.env`, three tests changed behaviour and
several others silently began making live calls. The suite now asserts the same thing on a laptop
with a full `.env` and on a fresh clone with none — which is what the macOS handoff needs.

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
