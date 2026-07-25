# Build log

Append-only, **newest at the top**. Every non-trivial change gets an entry: what changed, **why**
(the important part), and what alternatives were rejected. Never rewrite another agent's entry.

This log is also part of the ETHGlobal audit trail — it evidences that decisions were made during
the hackathon window.

---

## 2026-07-25 — Lane D: Uniswap taker path live, and three findings that contradict our fixtures

**What changed.** `/venues` scaffolded and the Uniswap adapter finished end to end: `config.py`,
`addresses.py`, `abi.py`, `errors.py`, `registry.py`, and `uniswap/{client,plan,venue}.py`.
18 tests green, 4 of them against the live gateway.

**Three things the live API does that our written assumptions did not.** All found in the first
hour, because the alternative is finding them at CP2 with the vertical slice on the line.

1. **`routingPreference: CLASSIC` is rejected** with HTTP 400 `"routingPreference" must be one of
   [BEST_PRICE, FASTEST]` — yet a *successful* response echoes `"routing": "CLASSIC"` back. The
   value you read out of a response is not a value you may send. Headed for `FEEDBACK.md`; there is
   a regression test pinning it so we notice if they fix it.
2. **The swap target is `0x6fF5693b…D299b43`, not the `0x2626664c…e481` UniversalRouter** in
   `packages/schema/fixtures/execution-plan.json`. Had we trusted the fixture, every swap would have
   reverted on an allowlist check. Filed to Lane A as cross-lane request 7.
3. **`swap.value` comes back hex-encoded (`"0x00"`)** while `ExecutionPlan.value` requires
   `^[0-9]+$`. A straight copy produces a plan that passes casual inspection and fails schema
   validation. Normalised in `plan.py::_to_int`, with a test.

**The design decision that matters: how a contract vault gets a Permit2 allowance.** The quote
response hands back a `permitData` block to sign as an EIP-712 `PermitSingle`. **The vault cannot
sign anything** — it is a contract, it holds no key, and the agent's key is external to it. Options
were (a) implement ERC-1271 so the vault validates a signature the agent produces, or (b) use
Permit2's other, signature-free entry point, `approve(token, spender, amount, expiration)`, which is
an ordinary call the vault can make through `execute()`. **Chose (b).** It needs nothing from Lane
A beyond the generic `execute()` that already exists, whereas (a) would have put a contract change
on Lane A's critical path for no functional gain. Confirmed viable by observing `POST /swap` return
200 with no signature supplied. Every plan is therefore three ordered steps: ERC-20 approve → Permit2
approve → router execute.

**Approvals are re-emitted on every plan** rather than checked against current allowance first. A
redundant approve costs gas and always succeeds; a missing one reverts the whole plan. Given the
vault executes plans rarely and atomically, that is the right side to err on. `include_approvals=False`
exists for a vault with standing allowances.

**Why no web3.py.** This lane needs ABI encoding, keccak, and eventually one `eth_call` — all of
which are a few lines over the `httpx` client already in the tree. `eth-abi` + `eth-utils` are a
fraction of the dependency weight, and the root `pyproject.toml` already documents a broken global
web3 breaking pytest collection. Added as a `venues` extra, following the per-lane extras pattern
Lane B established rather than inventing a second convention.

**Rejected: a standalone `venues/pyproject.toml` with its own workspace.** Written first (while the
root config was broken) and then deleted once Lane B fixed root. It worked, but it meant a second
`.venv` in the tree and a macOS teammate at 10:00 guessing which one to activate. One venv,
per-lane extras, `uv sync --all-extras`.

**Client/translator split.** `client.py` speaks HTTP and knows nothing about our schema; `plan.py`
speaks our schema and never touches the network. That is what lets the plan builder be tested
against recorded responses — the offline suite covers step ordering, unit conversion and allowlist
enforcement with no quota and no market dependency — and it confines a future Uniswap API change to
one file.

---

## 2026-07-25 — Lane B phases 3–6: the decision cycle, the journal, and the signing chain client

**What changed.** The loop is real. `agent/loop/` (engine, planning, cycle, journal), `agent/mandate/`
(store, amendment), `agent/chain/` (ABI loading, web3 client, stub), `agent/service/live.py` wiring
it behind the frozen routes, and the genesis prompt. 78 tests green.

