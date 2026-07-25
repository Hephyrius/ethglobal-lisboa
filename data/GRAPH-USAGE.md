# The Graph — exactly what we use

Written for the submission form. Track 2 asks you to *"briefly describe how The Graph is used (which
Subgraphs, endpoints, tools)"*, and Track 3 asks for **two or more Graph products composed**. This is
the copy-pasteable answer, with the specific identifiers rather than a category name — every figure
below was read from the live gateway on 2026-07-25.

Reproduce any of it with:

```bash
uv run curator-data verify-live          # queries every subgraph and prints what came back
uv run curator-data snapshot --assets USDC,WETH
uv run curator-data protocols            # the configured table
```

---

## Subgraphs queried (decentralised network, via the gateway)

| Protocol | Subgraph ID | Schema | Supplies |
|---|---|---|---|
| **Moonwell** (Base) | `33ex1ExmYQtwGVwri1AP3oMFPGSce6YbocBP7fWbsBrg` | Messari **standardized** lending | supply APY, TVL, utilization |
| **Aave V3** (Base) | `GQFbb95cE6d8mV989mL5figjaGaKCQB3xqYrr1bRyXqF` | Aave's **own** schema (`reserves`) | supply APY, TVL, utilization |
| **Uniswap V3** (Base) | `FUbEPQw1oMghy39fwWBFY5fE6MXPXZQtjncQy2cXdrNS` | Messari **standardized** dex-amm | pool liquidity |
| The Graph Network | `DZz4kDTdmzWLWsV373w2bSmoar3umKKH9y82SUKr5qmp` | — | used to *search* the network for candidate subgraphs (see below) |

Endpoint form: `https://gateway.thegraph.com/api/subgraphs/id/{id}`, authenticated with
`Authorization: Bearer $GRAPH_API_KEY` — the key travels as a header, never in the URL, so it cannot
leak into a log or a screen share.

### The composition argument, concretely

Messari publishes **one standardized schema per protocol type**, so a single GraphQL document reads
every lending market. Adding a protocol is one line of configuration in
[`sources/protocols.py`](curator_data/sources/protocols.py) — no adapter, no schema change. That
claim is asserted by a test (`test_one_query_shape_serves_every_lending_protocol`), not just stated.

**Where it stops, honestly:** the published *Aave V3 Base* subgraph is **not** Messari-standardized —
it exposes `reserves`, not `markets`. We searched all 381 active Base subgraphs via The Graph's own
network subgraph and found no standardized Aave on Base, so Aave got its own adapter and its own
registry key. It is a separate key rather than a branch inside the Messari adapter because
`Fact.source` is **provenance**, and labelling Aave's own subgraph as "messari" would be false.

---

## Other Graph products used

**Token API** — `https://api.pinax.network/v1`, authenticated with a Graph Market JWT
(`TOKEN_API_KEY`; the subgraph gateway's key is rejected with 401). Base has no price category, so
price is derived from executed DEX swaps: `GET /evm/swaps?network=base&pool={pool}&limit=10`.

**x402 pay-per-query** — `https://gateway.thegraph.com/api/x402/subgraphs/id/{id}`. The agent pays
for its own market data out of its own wallet, in USDC on Base, **with no API key at all**. The
gateway quotes $0.01 per query.

**MCP server** (Track 1) — [`curator_mcp/`](curator_mcp/), a separately installable distribution with
its own `pyproject.toml`, `README.md` and [`SKILL.md`](curator_mcp/SKILL.md). Four tools:
`compare_protocols`, `get_market_yields`, `list_markets`, `get_token_price`, plus a
`curator://protocols` resource. It shares this package's sources rather than reimplementing them, so
the reusable product runs the same code as the demo — our agent is visibly *a* consumer, not *the*
consumer.

---

## Two or more Graph products, composed (Track 3)

Four sources merge into one **source-agnostic** `MarketSnapshot`:

```
Messari standardized subgraphs ─┐
Aave V3 subgraph               ─┼─► MarketSnapshot (flat facts, each carrying its own provenance)
Graph Token API                ─┤
Chainlink (on-chain, non-Graph)─┘
```

Sources never see each other and never agree on coverage; each contributes a *partial* list of facts
and the registry merges them. That is what makes the composition real rather than a list — and the
fourth source is deliberately **not** an HTTP API at all: it reads a contract over JSON-RPC, showing
the port abstracts *kinds of provider* rather than endpoints.

A live snapshot, exactly as an agent tick runs it (6.3s):

```
moonwell   USDC   APY 15.38%   TVL $ 14,489,518   util 0.91    [messari]
aave-v3    USDC   APY  3.51%   TVL $172,603,113   util 0.85    [aave]
aave-v3    WETH   APY  1.46%   TVL $174,448,695   util 0.77    [aave]
price USDC  $   1.00   via [chainlink]
price WETH  $1,856.33  via [chainlink, token_api]   spread 0.29%
```

Two lending protocols compared, and **two mechanically independent price sources cross-validating** —
an oracle read and executed swap prices, 0.29% apart. A wide spread is surfaced as `disagreement`,
because that gap means a stale oracle, a manipulated pool, or a dislocated market: all things a
curator should act on.

---

## Live data, not mocks

The Graph disqualifies mocked or static data. `curator-data verify-live` is the gate: it queries
every configured subgraph for real and **exits non-zero if anything failed *or was skipped***,
because "we did not check" is not proof. The unit suite is deliberately the opposite — hermetic, no
network, no credentials — so the two never get confused for one another.

## Known limitation, stated plainly

The Uniswap V3 subgraph's indexers are intermittently unavailable (`bad indexers`, or a ~20s
timeout). It is not our query — live introspection confirms the subgraph *is* Messari-standardized
and it has returned data. A per-protocol deadline means it costs at most 6s and degrades into
`MarketSnapshot.errors` rather than delaying the tick. Lending data does not depend on it.
