# `/agent` — the agent harness (Lane B)

## Purpose

The runtime scaffold around the LLM that curates a vault. It owns the model seam, **output
validation**, the mandate, the decision loop, the chain client, and the HTTP surface the dApp talks
to.

The agent holds a key and executes directly with no human override after genesis (locked decision,
[plans/initiate_plan.md](../plans/initiate_plan.md) §2). Everything here is shaped by that: the only
thing between a 14B open-weight model's malformed JSON and a signed transaction is this component's
validation layer, so it fails closed and records what it rejected.

---

## Quick start

```bash
uv sync --all-extras          # NOT --extra agent — see the warning below
uv run uvicorn agent.api.app:app --reload --port 8000
```

> ⚠️ **Always `uv sync --all-extras`.** Syncing a subset (`uv sync --extra agent`) *prunes* every
> package outside the named extras from the shared venv, silently uninstalling the other lanes'
> dependencies. Finding discovered by Lane C; it costs ten confusing minutes each time.

Then `http://localhost:8000/docs` for live OpenAPI, or:

```bash
curl localhost:8000/health
curl localhost:8000/vault/0x1111111111111111111111111111111111111111/state
```

No configuration is required. With no `.env` at all it starts in **fixture mode** and serves the
golden fixtures — no Ollama, no RPC, no other lane needed.

---

## Public interface

### The frozen routes

Frozen in master plan §8 and mirrored as zod in `packages/schema/ts/src/index.ts`. **These shapes are
identical in fixture and live mode** — there is no fixture-only endpoint to migrate off later.

| Route | Body / query | Returns |
|---|---|---|
| `POST /genesis/chat` | `{messages: [{role: "user"\|"assistant", content}]}` | `{reply, mandate_draft?}` |
| `POST /genesis/finalize` | `{mandate: Mandate}` | `{mandate_hash, deploy_tx, vault}` |
| `GET /vault/{addr}/state` | — | `VaultState` |
| `GET /vault/{addr}/decisions` | `?limit=` (1–200, default 20) | `AgentAction[]`, newest first |
| `POST /vault/{addr}/tick` | — | `AgentAction` |

Plus three additions that are **not** part of the freeze:

| Route | Returns | Why it exists |
|---|---|---|
| `GET /vault/{addr}/mandate` | `Mandate` | Cross-lane request #5. `VaultState` carries only `mandate_hash`, so the mandate viewer had no source for a vault the browser did not itself create. |
| `GET /genesis/sources` | `{sources[], venues[]}` | The genesis flow asks the user to grant data sources. That list must come from what Lane C actually registered, not a copy hardcoded in the dApp. |
| `GET /health` | see below | Reports **which provider each seam actually resolved to**. |

### Status codes

Ordinary conditions get status codes that say what they are, so Lane E never has to guess from a
500. **A bad *outcome* is not an error** — see the tick table below.

| Code | When |
|---|---|
| `200` | including a tick that held, was rejected, or reverted on-chain |
| `404` | no mandate stored for that vault — it was deployed by another harness, or genesis has not run |
| `422` | malformed address, an incomplete `Mandate` at `finalize`, or `limit` out of range |
| `503` | live mode missing a setting it needs (`AGENT_PRIVATE_KEY`, `VAULT_FACTORY_ADDRESS`); the detail names it |

### Data shapes

Every shape is imported from `packages/schema` — none are redefined here. `Mandate`,
`MarketSnapshot`, `AllocationDecision`, `ExecutionPlan`, `AgentAction`, `VaultState`.

The request/response envelopes (`GenesisChatRequest`, `MandateDraft`, …) live in
[`agent/api/schemas.py`](api/schemas.py) and mirror the zod definitions exactly.

#### `VaultState.share_price` is a ratio × 10¹⁸, not `convertToAssets(1e18)`

