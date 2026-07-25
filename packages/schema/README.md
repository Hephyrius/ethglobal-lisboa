# packages/schema — the frozen cross-lane interface

## Purpose

The single definition of every shape that crosses a component boundary. Five Claude Code instances
build this repo in parallel and must not read each other's code ([INSTRUCTIONS.md](../../INSTRUCTIONS.md)
Rule 7), so this package is how they agree on anything at all.

**Frozen, and owned by Lane F for Wave 2.** A lane that needs a change files a request in
[docs/active-work.md](../../docs/active-work.md) — it does not edit this directory. Lane F turns
schema requests round in **30 minutes**; a frozen schema with a slow owner looks unblocked and is
not.

## Layout

```
*.schema.json          SOURCE OF TRUTH — JSON Schema 2020-12
python/curator_schema/ pydantic mirror (models.py) + port Protocols (ports.py)
ts/src/index.ts        zod mirror + inferred TypeScript types
fixtures/*.json        golden fixtures — every lane develops against these
presets/*.json         starting-point mandates offered at genesis, + index.json
python/tests/          conformance: fixtures AND presets satisfy JSON Schema and pydantic
```

Check a change to the TypeScript mirror without needing `web/`:

```bash
uv run pytest packages/schema/python -q                 # 57 tests
pnpm --filter @curator/schema typecheck                 # or: npx tsc --noEmit -p packages/schema/ts
```

The stack is split Python/TypeScript, so each shape is declared three times. That is the accepted
cost of the split; `python/tests/test_conformance.py` is the mitigation. It validates every fixture
against both the JSON Schema and the pydantic model, and checks that a pydantic round-trip still
satisfies the schema — so a change to one representation that isn't mirrored fails immediately
rather than at integration time.

## Public interface

### Data shapes

| Shape | Crosses | Notes |
|---|---|---|
| `Mandate` | genesis → agent → chain (hash) | Soft, LLM-side. Mutable **only by the agent** after genesis. |
| `MarketSnapshot` | data → agent | Source-agnostic. See below — this design is load-bearing. |
| `AllocationDecision` | model → agent | What the LLM must emit. Validated before anything executes. |
| `ExecutionPlan` | venues → agent → vault | Concrete calldata. The Lane A/D seam. |
| `AgentAction` | agent → API → dApp | One decision cycle. Audit trail and demo feed. |
| `VaultState` | chain → agent → dApp | Vault is sole custodian, so `holdings` is the whole picture. |

### Ports (`python/curator_schema/ports.py`)

`DataSource`, `DataSourceRegistry`, `ModelBackend`, `Venue`, `VaultClient`, `DecisionEngine`.
Depend on these Protocols, never on another lane's concrete class. Docstrings there are the spec.

### Frozen API routes

Implemented by Lane B (`agent/api`), consumed by Lane E (`web/`). Request/response shapes are in
the zod mirror. Lane B serves these with fixture data from hour 2 so Lane E is never blocked.

```
POST /genesis/chat          {messages[]}   → {reply, mandate_draft?}
POST /genesis/finalize      {mandate}      → {mandate_hash, deploy_tx, vault}
GET  /vault/{addr}/state                   → VaultState
GET  /vault/{addr}/decisions?limit=        → AgentAction[]
POST /vault/{addr}/tick                    → AgentAction
```

### Mandate presets (`presets/`)

Starting points offered in the genesis conversation and rendered as cards in the dApp. **Both read
the same files**, so the model's recommendation and the button the user clicks cannot diverge.

```python
import json, pathlib
from curator_schema import Mandate

root = pathlib.Path("packages/schema")
index = json.loads((root / "presets/index.json").read_text())
for entry in index["presets"]:
    mandate = Mandate.model_validate(json.loads((root / entry["file"]).read_text()))
    print(entry["key"], "—", entry["headline"], "| tradeoff:", entry["tradeoff"])
```

| Key | Shape | Persona |
|---|---|---|
| `conservative-income` | USDC lending only · 25% cash floor · 10 bps · band 0.02 | *The Treasurer* (low conviction) |
| `balanced-two-asset` | USDC/WETH · 60% cap · 20% floor · 50 bps | none — the control |
| `opportunistic` | 80% cap · 5% floor · 150 bps · 15-min cooldown | *The Yield Hound* (high conviction) |

Read `index.json` rather than globbing the directory: it carries the `headline` and the **required
`tradeoff`** a card and the conversation both need, and `test_presets.py` asserts the index and the
directory agree in both directions. A preset is validated against `Mandate` **plus** invariants the
schema cannot express — every venue it names has an adapter, a multi-asset mandate grants a swap
venue, and every preset grants a venue that can earn on idle capital. That is what makes *"a preset
can never be un-deployable"* a test rather than an intention.

### The soft mandate band, and where it must never apply

`MandateConstraints.tolerance_band_pct` (default `0.05`) accepts a small numeric breach **with a
recorded warning** instead of rejecting it. **The band is relative to the constraint's own value:**
a ceiling `C` admits `C*(1+band)`, a floor `F` admits `F*(1-band)`, a target `T` admits
`|actual − T| ≤ T*band`.

