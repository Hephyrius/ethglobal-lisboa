# Lane C — Data layer (`/data`)

**Owner:** Lane C instance · **Claimed:** 2026-07-25 · **Scope:** master build plan §10 Lane C (MVP only)

Targets three Graph prize tracks *and* is the extension point for every future data provider.
Those two goals are in tension only if you build the Graph adapters first. So we don't: the
**registry and a source-agnostic `MarketSnapshot` come first, and the Graph adapters are its first
two consumers.**

---

## 1. The one design decision everything else follows from

The registry is not "a thing that calls The Graph." It is a fan-out/merge over anonymous
`DataSource` implementations that each contribute a *partial* list of `Fact`s.

```
mandate.permitted_data_sources = ["messari", "token_api"]
            │
            ▼
   Registry.snapshot(keys, assets)
            │  fan out concurrently, one task per source
            ├──► messari.fetch(assets)    -> [Fact, Fact, …]   (may raise/timeout → captured)
            ├──► token_api.fetch(assets)  -> [Fact, …]
            └──► chainlink.fetch(assets)  -> …                 ← tomorrow, no other file changes
            │
            ▼  merge, mint stable ids, sort
      MarketSnapshot{taken_at, facts[], errors[]}
```

Consequences we are deliberately buying:

- **No provider name appears in any shape.** `MarketSnapshot` is a flat list of provenance-carrying
  facts (`Fact.source` is the registry key). Enforced by a test that greps the public surface.
- **Sources never see each other.** No coverage negotiation, no ordering dependency, no shared
  state. Adding Chainlink is one file + one registration line.
- **A dead source degrades the snapshot; it never crashes the loop.** Every source call is wrapped;
  exceptions, timeouts and unknown keys all land in `snapshot.errors[]`. Lane B's decision loop must
  keep running with partial data — the model is *shown* the errors so it knows what it couldn't see.
- **`permitted_data_sources` is the access-control mechanism.** A source not named in the mandate is
  never consulted. This is the same mechanism as the genesis "user grants data sources" flow, not a
  parallel concept.

### The Track 3 composition argument, made concrete

Messari standardized subgraphs mean **one GraphQL query shape works across every lending protocol**.
So the protocol list is *data*, not code:

```python
# curator_data/sources/protocols.py — adding a protocol is THIS, and nothing else
LENDING = [
    Protocol("aave-v3",     "GQFbb95cE6d8mV989mL5figjaGaKCQB3xqYrr1bRyXqF"),
    Protocol("moonwell",    "…"),
]
```

That table is the demo. Adding a protocol to the agent's opportunity set is a one-line config edit
with no adapter, no schema change, no redeploy.

---

## 2. Layout

```
data/
  pyproject.toml            distribution: curator-data
  README.md                 ← the usage doc Lane B integrates against (Rule 5)
  curator_data/
    config.py               env + feature flags, one Settings object, no scattered os.getenv
    ports.py                lane-local re-export of the frozen DataSource protocol + BaseSource
    facts.py                Fact construction + stable id minting (keeps sources terse)
    registry.py             fan-out / merge / error capture
    graph/
      gateway.py            GraphQL-over-httpx client for gateway.thegraph.com (Bearer auth)
      errors.py             transport error taxonomy
    sources/
      __init__.py           THE REGISTRATION TABLE — one line per source
      protocols.py          protocol → subgraph id (data, not code)
      messari.py            Graph · Messari standardized subgraphs (yields, TVL, utilization)
      token_api.py          Graph · Token API (prices)
    x402/
      client.py             402 → sign → resend, feature-flagged
      payment.py            EIP-3009 USDC authorization signing via eth-account
    cli.py                  reusable `curator-data` CLI: snapshot / verify-live / sources
  curator_mcp/              SEPARATE DISTRIBUTION — standalone MCP server
    pyproject.toml          distribution: curator-mcp
    README.md
    SKILL.md                ← Graph Track 1 gate
    curator_mcp/server.py
  tests/
```

