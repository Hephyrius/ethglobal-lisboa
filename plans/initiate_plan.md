# Agentic Vault Curation — Project Plan

> A platform where users co-design an investment strategy in natural language, wrap
> it in an ERC-4626 vault, and hand curation to an autonomous LLM agent that
> allocates capital against a mandate using live data sources.

Built for ETHGlobal Lisbon 2026. This file is the source of truth for architecture
decisions. Items marked **[PARKED]** are explicitly out of scope for the hackathon —
do not build them unless asked.

---

## 1. Concept

An AI agent plays the role a human vault curator plays today (à la Morpho / Yearn):
it decides how to allocate deposited capital across markets/strategies to optimize
risk-adjusted yield, and rebalances as conditions change. **The agent is the curator.**

A user creates a vault by talking to a local LLM in natural language. That
conversation produces a **mandate** — the rules and constraints the agent operates
under, plus the data sources it may consult. The mandate is wrapped in an ERC-4626
vault. From genesis onward, the agent runs autonomously.

---

## 2. Locked Decisions

These are settled. Do not relitigate without an explicit request.

| Area | Decision |
|------|----------|
| Mandate location | **LLM-side (soft).** Not enforced on-chain. |
| Mandate mutability | **Mutable while live, but only by the agent** as it pursues its mandate. The human deployer cannot change it after genesis. |
| Agent → chain boundary | **Agent holds a key and executes directly.** Fully autonomous curator. |
| Strategy creation | **One-time genesis event.** After genesis, only the agent updates the strategy. |
| Agent ↔ vault cardinality | **One agent per vault.** |
| Custody during rebalance | **Pattern 1: vault is sole custodian.** Capital never leaves the vault contract; `totalAssets()` always reflects held assets. Clean share accounting. |
| Model layer | **Local-first, provider-agnostic.** Open-weight models via **Ollama / vLLM**, standardized on OpenAI-compatible endpoints. Hosted APIs (Anthropic etc.) are optional drop-in later. |

### Trust model note (intentional)
The trust model rests fully on the agent: soft mandate + agent holds the key + no
human override after genesis. There is **no hard on-chain backstop** in the hackathon
build. This is a deliberate, internally-consistent scope choice — the cleanest
expression of the "agentic curation" thesis. The future backstop is **protocol-level
controls** across all platform-deployed vaults (see Parked).

---

## 3. Architecture

### 3.1 Off-chain

**Strategy builder (genesis)**
- User co-designs a strategy in natural language with a local open LLM.
- User selects which **data sources** the agent may consult.
- Output: a **mandate** (constraints + permitted data sources + investment intent),
  crystallized once at genesis.

**Agent harness** — runtime scaffold around the model. Responsibilities:
- Wraps the LLM behind a **model-abstraction seam** (swappable local/remote backend).
- Holds the mandate.
- Wires in the chosen data sources.
- Runs the decision/execution loop.
- **Validates model outputs** (strict schema / function-call parsing, reject-and-retry
  on malformed responses) before anything reaches the chain — load-bearing because
  smaller open models are more prone to malformed / weak structured output, and the
  agent executes directly with a key.

**Model layer**
- Backends: Ollama and vLLM (both expose OpenAI-compatible endpoints).
- Standardize the harness on the OpenAI-compatible request/response shape → local
  backends *and* most hosted providers work behind one interface.
- Target open model(s): **[TODO — decide later]**. Tool-calling reliability varies
  widely; pick with that in mind.

### 3.2 On-chain

Built on **OpenZeppelin** primitives (ERC-4626, AccessControl/Ownable, Clones/factory).

- **Vault (ERC-4626)** — deposits, shares, withdrawals. Sole custodian of assets
  (Pattern 1). `totalAssets()` is the single source of truth for share pricing.
- **Ownership / access control** — defines the agent's authorization boundary and
  who (if anyone) controls the vault shell. Note: mandate itself is soft/off-chain,
  so on-chain controls here are minimal for the hackathon.
- **Factory / deployment** — spins up a new vault per created strategy (Clones pattern
  for cheap deploys).
- **Allocation & funding** — moving capital into positions and rebalancing, with the
  vault remaining custodian throughout.

---

## 4. Build Order (suggested)

1. **Contracts**: OZ ERC-4626 vault (Pattern 1) + factory. Get deposit → shares →
   withdraw working with accurate `totalAssets()`.
2. **Allocation surface**: the vault-held rebalance path (agent-authorized calls that
   keep the vault as custodian).
3. **Harness skeleton**: model-abstraction seam over Ollama/vLLM (OpenAI-compatible),
   output validation, mandate loading.
4. **Decision/execution loop**: agent reads data sources → decides allocation →
   executes on-chain with its key.
5. **Genesis strategy builder**: natural-language → mandate crystallization.
6. **Data source integration**: wire live sources into the harness.

(Exact ordering flexible; contracts-first de-risks the accounting core early.)

---

## 5. Open Questions / TODO

- **Mandate schema**: what a strategy actually *contains* (constraints, risk params,
  permitted venues, data-source list, update rules). Not yet defined.
- **Agent decision loop**: trigger cadence (block/time/event-driven?), how a rebalance
  decision is formed and bounded.
- **Contract interfaces**: full contract set and function surface for the
  agent → vault authorization boundary.
- **Data sources**: which live sources, and their adapters into the harness.
- **Target open model(s)** for local serving.

---

## 6. [PARKED] — Do Not Build for Hackathon

- **Harness trust / verifiability** — why a depositor should trust a black-box
  off-chain agent with funds. Deferred.
- **Protocol-level controls** — global, platform-wide guardrails across every deployed
  vault, as the eventual system-wide safety backstop (replaces per-vault human
  override). Design later.
- **Hosted API model backends** — optional drop-in after local-first works.
- **Pattern 2 custody** (funds leaving the vault to external position contracts) —
  not unless a strategy genuinely can't be expressed with the vault as holder.

---

## 7. Bounty Context (ETHGlobal Lisbon 2026)

The architecture above is bounty-agnostic by design. Three sponsors selected —
slot them into the real architecture, don't warp the architecture to fit them:

- **The Graph ($15K)** — the agent's live data source (yields, TVL, liquidity, risk).
  Natural fit; possibly the ERC-4626 / composable-standardized track given the vault.
- **Uniswap ($10K)** — execution / rebalancing venue via the Uniswap API (needs valid
  API key, `FEEDBACK.md`, feedback-form submission).
- **1inch ($7K)** — the structured DeFi position itself, expressed via **Aqua**
  (SwapVM usage scores higher). Must be distinct from Uniswap's execution role, or it
  reads as cosmetic to judges.

Integration/positioning to be workshopped separately.