The frozen interface disagrees with itself here, so this states which half this API follows
(cross-lane request #50). `vault-state.schema.json` *describes* the field as `convertToAssets(1e18)`
— 6-decimal for a USDC vault — while `fixtures/vault-state.json` *carries*
`1002506265664160401` for 50,000 USDC over 49,875 shares, which is the dimensionless
assets-per-share ratio scaled by 10¹⁸. **This API follows the fixture**, because every lane's tests
validate against fixtures and nothing validates against prose.

| | 50,000 USDC / 49,875 shares | fork vault at 0.999952 |
|---|---|---|
| this API, and the golden fixture | `1002506265664160401` | `999952000000000000` |
| `convertToAssets(1e18)` on-chain | `1002506` | `999952` |

Neither is wrong — they are the same number in different units, and the second is the first
truncated at 12 digits. **Both are ~10¹² apart but not exactly**, which is the practical argument
for the 18-decimal form: at 6 decimals a USDC vault's share price cannot move until it has gained
0.0001%, so early performance reads as a flat line.

To compare against the chain, divide by 10¹². To go the other way, don't — the precision is gone.
`agent/performance/recorder.py` does this conversion in one place (`share_price_in_asset_units`),
because `PerformancePoint.share_price` **is** specified in asset units, and conflating the two once
already cost a 10¹² error.

### Two wire-format guarantees Lane E can rely on

These are enforced by tests, because both are legal JSON Schema and still break zod in a browser:

1. **Every datetime is UTC with a `Z` suffix.** `z.string().datetime()` rejects `+01:00` offsets and
   bare naive timestamps. A plain `datetime.now()` on the Lisbon demo machine produces the former, so
   all timestamps go through [`agent/clock.py`](clock.py).
2. **No response contains a JSON `null`.** zod's `.optional()` accepts a missing key but rejects an
   explicit null. Every route sets `response_model_exclude_none=True`; fields that are genuinely
   nullable in the contract (`AgentAction.error`, `Holding.committed_to_venue`) are `.nullable()`
   *with a default* on the zod side, so omission is correct for them too.

`test_api_routes.py` asserts both over every leaf of every response.

### `GET /health`

```json
{ "status": "ok", "mode": "live", "data_registry": "curator_data:build_registry",
  "venue_registry": "venues:get_venue", "model_backend": "ollama:qwen2.5:3b-instruct-q4_K_M",
  "model_reachable": true }
```

`status` is `degraded` whenever **live mode is not actually live** — a registry that failed to
import, or a model that is not pulled. `data_registry` / `venue_registry` name the resolved ref, or
the ref that was tried plus why it failed.

`model_reachable` answers the question a plain ping cannot: **`ollama serve` responds happily with
nothing pulled**, so a server-is-up check reads green right until the first tick dies with
`model not found`. Only probed in live mode (fixture mode calls no model), and omitted when it could
not be determined.

A live run quietly serving fixture numbers, or pointed at a model that was never pulled, is exactly
what this endpoint exists to make visible. **Check it before believing a demo.**

---

## Configuration

All optional. Defaults give a working fixture-mode server.

| Var | Default | Meaning |
|---|---|---|
| `AGENT_MODE` | `fixture` | `fixture` \| `live`. Swaps dependencies only, never route behaviour. |
| `AGENT_DATA_REGISTRY` | — | `module:attribute` for Lane C's registry, e.g. `data.registry:registry` |
| `AGENT_VENUE_REGISTRY` | — | `module:attribute` for Lane D's venues |
| `AGENT_CORS_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000` | Comma-separated dApp origins |
| `MODEL_NAME` | `qwen2.5:14b-instruct` | Served model |
| `AGENT_MODEL_BACKEND` | `ollama` | `ollama` \| `vllm` |
| `OLLAMA_BASE_URL` | `http://localhost:11434/v1` | OpenAI-compatible endpoint |
| `AGENT_MAX_VALIDATION_RETRIES` | `3` | Attempts before a cycle is recorded `rejected` |
| `ANVIL_RPC_URL` | `http://localhost:8540` | Chain endpoint |
| `AGENT_PRIVATE_KEY` | — | The curator's key. Required in live mode. |
| `AGENT_STATE_DIR` | `.agent-state/` | Persisted mandates and action journals (gitignored) |

---

## Dependencies

**On other lanes — all late-bound, none imported at module scope.**

`import agent` never transitively imports another lane. Providers are resolved from a
`"module:attribute"` config string on first use ([`agent/providers/resolve.py`](providers/resolve.py)),
and anything that fails to resolve degrades to a fixture provider with a warning rather than taking
the API down.

| Lane | How it reaches us | If absent |
|---|---|---|
| **C** data | `AGENT_DATA_REGISTRY` → a `DataSourceRegistry` | `FixtureDataRegistry` over the golden snapshot |
| **D** venues | `AGENT_VENUE_REGISTRY` → key→`Venue` lookup | `FixtureVenueRegistry` over the golden plan |
| **A** contracts | ABIs read from `contracts/out/**` at runtime | minimal built-in ABI, stub client |

**So: Lane C and Lane D each cost this lane one environment variable and zero code changes.**
Both are wired and verified against what those lanes actually published — set:

```bash
AGENT_DATA_REGISTRY=curator_data:build_registry
AGENT_VENUE_REGISTRY=venues:get_venue
```

`agent/tests/test_integration_lanes.py` binds to both for real and asserts Lane C's registry
satisfies `DataSourceRegistry`, that its sources cover what the golden mandate grants, that Lane D's
adapters satisfy `Venue`, and that a full cycle runs across both. It **skips** rather than fails when
a lane is absent, so this suite still runs from a fresh clone with only `/agent` installed.

The venue ref accepts three shapes — a mapping, an object with `.get(key)`, or a bare lookup function
(what Lane D publishes) — so neither lane had to change anything to be consumable.

External: `fastapi`, `uvicorn`, `httpx`, `web3`, `pydantic`, `curator-schema`.

---

## How data sources are chosen

The mandate's `permitted_data_sources` is a list of **registry keys**, and it is the whole access
control mechanism — a source not named there is never consulted:

```python
snapshot = await registry.snapshot(mandate.permitted_data_sources, mandate.constraints.allowed_assets)
```

That is the same mechanism as "the user selects which data sources the agent may consult" at genesis.
There is no second concept and no source-specific code in this lane: **granting a source is a mandate
edit, not a code change.** The harness never imports a source module, never names one in code, and
cannot tell Messari from Chainlink.

---

## Assumptions & invariants

Things a caller may rely on:

- **`POST /tick` always returns an `AgentAction`.** A cycle that held, was rejected at validation, or
  reverted on-chain is a *successful request* describing that outcome. The route only errors if the
  harness itself could not run — so the dApp renders a feed entry, never a toast.
- **Rejected decisions are kept and returned.** `status: "rejected"` means output validation stopped
  it and nothing reached the chain. These carry no `plan` and no `tx_hashes`, and their
  `model.validation_retries` is non-zero. They are evidence, not noise — render them.
- **`decision.facts_used` only ever cites facts present in the same action's `snapshot`.** Enforced
  by validation, so the dApp can safely join the two to draw data → reasoning → transaction.
- **`mandate_hash` is real in both modes.** keccak256 over a canonical serialization
  ([`agent/mandate/hashing.py`](mandate/hashing.py)): UTF-8 JSON, sorted keys, no whitespace, unset
  optionals omitted. The value shown at genesis is the value committed on-chain, and identical inputs
  hash identically on any machine.
- **The vault is sole custodian.** `VaultState.holdings` is the complete position picture even with
  Aqua strategies open; `committed_to_venue` flags encumbrance, not location.
- **`GET /vault/{addr}/state` echoes the address you asked for**, so the dApp never renders a
  different vault than the URL says.

Things a caller must guarantee:

- `{addr}` is a 0x-prefixed 40-hex-character address, or the route returns `422`.
- `POST /genesis/finalize` takes a **complete** `Mandate`, not a draft — it is validated against the
  full frozen schema before anything deploys, because the mandate is immutable to humans afterwards.

---

## What one tick actually does

`POST /vault/{addr}/tick` runs [`agent/loop/cycle.py`](loop/cycle.py):

```
mandate -> vault state -> market snapshot -> model -> validation
        -> venue plan -> executeBatch -> journal
```

**Every path produces and journals an `AgentAction`; the route never errors on a bad outcome.** The
five statuses mean five different things, and the difference is the point:

| Status | Means | Reached the chain? |
|---|---|---|
| `executed` | the plan was submitted | yes |
| `held` | the agent chose not to act, or the mandate cooldown is running | no |
| `rejected` | output validation or a mandate limit stopped it | **no** |
| `failed` | the model, a data source or the chain broke | maybe, partially |

`rejected` is not an error — it is the safety layer working, and it carries no `plan` and no
`tx_hashes`. `failed` means something was unreachable. A dead Ollama is `failed`, never `rejected`;
conflating them would make the feed misreport why a tick produced nothing.

Two mandate limits are enforced outside the model's output because they cannot be judged from it
alone: the **rebalance cooldown** (checked *before* the model is called — asking it to decide and
then ignoring the answer is worse than not asking) and the **slippage ceiling**, which only becomes
knowable once a venue has quoted. A plan whose quote has expired is refused rather than submitted.

A plan's steps go to the chain as a single `executeBatch`, so a tick lands complete or not at all —
the vault is never left in a half-applied state no decision authored.

## The six validation layers

The only thing between a 3B model's output and a signed transaction. Each layer emits a *different*
retry hint, because a message naming the breach and its limit gets fixed on the next attempt while
"invalid output, try again" burns the tick.

| # | Catches | Told to the model |
|---|---|---|
| 1 extract | fences, prose, `<think>`, trailing commas | "return only a JSON object" |
| 2 schema | wrong types, unknown fields, bad enums | the pydantic error, compacted, **naming only the union variant it attempted** |
| 3 mandate | forbidden asset, weights ≠ 1, too many actions | the breach *and* the limit |
| 4 grounding | citing facts absent from its snapshot | the invented ids *and* the real ones |
| 5 direction | selling an asset already below target | which side is past target, and which way to swap |
| 6 outcome | where the trade **lands** — cash floor, position cap, overshoot | the resulting weight vs the limit |

**Layers 5 and 6 exist because the loop executed real transactions that were wrong and layers 1–4
passed them, correctly.** The decisions were internally consistent in every respect except the one
that decides whether they make money: mandate limits were being checked against what the model
*declared it wanted*, never against what its trade would *do*. Both compare the decision to reality
using the vault's own `value_in_asset` — the Chainlink figure `totalAssets()` is built from — so they
agree with the contract rather than forming a second opinion.

Both stay silent where they cannot judge honestly: no `target_allocations`, an unpriced holding, an
empty vault, an Aqua ship (which posts liquidity rather than changing composition), or a swap sized
in token units, which cannot be projected without a price.

All six have been observed rejecting live, each producing a journaled `AgentAction(status="rejected")`
with no plan and no transaction.

## What fixture mode serves

Fixture mode is the default and is a first-class path, not a placeholder.

- The decision feed **covers every status** — `executed`, `held`, `rejected`, `failed` — because
  Lane E has to render all of them and discovering the rejected state at demo time is too late.
- Timestamps count backwards from *now*, so the feed never reads as stale.
- Executed actions **carry the `MarketSnapshot` they reasoned over**, which the golden
  `agent-action.json` omits — without it the data → reasoning → tx view cannot be built.
- `mandate_hash` is computed for real.

The one thing fixture mode must never do is reach a chain: its `ExecutionPlan` calldata is the
fixture's and is not executable.

---

## Usage example

```ts
// Lane E — the decision feed
const res = await fetch(`${API}/vault/${addr}/decisions?limit=20`)
const actions = z.array(AgentAction).parse(await res.json())

for (const a of actions) {
  if (a.status === 'rejected') renderRejection(a.error, a.model?.validation_retries)
  else renderDecision({
    facts: a.snapshot?.facts.filter(f => a.decision?.facts_used.includes(f.id)),  // provenance
    reasoning: a.decision?.reasoning,
    txs: a.tx_hashes,
  })
}
```

```python
# Any lane — drive a cycle directly, no HTTP
from agent.api.deps import get_vault_service
action = await get_vault_service().tick("0x1111111111111111111111111111111111111111")
```

---

## Layout

```
config.py            env-driven settings; every path derived from the repo root
clock.py             UTC-with-Z timestamps — the Python→TS format trap, in one place
fixtures.py          typed access to packages/schema/fixtures
model/
  openai_compat.py   one HTTP client for every OpenAI-compatible endpoint
  backends/          ollama · vllm · scripted (tests) — one line each in the table
  extraction.py      recovering JSON from fences, prose and <think> blocks
  validation.py      * six-layer validation + reject-and-retry
  prompts/           curator and genesis prompts, kept out of the calling code
mandate/
  hashing.py         canonical JSON → keccak256 (identical in both modes)
  constraints.py     what the mandate permits — testable without a model
  store.py           atomic per-vault persistence
  amend.py           agent-side mutation, with invariants code can enforce
loop/
  engine.py          DecisionEngine: mandate + snapshot → validated decision
  planning.py        venue intents → one checked ExecutionPlan
  cycle.py           one tick, every path journaled
  store.py           append-only AgentAction journal
chain/
  abi.py             loads Lane A's published ABIs, with a minimal fallback
  vault_client.py    web3.py — reads state, signs and submits executeBatch
  stub.py            chainless VaultClient for fixture mode and pre-CP1
providers/           late binding to Lanes C and D, with fixture fallbacks
service/             the ports routes depend on; fixture and live implementations
api/                 FastAPI app, routes, request/response schemas
tests/               78 tests — schema conformance, wire format, retries, the cycle
```

## Tests

```bash
uv run pytest agent -q      # 109 passed, 3 skipped, ~4s — no network, no model, no chain
uv run ruff check agent
```

Three cross-lane tests reach the live Graph gateway and are skipped by default; without a credential
they cost ~12s of connection timeouts each and make the suite depend on having internet. Run them
deliberately when a key lands:

```bash
AGENT_TEST_NETWORK=1 uv run pytest agent/tests/test_integration_lanes.py
```

Measure what a decision actually costs on the current machine — the number that decides whether the
demo feels alive, retries included:

```bash
uv run python -m agent.bench --model qwen2.5:3b-instruct-q4_K_M --runs 3
```

Payloads are validated against `packages/schema/*.json` — the JSON Schema source of truth — not
against the pydantic mirror, so the tests prove agreement with the contract Lane E's zod was written
from rather than agreement with ourselves.

## Status and known gaps

**Complete:** all frozen routes in both modes · six-layer output validation with reject-and-retry ·
mandate store, hashing and amendment · the decision cycle with cooldown, slippage and stale-quote
enforcement · the append-only journal · `VaultClient` on web3.py against Lane A's published ABIs ·
live genesis. 192 tests green, ruff clean, no network or model needed to run them.

**The vertical slice runs end to end on live data.** With `AGENT_MODE=live` and both provider refs
set:

```
health   : ok — curator_data:build_registry · venues:get_venue · model_reachable
genesis  : mandate hashed, vault deployed, mandate persisted
tick     : held in 55.5s, 0 retries, 3 live Graph facts consulted, 2 sources degraded
           cites messari:yield:moonwell/usdc, :tvl:, :utilization:
feed     : 1 entry rendered from the journal
```

Those fact ids come from Lane C's **live** Messari subgraph query, not a fixture — the demo-path
requirement. The two `snapshot.errors` are the Token API without a credential, degrading the snapshot
exactly as designed rather than failing the tick. A tick is slower than the raw model benchmark
because it also pays for the Graph round trip.

**Verified against the real fork.** `Web3VaultClient.state()` reads Lane A's deployed vault
`0x0E2c…B5d1` on the anvil fork correctly: 2,500 USDC, share price exactly `1e18`, ERC-20 symbols
resolved, `mandate_hash` schema-valid. Reading a real contract is what caught the `bytes.hex()`
prefix bug — `to_hex_string` now normalizes it, with tests.

> ⚠️ **`AGENT_PRIVATE_KEY` must be the account that actually holds `AGENT_ROLE`.** On the current
> fork that is **anvil account #1** (`0x7099…79C8`, key
> `0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d`) — *not* account #0. The
> wrong key reads state fine and then reverts every `executeBatch` on an AccessControl check.
> `GET /vault/{addr}/state` reports the vault's expected `agent`; compare it against the address the
> harness logs at startup.

