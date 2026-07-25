# Agentic Vault Curation

**An ERC-4626 vault whose curator is an autonomous LLM agent.** You co-design a strategy in natural
language with a local open model; that conversation crystallizes into a **mandate**; the mandate is
wrapped in a vault; and from genesis onward an agent holding its own key allocates capital against
that mandate using live on-chain data. There is no human override after genesis.

Built at **ETHGlobal Lisbon 2026**.

---

## What it does

A human curator at Morpho or Yearn decides how to allocate deposited capital across markets and
rebalances as conditions change. **Here the agent is the curator.**

```
   ┌──────────── DATA (pluggable registry) ─────────────┐
   │  The Graph: Messari subgraphs · Aave · Token API   │   the agent's EYES
   │  x402 pay-per-query · Chainlink/Pyth drop in later │   (live, never mocked)
   └────────────────────────┬───────────────────────────┘
                            │ MarketSnapshot
                            ▼
                     ┌─────────────┐
                     │ LLM curator │  mandate + strictly validated structured output
                     └──────┬──────┘
                            │ AllocationDecision
                            ▼
                     ┌─────────────┐
       Uniswap API ◄─┤ ERC-4626    ├─► 1inch Aqua / SwapVM
       ROTATE what   │   VAULT     │   HOLD the position
       the vault     │ sole        │   (tokens never leave —
       holds         │ custodian   │    virtual balances only)
                     └─────────────┘
```

**Custody invariant: the vault is the sole custodian.** Capital never leaves it. That constraint is
what makes share accounting trustworthy, and it is why the 1inch integration is structural rather
than decorative — see below.

---

## Sponsor integrations

### 1inch — Aqua / SwapVM · the position

Aqua is a shared-liquidity registry: tokens **stay in the maker's wallet** and only virtual balances
`balances[maker][app][strategyHash][token]` are tracked on-chain. That is exactly our custody model,
so **the vault itself is the Aqua maker** — it approves Aqua once, `ship()`s a strategy, and the
capital never moves. Aqua is the only way we found to hold a live market-making position *without*
breaking sole custody. SwapVM runs in Aqua mode (`useAquaInsteadOfSignature = true`).