**Why every path through the cycle returns a journaled `AgentAction` instead of raising.** This is a
deliberate contract with Lane E: `POST /tick` renders a feed entry no matter what happened, so the
dApp never shows "something went wrong" — the feed says what went wrong and the record persists.
Keeping the five statuses distinct is what makes that honest, and the split that matters most is
`rejected` vs `failed`. A rejection means validation or a mandate limit stopped it and **nothing
reached the chain**; a failure means the model, a data source or the chain broke. A dead Ollama is
`failed`, never `rejected` — reporting an unreachable server as a validation failure would make the
feed lie about the one thing this project is arguing for.

**Why a whole plan is one `executeBatch` rather than N calls to `execute`.** Lane A published both.
Submitting steps separately lets a plan land *half* applied — approval granted, swap reverted —
leaving the vault in a state no decision authored and no depositor was shown. `executeBatch` makes
the tick atomic and yields one transaction hash, which is also what the feed wants. The `VaultClient`
port warns that a partially-applied plan is an outcome the caller must record; making it impossible
is better than recording it accurately.

**Why the rebalance cooldown is checked *before* the model is called.** The alternative is to ask for
a decision and then refuse to act on it, which spends a model call to learn something already known
and produces a feed entry where the agent's stated intent contradicts what happened. Only `executed`
cycles start a cooldown — holding or being rejected did not move capital, so they must not block the
next tick. The snapshot is still taken and shown, so a cooldown hold still displays what was observed.

**Where each mandate limit is enforced, and why they are not all in one place.** Asset lists, weight
sums, position caps, the cash floor and action counts are checkable from the decision alone, so they
live in `mandate/constraints.py` and run inside validation. **Slippage cannot be** — the decision
expresses intent and only the venue knows the price impact of filling it — so it is checked on the
merged plan in `loop/planning.py`. Quote staleness likewise. Splitting them by *what information the
check needs* keeps the constraint module testable with no venue, no model and no event loop.

**Why plans are merged into one.** `AgentAction.plan` is a single `ExecutionPlan` but a mandate may
allow several intents per tick. Merging is the honest reading rather than a workaround: the vault
executes a flat ordered sequence of calls, so "the plan for this tick" genuinely is the concatenation.
Step order is preserved because approvals must precede the calls that need them, and the merged plan
reports the *worst* slippage and *earliest* expiry of its parts, since those are what actually bind.

**Agent-side mandate amendment, and the invariants free text cannot enforce.** §2 locks the mandate
as mutable *only by the agent*. An agent that can rewrite its constraints can rewrite them away, and
`update_rules` is prose that no code can check. So four structural invariants are enforced regardless
of what the model asks for: `base_asset` can never change (the ERC-4626 asset is fixed at deployment,
and every share-price calculation would silently change meaning), the base asset must stay in
`allowed_assets`, `version` is assigned by the harness and always increments, and the merged result
must satisfy the full schema or it is rejected whole. A refused amendment does not fail the tick —
the decision may still be sound under the existing mandate — but it is logged.

**Reading `contracts/out/` is integration, not a boundary crossing.** `docs/active-work.md` states
that directory is committed on purpose as Lane A's way of publishing ABIs. So the harness loads the
compiled artifact and never opens `contracts/src/`: the ABI is the contract, the Solidity is Lane A's
business. A minimal fallback ABI covers the case where the artifact is missing (fresh clone, mid
`forge build`) so the tests still run. Similarly, the base-asset address is read from
`deployments/base-fork.json` rather than hardcoded — a chain constant in the harness would drift.

**A fixture bug worth recording because it would have surfaced only this afternoon.** The golden
`execution-plan.json` carries `quote_expires_at: 2026-07-25T14:06:30Z`. The harness refuses to submit
a stale quote, so replaying that timestamp verbatim made fixture mode work all morning and start
rejecting *every* tick after 14:06 today — during the demo window. The fixture venue now re-stamps
quotes relative to now, the same fix already applied to the fixture decision feed. General lesson for
the other lanes: **golden fixtures contain absolute timestamps, and anything that compares them to
`now` needs them re-stamped, not replayed.**

**Share price is computed, not read from `convertToAssets`.** Derived from `totalAssets`,
`totalSupply` and both decimals so it matches the golden fixture's definition exactly — assets per
whole share in 1e18 fixed point. Two lanes disagreeing about what "share price" scales to is a bug a
depositor sees before we do.