**The model is real and measured.** `qwen2.5:3b-instruct-q4_K_M` on this machine (i5-8265U, no GPU,
DDR4-2400):

| | |
|---|---|
| median validated decision | **32.7s** (32.1–33.1s) |
| validation retries | **0 across every run** |
| tokens | 983 in / 270 out |

Zero retries is why this model was chosen. Token generation is memory-bandwidth-bound, so a 14B at Q4
streams ~9 GB per token and costs minutes per tick regardless of how well it reasons — at this scale
**reliability at structured output beats capability.** Re-measure on any other machine before
trusting a different tag:

```bash
uv run python -m agent.bench --model <tag> --runs 3
```

> ### ⚠️ Before a demo: `OLLAMA_KEEP_ALIVE=30m`
>
> **Ollama evicts an idle model after ~5 minutes.** The next tick then pays a ~2 GB reload from disk
> before it can generate — a warm decision measured 33s, the first cold one blew past a 120s budget
> and surfaced as `ModelUnavailable`, which reads as *"the server is down"* when the server is merely
> slow. That is a demo-shaped failure: it happens precisely when the stack has been sitting idle
> while someone explains the architecture.
>
> Two mitigations, both applied:
> - `model_timeout_s` now defaults to **300s** so a cold load completes rather than being misreported.
> - Set **`OLLAMA_KEEP_ALIVE=30m` on the Ollama server** (it is a server-side environment variable).
>   Passing `keep_alive` in the request body does **not** work — verified: Ollama's
>   OpenAI-compatible endpoint silently ignores it and the TTL stays at 5 minutes.
>
> `curl localhost:11434/api/ps` shows what is resident and when it expires.

> **The model's prose is not as trustworthy as its decisions.** On the first live run it cited fact
> `f6` — a $12.4M *liquidity* figure — as "the highest headline APY of 10.43%". A real id, an
> invented value. It passed all four validation layers, because grounding catches fabricated **ids**,
> not fabricated **numbers**. The fact table was rewritten to make units unmisreadable and the
> misread stopped, but a 3B still makes qualitative errors (it called 91% utilization "low"). The
> *decision* was safe and mandate-legal throughout — which is exactly why constraints are enforced in
> code rather than trusted to the reasoning. Read the feed with that in mind.

**Still not verified:**

- **No write has been submitted on-chain.** `state()` is verified against Lane A's deployed vault and
  the `executeBatch` encoding round-trips byte-identically, but the first real submission will be the
  first real submission.
- **`VAULT_FACTORY_ADDRESS` must be set** for live genesis to deploy. Lane A's deploy script writes
  it to `deployments/base-fork.json` — currently `0x0282…F302D`.

Lane plan: [plans/2026-07-25-lane-b-agent.md](../plans/2026-07-25-lane-b-agent.md).
