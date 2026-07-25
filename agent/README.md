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
  validation.py      ★ four-layer validation + reject-and-retry
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

**Complete:** all frozen routes in both modes · four-layer output validation with reject-and-retry ·
mandate store, hashing and amendment · the decision cycle with cooldown, slippage and stale-quote
enforcement · the append-only journal · `VaultClient` on web3.py against Lane A's published ABIs ·
live genesis. 78 tests green, ruff clean, no network needed to run them.

**Not yet verified — read this before the demo:**

- **The live model path has never run against a real model.** There is no Ollama on the build
  machine (`ollama` is not on PATH and nothing is listening on 11434). Every layer around the model
  is tested via the scripted backend, and `ModelUnavailable` is handled correctly, but how often a
  real `qwen2.5:14b-instruct` needs a retry is unmeasured. **First job for whoever has a GPU:**
  `ollama serve && ollama pull qwen2.5:14b-instruct`, then `AGENT_MODE=live` and
  `POST /vault/{addr}/tick`. Expect the retry counter to be non-zero; that is the honest cost and it
  is displayed on purpose.
- **`Web3VaultClient` has not been run against a live fork.** It is written against Lane A's
  published ABI (`executeBatch`, `holdings`, `createVault`) but no anvil fork was up during this
  lane's build. Live mode falls back to the stub client when `AGENT_PRIVATE_KEY` is unset or the RPC
  is unreachable, and `GET /health` reports `degraded` when that happens — check it first.
- **`VAULT_FACTORY_ADDRESS` must be set** for live genesis to deploy a real vault. Lane A's deploy
  script writes the address into `deployments/base-fork.json`.

Lane plan: [plans/2026-07-25-lane-b-agent.md](../plans/2026-07-25-lane-b-agent.md).