**Genesis fails differently from the decision loop, on purpose.** A malformed genesis response
degrades to "show the text, skip the draft update": a human is present, can see what happened and can
restate themselves. A malformed *decision* has nobody in the loop, so rejection is the only safe
answer. Same harness, opposite posture, because the trust model differs on either side of genesis.
`finalize` is strict regardless — it validates the full `Mandate` before deploying, since the mandate
becomes immutable to humans the moment it does.

**Known gap, stated plainly:** there is no Ollama on this machine (`ollama` is not on PATH, nothing
listening on 11434), so **the live model path has never run against a real model**, and no anvil fork
was up, so `Web3VaultClient` has not executed against a real chain. Everything around both is tested
via the scripted backend and the stub client, and both degrade visibly rather than silently —
`GET /health` reports `degraded` whenever live mode falls back. Flagged in `agent/README.md` under
"known gaps" as the first job for whoever has a GPU and a fork.

---

## 2026-07-25 — Lane B phase 2: the model seam and the validation layer that guards the key

**What changed.** `agent/model/` — an OpenAI-compatible client shared by an Ollama and a vLLM
backend, a scripted backend for tests, the curator prompt, and the four-layer output validator with
reject-and-retry. `agent/mandate/constraints.py` holds the mandate checks. 40 new tests; 60 green.

**Why validation is four separately-named layers instead of one `try: parse`.** The layering exists
to make *retries actually work*. A model told "invalid output, try again" learns nothing and burns
the tick; a model told "cbETH is not permitted; the mandate allows only USDC, WETH" fixes it on the
next attempt. So each layer produces a message written to be fed straight back:

| Layer | Catches | Told to the model |
|---|---|---|
| 1 extract | fences, prose, `<think>`, trailing commas | "return only a JSON object" |
| 2 schema | wrong types, unknown fields, bad enums | the pydantic error, compacted to 6 lines |
| 3 mandate | forbidden asset, weights ≠ 1, too many actions | the breach **and the limit it broke** |
| 4 grounding | citing facts that were never in the snapshot | the invented ids **and the real ones** |

Layer 3 reports *every* breach at once rather than the first: one retry that fixes three problems
beats three retries.

**Why the correction is appended as a conversation turn rather than a rewritten prompt.** The retry
puts the model's own rejected output back as an `assistant` message and the failure as a `user`
message. Models correct a visible, concrete mistake far more reliably than they avoid an abstract one
described in a system prompt, and it leaves the original task text intact. The echoed output is
capped at 1200 characters so three failures cannot crowd the real prompt out of a small context
window.

**Why grounding is a validation layer and not a UI nicety.** `facts_used` must cite real `Fact.id`s
from the snapshot the model was given. Two things ride on it: the dApp joins facts → reasoning → tx
hash to show *why* the agent acted, and a model citing `f9` when the snapshot stopped at `f6` has
demonstrably stopped reading its inputs. That is the cheapest signal available that the reasoning is
confabulated — and a confabulated rebalance spends real money. Also rejected: any non-`hold` action
citing no facts at all. Holding while citing nothing stays legal, because "nothing could be read this
tick" is an honest reason to hold.

**The golden fixtures settled a constraint ambiguity that would otherwise have been a coin flip.**
The golden mandate sets `max_position_pct: 0.6` and `min_cash_pct: 0.2`; the golden decision
allocates USDC 0.70 / WETH 0.30 with `base_asset: "USDC"`. Reading `max_position_pct` as a cap on
*every* allocation makes the shared fixture violate the shared mandate. So it caps **risk positions**
— non-base assets — while the cash leg is governed from the other side by `min_cash_pct`. WETH 0.30 ≤
0.60 and USDC 0.70 ≥ 0.20, consistent. A test asserts the golden decision is legal under the golden
mandate, so if another lane ever reads these fields differently the disagreement surfaces here rather
than as a mystery rejection at demo time.

**Why coherence between `action` and `venue_intents` is enforced.** A `rebalance` carrying no intents
executes nothing while reporting that it acted; a `hold` carrying swap intents trades while claiming
to have stood still. Both are schema-valid and both make the decision feed lie to a depositor, which
is the one thing this product cannot afford — the feed *is* the product.