| Constraint | Banded? | Why |
|---|---|---|
| `max_position_pct`, `min_cash_pct`, target drift | ✅ | These are aims; 61% against a 60% cap is a swap that priced a hair differently. |
| `max_slippage_bps` | ❌ **never** | A ceiling already compared against a worst case, not an estimate. Banding it silently pays more than the mandate's stated maximum cost. |
| `allowed_assets`, `permitted_venues`, `permitted_data_sources` | ❌ **never** | Not numeric. There is no 5% of an asset that isn't permitted. |
| `max_actions_per_tick`, `rebalance_cooldown_seconds` | ❌ | Anti-churn limits. A band here is just a bigger limit. |

Every banded acceptance **must** appear in `AgentAction.warnings`, and must be rendered wherever the
action is. A band nobody can see is indistinguishable from no rule at all, and repeated invisible
acceptances are how a book ratchets away from its mandate without ever tripping a rejection — which
is why drift is measured against the **mandate**, never against last tick.

### Personas

`Mandate.persona` shapes how the agent argues and what it prefers **among options the mandate
already permits**. It can never widen anything: not an asset outside `allowed_assets`, not a cap, not
the cash floor, not the slippage ceiling. Persona is taste; constraints are law. Lane B pins that
behaviourally; `test_presets.py` pins the authoring half — a persona in a preset may not name an
unpermitted asset or carry a percentage, because a number in a persona reads as a bound.

## Two designs worth understanding before you build against them

**`MarketSnapshot` is a flat list of provenance-carrying facts, not a provider's response shape.**
Each source contributes a *partial* set of `Fact`s and the registry merges them; sources never see
each other and never have to agree on coverage. No field is named after The Graph. This is what
makes adding Chainlink, Pyth or DefiLlama a matter of one new file plus one registration line, and
every fact carries `source` so the dApp can show where a number came from. A failing source lands in
`errors[]` and degrades the snapshot — it never crashes the decision loop.

**`ExecutionPlan` is the seam that keeps Lanes A and D apart.** Lane D builds arbitrary calldata
off-chain and never touches `contracts/`; the vault exposes one generic allowlisted
`execute(target, value, data)` and never learns what a venue is. A third venue is a new adapter, not
a contract change.

## Usage

```python
from curator_schema import Mandate, MarketSnapshot, AllocationDecision
from curator_schema.ports import DataSource

mandate = Mandate.model_validate_json(raw)
snapshot = await registry.snapshot(mandate.permitted_data_sources, mandate.constraints.allowed_assets)
decision = AllocationDecision.model_validate_json(model_output)  # raises → reject-and-retry
```

```ts
import { AllocationDecision, VaultState } from '@curator/schema'

const state = VaultState.parse(await res.json())
```

Develop against the fixtures so you never block on another lane:

```python
import json, pathlib
snap = MarketSnapshot.model_validate(
    json.loads(pathlib.Path("packages/schema/fixtures/market-snapshot.json").read_text())
)
```

## Assumptions & invariants

- **uint256 crosses as a decimal string**, never a JSON number — it exceeds float64 and
  `Number.MAX_SAFE_INTEGER`. Don't `Number()` these.
- **`extra="forbid"` / `.strict()` everywhere.** A typo fails at the boundary rather than silently
  propagating a field nobody reads.
- **APY is a fraction**: `0.0432` means 4.32%. Normalize at the source adapter.
- **The vault is sole custodian** (Pattern 1). Aqua tracks virtual balances while tokens stay in the
  vault, so `VaultState.holdings` is complete even with positions open. `committed_to_venue` flags
  encumbrance, not location.
- **`AgentAction` with `status: "rejected"` is kept**, not discarded — those records are the evidence
  that output validation is load-bearing.
- **`AllocationDecision.facts_used` must reference real `Fact.id`s** from the snapshot the agent was
  given. It's how the dApp draws data → reasoning → transaction, and how we catch a model inventing
  numbers.
- **A field with a non-`None` default changes `mandate_hash`.** The hash is taken over a
  re-serialization of the parsed model, so a new default materializes into the canonical form and
  moves the hash for mandates that never mentioned it — measured when `tolerance_band_pct` landed
  (active-work #71). Optional fields defaulting to `None` drop out and are hash-neutral. Any request
  that adds a defaulted field to a hashed shape is announced as hash-visible.

## Dependencies

Python: `pydantic>=2.7` (plus `jsonschema`, `referencing`, `pytest` for the conformance test).
TypeScript: `zod ^3.23`.

## Tests

```bash
uv run pytest packages/schema/python -q     # 22 tests
```

> If you run this against global Anaconda rather than the project venv, pass
> `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` — there's a broken global `web3` pytest plugin on this machine
> that breaks collection. The `uv` venv doesn't have it. See [docs/setup.md](../../docs/setup.md).