| What | Where |
|---|---|
| SwapVM program built with 1inch's official Solidity `ProgramBuilder` | [`venues/aqua/solidity/src/SwapVMProgramBuilder.sol`](venues/aqua/solidity/src/SwapVMProgramBuilder.sol) |
| `ship()` / `dock()` calldata | [`venues/aqua/calldata.py:56`](venues/aqua/calldata.py#L56) · [`:89`](venues/aqua/calldata.py#L89) |
| Venue adapter | [`venues/aqua/venue.py:80`](venues/aqua/venue.py#L80) |
| Fork test: a **contract** maker ships and docks against the real deployed Aqua | [`venues/aqua/solidity/test/VaultRelayFork.t.sol`](venues/aqua/solidity/test/VaultRelayFork.t.sol) |

Official contracts on Base: Aqua `0x499943E74FB0cE105688beeE8Ef2ABec5D936d31`,
SwapVM `0x8fDD04Dbf6111437B44bbca99C28882434e0958f`.

> **A finding worth reading:** `Aqua.ship()` **succeeds with zero allowance**. It returns a valid
> strategy hash and non-zero balances, because shipping moves no tokens — the allowance is only
> consumed later when a taker fills. So a plan missing its approvals does not revert; it produces a
> position that looks healthy in every observable way and is silently never fillable. Pinned by
> `VaultRelayFork.t.sol`, and documented in [`docs/active-work.md`](docs/active-work.md) request #17.

### The Graph — the agent's eyes

| What | Where |
|---|---|
| **Standalone MCP server** — reusable by any agent, not just ours | [`data/curator_mcp/`](data/curator_mcp/) · [`SKILL.md`](data/curator_mcp/SKILL.md) |
| Source registry — mandate names a key, registry resolves it | [`data/curator_data/registry.py`](data/curator_data/registry.py) |
| Messari standardized subgraphs (one query shape, N protocols) | [`data/curator_data/sources/messari.py`](data/curator_data/sources/messari.py) |
| Aave V3 (own schema, so its own key) · Token API | [`sources/aave.py`](data/curator_data/sources/aave.py) · [`sources/token_api.py`](data/curator_data/sources/token_api.py) |
| **x402 pay-per-query** — the agent pays for its own data in USDC, no API key | [`data/curator_data/x402/`](data/curator_data/x402/) |

Adding a data provider is one file plus one registration line, then naming it in a mandate — no
other code changes. `MarketSnapshot` is deliberately **source-agnostic**: a flat list of facts each
carrying its own `source`, merged from partial contributions. No field is named after any provider,
which is why Chainlink or Pyth would drop in unchanged.

**Eight sources ship, and the claim above is exercised rather than asserted.** Four were added after
the registry froze, each as one file plus one line: `chainlink` (a *contract read*, not an HTTP API —
the strongest evidence the registry merges kinds of provider, not just endpoints), `defillama`,
`feargreed` and `gas`. Two of those needed a new `Fact.kind`, which is the schema's documented
extension point being used as designed.

> **The Graph is the depth layer and DefiLlama is breadth — the distinction is deliberate.**
> The Messari and Aave subgraph sources are queried per-protocol against indexed chain state and are
> the sources of record. DefiLlama is a third-party aggregator, so its facts carry a lower
> `Fact.confidence` and the curator prompt prefers a subgraph where they disagree. What it buys is a
> real gap closed: before it, the agent compared Aave against Moonwell and we called that a
> multi-protocol comparison.
>
> Its yields are `apyBase`, never the headline. The first live run put `aerodrome-slipstream
> USDC-CBBTC at 91.14%` above `aave-v3 USDC at 3.50%` — but 76 points of that was `apyReward`, a
> token emission with a different risk profile and an expiry date, not interest.

### Uniswap — the Trading API · rotation

An Aqua maker is passive: it posts liquidity and waits to be filled, so it cannot decide to change
what it holds. Uniswap is the taker-side path that lets the agent actually rotate composition.

| What | Where |
|---|---|
| Trading API client — `POST /quote`, `POST /swap`, `x-api-key` | [`venues/uniswap/client.py:155`](venues/uniswap/client.py#L155) · [`:160`](venues/uniswap/client.py#L160) |
| API response → executable transaction plan | [`venues/uniswap/plan.py`](venues/uniswap/plan.py) |
| Venue adapter behind the shared port | [`venues/uniswap/venue.py`](venues/uniswap/venue.py) |
| Developer feedback | [`FEEDBACK.md`](FEEDBACK.md) |

---

## Contracts

| Contract | Source | Base fork address |
|---|---|---|
| `CuratedVault` | [`contracts/src/CuratedVault.sol`](contracts/src/CuratedVault.sol) | impl `0xd5a7373214426f7eF18666a65c66dC614E1767ce` |
| `VaultFactory` | [`contracts/src/VaultFactory.sol`](contracts/src/VaultFactory.sol) | `0x02827a276587B906a4DDb2C4863C9EbD6Abf302D` |
| Demo vault (cUSDC) | — | `0x0E2c0e50E67B96C9C401C94e111a3DBD00DEB5d1` |

Key functions:

- [`execute(address,uint256,bytes)`](contracts/src/CuratedVault.sol#L124) and
  [`executeBatch(Call[])`](contracts/src/CuratedVault.sol#L134) — the agent's only write surface.
  `AGENT_ROLE` plus a **target allowlist**. This single generic entry point is what lets venue
  adapters build arbitrary calldata off-chain while the vault stays venue-agnostic; a new venue is a
  new adapter, never a contract change.
- [`totalAssets()`](contracts/src/CuratedVault.sol#L189) — base-asset balance plus non-base holdings
  valued through Chainlink. **Reverts rather than returning a wrong number** if a feed for a token
  the vault actually holds is stale.
- [`holdings()`](contracts/src/CuratedVault.sol#L303) — the whole position in one call, no N+1.

Addresses are read from [`deployments/base-fork.json`](deployments/base-fork.json) — never hardcoded.

---

## Layout

| Path | What |
|---|---|
| [`contracts/`](contracts/) | ERC-4626 vault, factory, agent authorization (Foundry) |
| [`agent/`](agent/) | Model seam, output validation, mandate, decision loop, FastAPI |
| [`data/`](data/) | Source registry, Graph adapters, MCP server, x402 |
| [`venues/`](venues/) | Uniswap and Aqua/SwapVM adapters |
| [`web/`](web/) | Next.js dApp — genesis chat, deposit/withdraw, decision feed |
| [`packages/schema/`](packages/schema/) | The frozen cross-component interface |

Each directory has a `README.md` describing its public interface. The build was done by five agents
working in parallel with strict component isolation — [`INSTRUCTIONS.md`](INSTRUCTIONS.md) has the
rules, [`docs/active-work.md`](docs/active-work.md) has the coordination record, and
[`docs/build-log.md`](docs/build-log.md) explains why each significant decision was made.

## Run it

See [`docs/setup.md`](docs/setup.md). Short version:

```bash
cp .env.example .env          # fill UNISWAP_API_KEY, BASE_RPC_URL, GRAPH_API_KEY
uv sync --all-extras
./scripts/anvil-fork.sh                                  # Base fork
uv run uvicorn agent.api.app:app --port 8000             # agent
pnpm install && pnpm --filter @curator/web dev           # dApp on :3000
```

Tests: **76 Foundry** (7 against real Base state) and **414 Python**.

```bash
uv run pytest packages/schema/python agent data venues
cd contracts && forge test --fork-url $BASE_RPC_URL
```

## Design notes

**The mandate is soft and mutable only by the agent.** It is not enforced on-chain; its keccak256
hash is recorded at vault creation so a depositor can verify the mandate they were shown is the one
deployed. The human deployer cannot change it after genesis. This is a deliberate scope choice —
the trust model rests on the agent, and we did not build a human backstop.

**Output validation is load-bearing, not hygiene.** The agent holds a key and executes directly, and
small open models produce malformed structured output regularly. Every model response is validated
against a JSON Schema and against the mandate's own constraints, with the validation error fed back
on retry ([`agent/model/validation.py`](agent/model/validation.py)). Rejected decisions are kept in
the journal rather than discarded — they are the evidence the layer is doing work.

**The decision feed is the product.** Every cycle renders as *data consulted, with per-fact
provenance → the curator's reasoning verbatim → the calldata and transaction hashes*. An autonomous
agent moving other people's money should be legible, and `facts_used` resolves every number the
agent cites back to the source that reported it.