**Why the backend split is one hook and not two HTTP clients.** The only real difference between
Ollama and vLLM is how you request structured output: Ollama takes `response_format: {"type":
"json_object"}` (syntax only), vLLM accepts full JSON-Schema-guided decoding. That is a single
callable passed into the shared client, so each backend file is a dozen lines. Neither hint is
treated as a guarantee — `ports.ModelBackend` says so and it is true: guided decoding can produce a
perfectly well-formed decision that breaks the mandate, so layers 3 and 4 run identically on both.

**Why `scripted` is not in the backend registration table.** It is a real `ModelBackend` (the harness
cannot tell it from Ollama, so tests exercise the true code path), but it is constructed directly and
deliberately *not* selectable via `AGENT_MODEL_BACKEND`. Nothing should be able to put a canned model
in front of a live vault by setting an environment variable.

**`ModelUnavailable` is distinct from a validation failure**, and the cycle records it as `failed`
rather than `rejected`. Conflating "the server is down" with "the model is unreliable" would make the
decision feed misreport why a tick produced nothing.

**Rejected:** relying on `response_format` / guided decoding *instead* of validating — it constrains
syntax and at best shape, never mandate legality, and the agent holds a key. Also rejected: repairing
model JSON beyond trailing commas. Silently "fixing" a malformed decision is exactly the risk the
layer exists to prevent; only a repair that cannot change semantics is acceptable.

---

## 2026-07-25 — Lane B phase 1: frozen routes live on fixtures; late binding to Lanes C and D