**Deviation from the master plan's sketch, logged in the build log:** the plan showed
`/data/registry.py` importing as `data.registry`. Two problems — `data` is far too generic a
top-level import name to install into a shared venv, and the MCP server must be *separately
installable*, which requires real distribution boundaries. So `/data` is the lane directory and
`curator_data` is the package inside it. Lane B imports `curator_data`, never `data`.

---

## 3. Why the MCP server is a separate distribution

Graph Track 1 asks for **reusable tooling, not a single end-user app.** A server that only works
inside our repo fails that on its face. So `curator-mcp` is its own distribution with its own
`pyproject.toml`, `README.md` and `SKILL.md`, runnable by any MCP client:

```jsonc
{ "mcpServers": { "curator": { "command": "uvx", "args": ["curator-mcp"],
                               "env": { "GRAPH_API_KEY": "…" } } } }
```

Tools: `list_markets`, `get_market_yields`, `compare_protocols`, `get_token_price`.

Our agent harness is visibly *a* consumer, not *the* consumer — it talks to the registry directly
(in-process, no stdio hop), while the MCP server wraps the same sources for everyone else. Both
paths share one implementation, so the reusable product is the same code the demo runs on.

---

## 4. x402 — 90 minute timebox, feature flag, fallback

The agent paying for its own market data out of its own wallet is the strongest narrative beat we
have, and it is also hand-rolled crypto-signing on a deadline. So it is built as a **transport
decorator, not a source**:

```
GatewayClient        ← API-key auth (default, always works)
X402GatewayClient    ← wraps it: try 402-paid request, fall back to the wrapped client on ANY failure
```

- Enabled only by `X402_ENABLED=true`. Default off.
- Any failure — no wallet, unsupported scheme, signing error, non-402 response — falls back to the
  API-key path and records a `snapshot.errors[]` note. It is structurally incapable of breaking the
  demo.
- Timer starts when the transport decorator is written. At 90 minutes it ships as-is behind the flag
  and I move on.

---

## 5. Live data — the submission gate

The Graph disqualifies mocked data. Fixtures are for development; the demo path hits the live
gateway. `curator-data verify-live` is the single command that proves it: real gateway, real
subgraph, populated `MarketSnapshot`, printed provenance. It is also the macOS handoff check.

**Blocking:** `GRAPH_API_KEY` is absent from `.env` (only `uniswap_key=` is present). It cannot be
self-served — it needs a human at [thegraph.com/studio](https://thegraph.com/studio) → API Keys.
Until it lands, every unit test runs offline against `httpx.MockTransport` and `verify-live` reports
exactly what's missing. Nothing else in the lane is blocked on it.

---

## 6. Order of work

1. `config`, `ports`, `facts`, `registry` + registry tests — **the extension point, first**
2. `graph/gateway` transport
3. `sources/messari` + `protocols` table
4. `sources/token_api`
5. `curator_mcp` (own pyproject + README + SKILL.md)
6. `cli` (`snapshot`, `verify-live`, `sources`)
7. `x402` behind the flag — 90 min timebox
8. README + build log throughout, not at the end

## 7. Definition of done (from master plan §12)

- [ ] Live query against the real gateway returns a populated `MarketSnapshot`
- [ ] MCP server starts standalone and responds to `tools/list`
- [ ] x402 completes a paid query *or* cleanly falls back
- [ ] **Registry test: a dummy second source registers and merges without touching any existing source**
- [ ] `README.md` usage doc current; build-log entries for every non-trivial decision
- [ ] Cross-platform: no absolute paths, POSIX scripts only, `uv run` everywhere

## 8. Risks

| Risk | Mitigation |
|---|---|
| No `GRAPH_API_KEY` → can't verify live | Build offline against `MockTransport`; `verify-live` proves it in one command the moment the key lands |
| Subgraph IDs wrong or subgraph undeployed | IDs are a config table, not code — a correction is a one-line edit. `verify-live` names the failing protocol |
| Messari rate units (percent vs fraction) | Messari `InterestRate.rate` is a **percentage**; normalize `/100` at the adapter. Asserted in tests |
| x402 eats the night | Hard 90-min timebox, flag-off default, transport-decorator design so failure is a no-op |
| Token API needs a *separate* JWT from the gateway key | Own env var, own base URL, degrades into `errors[]` rather than failing the snapshot |
