# packages/schema — the frozen cross-lane interface

## Purpose

The single definition of every shape that crosses a component boundary. Five Claude Code instances
build this repo in parallel and must not read each other's code ([INSTRUCTIONS.md](../../INSTRUCTIONS.md)
Rule 7), so this package is how they agree on anything at all.

**Frozen after Wave 0.** A lane that needs a change files a request in
[docs/active-work.md](../../docs/active-work.md) — it does not edit this directory.

## Layout

```
*.schema.json          SOURCE OF TRUTH — JSON Schema 2020-12
python/curator_schema/ pydantic mirror (models.py) + port Protocols (ports.py)
ts/src/index.ts        zod mirror + inferred TypeScript types
fixtures/*.json        golden fixtures — every lane develops against these
python/tests/          conformance: fixtures must satisfy JSON Schema AND pydantic
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
