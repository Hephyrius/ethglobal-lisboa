# Build log

Append-only, **newest at the top**. Every non-trivial change gets an entry: what changed, **why**
(the important part), and what alternatives were rejected. Never rewrite another agent's entry.

This log is also part of the ETHGlobal audit trail — it evidences that decisions were made during
the hackathon window.

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