**What changed.** `/agent` stood up: config, typed fixture access, the FastAPI app with all five
frozen routes from §8 plus `GET /health`, `GET /genesis/sources` and `GET /vault/{addr}/mandate`,
fixture-mode services behind a port, canonical mandate hashing, and 20 tests. Lane E is unblocked
(cross-lane request #3).

**Why route handlers depend on a service port rather than calling the loop.** The obvious shape is
"routes call the decision loop, and fixture mode is a branch inside them." Rejected: the branch then
lives in every handler and the fixture path drifts from the live path exactly where it matters. A
`VaultService` / `GenesisService` Protocol means `agent/api/deps.py` is the *only* module that knows
which mode we are in, and the endpoint Lane E integrates against at hour 2 is byte-identical to the
one running at the demo. There is no fixture-only endpoint to migrate off.

**Why other lanes are resolved from a `"module:attribute"` string instead of imported.** This is the
most consequential decision in the lane. Rule 7 forbids importing another lane's internals, and
neither Lane C nor Lane D existed when this was written. Options:

- *Import Lane C's registry directly once it lands* — violates Rule 7, and makes `import agent` fail
  whenever a neighbouring lane is mid-edit. With five instances pushing concurrently that is a
  guaranteed outage of the API Lane E develops against.
- *Copy a minimal interface and adapt later* — that is schema drift with extra steps.
- *Late binding from config* ← **chosen.** `AGENT_DATA_REGISTRY=data.registry:registry` is imported
  on first use, checked against the `DataSourceRegistry` Protocol, and **any** failure — missing
  module, bad attribute, wrong shape — degrades to the fixture provider with a warning instead of
  raising. Lane C and Lane D each cost this lane one environment variable and zero code changes, and
  `import agent` never transitively imports another lane, so the test suite runs with no other lane
  installed. Cost: a typo'd ref fails soft, which is why `GET /health` reports what each seam
  actually resolved to — a live run quietly serving fixture numbers is the failure mode that
  matters, and it is now visible in one curl.

**Why fixture mode serves a feed covering every `AgentAction` status.** The golden fixture is a
single `executed` action. Serving four copies of it would let Lane E ship a decision feed that has
never rendered `rejected` or `failed` — and those states would first appear during the live demo.
Fixture mode therefore synthesizes a hold, a validation rejection and an on-chain failure alongside
the success, with timestamps counting back from *now* so the feed never reads as stale. It also
attaches the `MarketSnapshot` to executed actions, which the golden fixture omits: Lane E's MVP
requires showing data consulted (with provenance) → reasoning → tx hash, and that view is impossible
if the snapshot never crosses the wire.

**Why `mandate_hash` is computed for real in fixture mode.** It would have been easier to return a
constant. But the hash is what a depositor uses to verify the mandate they were shown is the one the
vault was deployed against, so fixture and live must agree byte-for-byte. Canonical form is defined
once in `agent/mandate/hashing.py` — UTF-8 JSON, sorted keys, no whitespace, unset optionals omitted
— and both modes call it. `exclude_none` matters: an explicit `"update_rules": null` must not hash
differently from an absent one.

**Two wire-format traps found by testing rather than at the demo.** Both are legal JSON Schema and
both break zod in the browser while passing any Python-only test:

1. `z.string().datetime()` accepts **only** UTC with a `Z` suffix — it rejects `+02:00` and rejects
   naive timestamps. Pydantic serializes whatever it is handed, so a plain `datetime.now()` on the
   Lisbon demo machine (UTC+1) emits `...+01:00` and Lane E's parser rejects it. All timestamps now
   go through `agent/clock.py`, and a test asserts the `Z` shape on **every** datetime-looking leaf
   of every response, not just the fields a test remembers.
2. zod's `.optional()` accepts a missing key but **rejects an explicit `null`.** Pydantic's unset
   optionals serialize to null by default. Every route sets `response_model_exclude_none=True` and a
   test asserts no response contains a null anywhere. It caught `/health` immediately, which is the
   point — the guard is cheap and the failure it prevents is a demo-time 500 in someone else's lane.

**Why tests validate against `packages/schema/*.json` and not the pydantic models.** Validating a
pydantic-produced payload with pydantic proves only that the harness agrees with itself. The JSON
Schema is the declared source of truth and is what Lane E's zod mirror was written from, so the
tests load the schemas into a `referencing` Registry (they cross-reference by relative URI) and
validate there.

**Additive routes, and why they do not breach the freeze.** `GET /vault/{addr}/mandate` (Lane E's
request #5 — `VaultState` carries only `mandate_hash`, so the mandate viewer had no source),
`GET /genesis/sources` (the user must grant data sources at genesis; that list has to come from what
Lane C registered, not a copy hardcoded in the dApp), and `GET /health`. The freeze prevents
*changing* agreed shapes; adding a route breaks no consumer. All five frozen routes are untouched.

**Rejected:** `pydantic-settings` for config — one more dependency to read a dozen env vars that
`os.environ` plus the already-present `python-dotenv` handles; a dataclass keeps the defaults
readable in one screen.

---

## 2026-07-25 — Lane B: root `uv` workspace config was broken, blocking all three Python lanes

**What changed.** One line in the root `pyproject.toml`:
`curator-schema = { path = "packages/schema/python", editable = true }` →
`curator-schema = { workspace = true }`.

**Why.** `uv sync` failed outright with *"`curator-schema` is included as a workspace member, but
references a path in `tool.uv.sources`. Workspace members must be declared as workspace sources."*
`packages/schema/python` was listed in **both** `[tool.uv.workspace] members` and
`[tool.uv.sources]`, which uv rejects. Nothing Python ran — not Lane B, not C, not D, and not
Wave 0's own conformance test. Workspace members are already editable-installed, so the
`editable = true` was redundant as well as invalid.

**Why I fixed it rather than filing a request.** Rule 7 says stay out of other lanes, and root config
belongs to Wave 0 — but Wave 0 is **released**, so there was no owner to action a request, and three
lanes were dead in the water. Lane C claimed in while I was working and would have hit the identical
wall within minutes; two instances independently patching the same line is exactly the collision
Rule 7 exists to prevent. Fixed once, pushed immediately, and announced in `docs/active-work.md` so
the other lanes pull rather than re-fix. Scope was one line in a shared root file — no lane
directory touched.

**Verified:** `uv sync --extra dev` clean, Python 3.12.13, pydantic 2.13.4, `import curator_schema`
resolves.

---

## 2026-07-25 — Wave 0: interface freeze and scaffolding

**What changed.** Repository foundation for five parallel instances: `CLAUDE.md`, the master build
plan in `plans/`, the frozen interface in `packages/schema/` (six JSON Schemas + pydantic and zod
mirrors + ports + golden fixtures + 22 conformance tests), `docs/`, root config and the anvil fork
script.

**Why a Wave 0 at all.** Rule 7 forbids instances from editing each other's components, but five
lanes still have to agree on the shapes that cross between them. Without one owner defining those
first, each lane invents its own and integration fails at the worst possible time. One hour of
serial work buys parallel work that actually converges.

**Why JSON Schema as source of truth, with pydantic and zod as mirrors.** The stack is split Python
(harness, data, venues) and TypeScript (dApp), so every shape is necessarily declared more than
once. Options considered:

- *Generate both from JSON Schema* — cleanest in principle, but codegen toolchains for pydantic and
  zod each need setup and debugging, and we have 24 hours.
- *Define in pydantic, export JSON Schema, generate zod* — couples the TypeScript side to a Python
  build step, awkward for Lane E working independently.
- *Hand-write all three, verify with shared fixtures* ← **chosen.** Hand-written mirrors read better
  and carry explanatory comments the lanes actually need. The drift risk is real, so it is paid for
  with `test_conformance.py`, which validates every golden fixture against both the JSON Schema and
  pydantic and round-trips pydantic output back through the schema.

**Why `MarketSnapshot` is a flat list of provenance-carrying facts.** The obvious design is a
Graph-shaped response object with fields for yields, TVL and prices. Rejected: it bakes today's data
provider into the type, and the requirement is that Chainlink, Pyth or DefiLlama can be added later
without touching anything else. Instead each source contributes a *partial* list of `Fact`s and the
registry merges them. Sources never see each other, never coordinate coverage, and every fact
carries `source` so the dApp can display provenance. Cost: consumers filter a list instead of
reading named fields. Worth it — adding a provider is now one file plus one registration line, and
the mandate's `permitted_data_sources` is literally the registry lookup, so the "user grants data
sources at genesis" flow needed no separate concept.

**Why `ExecutionPlan` is opaque calldata against an allowlisted target.** Lane A owns `contracts/`
and Lane D owns the venue integrations, but venue calls have to originate from the vault to preserve
Pattern 1 custody. Making the vault aware of Uniswap and Aqua would put venue logic in Lane A's
directory and force the two lanes to edit the same files. Instead the vault exposes one generic
agent-only `execute(target, value, data)` with a target allowlist, and Lane D builds arbitrary
calldata off-chain. Neither lane touches the other, and a third venue becomes an adapter rather than
a contract change. Accepted tradeoff: the allowlist is now a security-critical shared decision, so
it's tracked as cross-lane request #1.

**Why uint256 crosses as decimal strings.** Exceeds float64 and `Number.MAX_SAFE_INTEGER`. Silent
precision loss on a share-price calculation is the kind of bug that surfaces during a demo.

**Why `AgentAction` records rejected decisions.** Discarding them would hide the validation layer's
work. Small open models produce malformed structured output regularly and this agent holds a key, so
evidence that outputs were caught and retried is part of the story, not noise. `validation_retries`
is surfaced for the same reason.

**Environment findings** (recorded so no lane rediscovers them):
- `python` on PATH is the Microsoft Store stub and does not run; real Python is Anaconda 3.12.7. The
  project pins 3.12 via `uv`.
- Two WSL distros exist and the **default (Ubuntu-20.04) is the wrong one** — glibc 2.31 is too old
  for Foundry's prebuilt binaries and its Python 3.8 is below the MCP SDK's ≥3.10 floor. All Foundry
  work goes in Ubuntu-24.04 (glibc 2.39, Python 3.12.3).
- A globally-installed `web3` registers a broken `pytest_ethereum` plugin that breaks pytest
  collection under global Anaconda. The `uv` venv avoids it.
- `jsonschema.RefResolver` is deprecated and resolves cross-schema `$ref`s over the *network*; the
  conformance test uses a `referencing` Registry so refs resolve locally.

**Alternatives rejected on sponsor strategy** (full reasoning in the master plan):
- ENS over Uniswap for the third sponsor slot — Uniswap is load-bearing (an Aqua maker is passive and
  cannot rotate holdings; a taker-side venue is required), and it's $7K across 3 places versus $3K
  across 1. ENS mandate-hash text records are still worth building as narrative, just not submitted.
- Reimplementing SwapVM program encoding in Python — rejected in favour of 1inch's official Solidity
  `ProgramBuilder` read via `eth_call`. Their rules require the official contracts, and hand-rolling
  bytecode encoding under time pressure is how you lose a track.
