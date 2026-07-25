# Master Build Plan — Agentic Vault Curation

**ETHGlobal Lisbon 2026 · 5 parallel Claude Code instances · MVP + Mac handoff at 10:00 Sunday**

---

## 1. Context

We are building an agentic ERC-4626 vault curator (concept + locked decisions in
[plans/initiate_plan.md](plans/initiate_plan.md)) across **five Claude Code instances working
simultaneously**. [INSTRUCTIONS.md](INSTRUCTIONS.md) Rule 7 forbids any instance from editing another
component. That constraint is what this document exists to satisfy: it defines the lanes, freezes the
interface between them, and fixes the order of operations so nobody blocks and nobody collides.

**Every instance reads §2–§7, then only its own lane in §8. Do not read or edit other lanes' code.**

Decisions locked this session — do not relitigate:

| | |
|---|---|
| Stack | **Python** harness/data/venues · **TypeScript** (Next.js) frontend · **Solidity** (Foundry) contracts |
| Chain | **Anvil fork of Base mainnet** for dev · **real Base mainnet** for the final demo |
| Sponsors | **The Graph · Uniswap · 1inch** — all three load-bearing |
| Graph scope | **All 3 non-continuity tracks** ($11K) |
| JS-only SDKs | **Avoided.** SwapVM programs built in Solidity, x402 hand-rolled in Python |
| Data sources | **Pluggable registry** — Graph today, Chainlink/Pyth/DefiLlama drop in later (§8 Lane C) |
| Demo | Full dApp: genesis chat → deploy → deposit → live agent decision feed |
| Handoff | **Teammate on macOS takes over at 10:00.** Everything must be reproducible there. |

---

## 2. Environment — verified, do not re-derive

Checked on this machine. Two traps here that will burn an instance each if not stated.

**Windows host**
| Tool | Status |
|---|---|
| Python | **`C:\ProgramData\anaconda3\python.exe` — 3.12.7 ✓** |
| ⚠️ `python` on PATH | **The Microsoft Store stub — it does not run.** It shadows Anaconda. Use the absolute path or activate conda. |
| Node / pnpm | v20.13.1 / 9.5.0 ✓ |
| git | 2.45.1 ✓ · no `gh` CLI · no Docker |

**WSL — two distros installed**
| Distro | glibc | Python | Use |
|---|---|---|---|
| **Ubuntu-24.04** | **2.39** | 3.12.3 | ✅ **Foundry lives here.** glibc 2.39 ≫ 2.34, so `foundryup` prebuilt binaries work. |
| Ubuntu-20.04 *(default)* | 2.31 | 3.8.10 | ❌ **Avoid.** glibc too old for Foundry binaries; Python 3.8 is EOL and below the MCP SDK's ≥3.10 floor. |

> ⚠️ **`Ubuntu-20.04` is the default distro.** A bare `wsl <cmd>` lands in the wrong one and hits a
> `GLIBC_2.34 not found` wall. **Always `wsl -d Ubuntu-24.04`.**

**Runtime split (Windows side)**
- Lanes B, C, D (Python) and E (Node) → **Windows host.** Native filesystem speed on the repo.
- Lane A + Lane D's Foundry project → **`wsl -d Ubuntu-24.04`.** Only Foundry pays the `/mnt/c`
  penalty, and a small contract set compiles in seconds.
- Anvil runs in WSL. **Bind `--host 0.0.0.0`** or Windows clients cannot reach `localhost:8545`.

**Python environment: use `uv`, pinned to 3.12.** Identical on Windows, WSL and macOS, so the 10:00
handoff is a no-op. Anaconda 3.12.7 is the already-present fallback if `uv` gives trouble.
Commit `pyproject.toml` + `.python-version` + `uv.lock`.

**Foundry install (Lane A, hour 0):** `wsl -d Ubuntu-24.04` → `curl -L https://foundry.paradigm.xyz | bash && foundryup`.
Expected to succeed on glibc 2.39. If it somehow fails, fall back to a background
`cargo install --git https://github.com/foundry-rs/foundry --profile release forge cast anvil`
(cargo/rustc 1.88 live in the 20.04 distro) and write contracts while it compiles.

---

## 3. Cross-platform discipline — the 10:00 macOS handoff

The teammate picking this up at 10:00 is on macOS. The MVP deadline **is** the handoff. Treat
reproducibility as a deliverable, not a courtesy.

- **No absolute paths, no OS-specific paths, in committed code or config.** Everything relative to
  repo root; all machine-specific values via `.env`.
- **Scripts are POSIX `sh`/`bash`** — they must run unchanged in WSL and on macOS. No PowerShell in
  the committed tree.
- **`docs/setup.md` is a Wave 0 deliverable** with a macOS column beside the Windows/WSL column.
  On macOS everything is easier: `brew install node`, `curl … | sh` for uv, `foundryup` natively.
- **`docs/handoff.md`** — written during the T+14h freeze window, not at 09:55. What's done, what's
  stubbed, what's known-broken, how to run it, where each lane's plan and README live.
- Validate the handoff by the docs alone: a fresh clone plus `docs/setup.md` must reach a running
  stack with no tribal knowledge.

---

## 4. Timeline — 24 hours, integration included

| When | What |
|---|---|
| **T+0 → T+1:00** | **Wave 0** — frozen interface, `CLAUDE.md`, `/plans/`, `/docs/`, `setup.md`. *All lanes blocked.* |
| T+1:00 | Each lane writes its `/plans/` file, claims in `/docs/active-work.md`, then starts |
| **T+4h — CP1** | ABIs published · one live Graph query · one live Uniswap quote · **every lane's README exists** |
| **T+8h — CP2** | Vertical slice: deposit → agent tick → real Uniswap swap on fork |
| **T+12h — CP3** | Aqua `ship()` lands on fork · decision feed renders in the dApp |
| **T+14h** | **Feature freeze.** No new MVP scope. `docs/handoff.md` started. |
| T+14h → 10:00 | **Integration and hardening only.** Reconcile build log, usage docs, lane plans. |
| **10:00 Sun** | **MVP demoable end-to-end + clean handoff to macOS.** |
| 10:00 → submit | Mainnet deploy + funded run · demo video · `FEEDBACK.md` · submission text |

Every lane has an **MVP** list and a **Stretch** list. *Nothing from Stretch is touched until that
lane's MVP is green, documented, and pushed.*

---

## 5. Governance — where plans, rules and history live

**`/CLAUDE.md` — auto-loaded by every instance.** `INSTRUCTIONS.md` is not read automatically;
`CLAUDE.md` is. Wave 0 creates it as the entry point every instance picks up for free: pointer to
`INSTRUCTIONS.md` (the 7 rules), pointer to this plan, the lane table, the environment traps in §2,
the claim-before-you-build rule, and the commit-and-push rule. Without it, five instances start
without the rules loaded.

**`/plans/` — every plan lives in the repo (Rule 2).**
- `/plans/initiate_plan.md` — existing: concept + locked architecture decisions
- `/plans/2026-07-25-master-build-plan.md` — **this document.** Wave 0 copies it in.
- `/plans/2026-07-25-lane-{a..e}-{name}.md` — **each lane writes its own plan before coding.**
  Approach, file breakdown, interfaces produced, risks. Keep current; note material changes in the
  build log.

**`/docs/`** — `build-log.md`, `active-work.md`, `setup.md`, `handoff.md`. Append-only; never rewrite.

**Rule 1/5 compliance is ~20% of every lane's time. Budget it; it is not optional overhead.** Your
usage doc is the *only* way the other four lanes integrate with you, the build log is part of the
ETHGlobal audit trail, and both are what make the 10:00 handoff survivable. A lane that ships code
with no README has not shipped.

---

## 6. Architecture — why these three sponsors are load-bearing

```
   ┌──────────── DATA REGISTRY (pluggable) ─────────────┐
   │  Graph: Messari subgraphs · Token API · x402       │   the agent's EYES
   │  ── future drop-ins: Chainlink · Pyth · DefiLlama  │   (live, never mocked)
   └────────────────────────┬───────────────────────────┘
                            │ MarketSnapshot
                            ▼
                     ┌─────────────┐
                     │ LLM curator │  mandate + validated structured output
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

**The Aqua insight that makes 1inch non-cosmetic.** Aqua is a shared-liquidity *registry*: tokens
**stay in the maker's wallet**, and only virtual balances `balances[maker][app][strategyHash][token]`
are tracked on-chain. That is precisely our locked **Pattern 1 (vault is sole custodian)** decision.
So the **vault itself is the Aqua maker** — `approve(aqua)` once, `ship()` a strategy, capital never
leaves, `totalAssets()` stays correct. Rebalance is `dock()` + re-`ship()`. Aqua is the *only* way to
run a live market-making position without violating Pattern 1.

**Why Uniswap is still required.** An Aqua maker is passive — it posts liquidity and waits to be
filled. It cannot decide to change what it holds. Uniswap's `/quote` → `/swap` is the taker-side path
that lets the agent actually rotate composition ("volatility spiked, move to stables"). Distinct
role, non-overlapping with Aqua, exactly as [initiate_plan.md](plans/initiate_plan.md) §7 demands.

### Live contract addresses (Base — verified)
| | |
|---|---|
| Aqua | `0x499943e74fb0ce105688beee8ef2abec5d936d31` |
| SwapVM | `0x8fdd04dbf6111437b44bbca99c28882434e0958f` |
| USDC (Base) | `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913` |
| Uniswap API | `https://trade-api.gateway.uniswap.org/v1` — `POST /quote`, `POST /swap` |
| Graph x402 gateway | `https://gateway.thegraph.com/api/x402/subgraphs/id/{id}` |

---

## 7. Repository layout — component = lane = claim

```
/CLAUDE.md        Wave 0   auto-loaded rules entry point for every instance
/contracts        Lane A   Foundry/Solidity   vault, factory, agent execute() surface
/agent            Lane B   Python             model layer, validation, mandate, loop, FastAPI
/data             Lane C   Python             source registry, Graph adapters, MCP server, x402
/venues           Lane D   Python + Solidity  Aqua/SwapVM builder, Uniswap API client
/web              Lane E   TypeScript         genesis chat, deposit/withdraw, decision feed
/packages/schema  Wave 0   JSON Schema        THE FROZEN INTERFACE — read-only after freeze
/docs             shared   build-log · active-work · setup · handoff    APPEND ONLY
/plans            shared   master + per-lane plans                      APPEND ONLY
```

**Lane D owns Solidity too** — `/venues/aqua/solidity/`, a standalone Foundry project holding a
`SwapVMProgramBuilder` view contract. This is *not* `/contracts` and Lane A never imports it. It
exists so SwapVM programs are built with 1inch's official `ProgramBuilder` in Solidity, read
off-chain via `eth_call`, and handed to the vault as opaque bytes. This is the seam that keeps
Lanes A and D from colliding.

---

## 8. Wave 0 — foundation (BLOCKING, ~60 min, one instance)

Stack is split Python/TypeScript, so the schema is authored **once as JSON Schema** and mirrored.
This is the mitigation for the double-definition risk that a split stack accepts.

**Deliverables**
- **`/CLAUDE.md`** — see §5. Rules + environment traps, auto-loaded by all five instances.
- **`/.gitignore` with `.env` — before any real key is added.** Fold the existing `Example.env`
  (`uniswap_key=xxxx`) into a root `.env.example` covering every credential in §8.1.
- `/docs/setup.md` — Windows/WSL **and macOS** columns (§3)
- `/docs/build-log.md` + `/docs/active-work.md`, seeded with the five lane claims
- `/plans/2026-07-25-master-build-plan.md` — this file, copied into the repo
- `/packages/schema/*.json` — `Mandate`, `MarketSnapshot`, `AllocationDecision`, `ExecutionPlan`,
  `AgentAction`, `VaultState`
- `/packages/schema/python/` (pydantic) and `/packages/schema/ts/` (zod) mirrors
- `/packages/schema/fixtures/*.json` — **golden fixtures; every lane develops against these**
- **Port contracts** (docstrings are the spec): `DataSource`, `ModelBackend`, `VaultClient`, `Venue`
- **The FastAPI contract** Lane E consumes — freeze the routes now, Lane B implements them:
  ```
  POST /genesis/chat          {messages[]}        → {reply, mandate_draft?}
  POST /genesis/finalize      {mandate}           → {mandate_hash, deploy_tx}
  GET  /vault/{addr}/state                        → VaultState
  GET  /vault/{addr}/decisions?limit=             → AgentAction[]
  POST /vault/{addr}/tick                         → AgentAction
  ```
- Root `pyproject.toml` + `.python-version` (3.12) + `uv.lock`; `pnpm-workspace.yaml` for `/web`
- `scripts/anvil-fork.sh` (POSIX, `--host 0.0.0.0`), `deployments/base-fork.json` shape
- Git remote confirmed and **a first push landed**, so the audit trail starts at hour 0

**After freeze:** a lane needing a schema change files a request in `/docs/active-work.md`. It does
not edit `/packages/schema`.

### 8.1 Credentials — full list, get the blocking three now

**Blocking — nothing works without these:**

| Var | Where | Owner | Notes |
|---|---|---|---|
| `UNISWAP_API_KEY` | [developers.uniswap.org/dashboard](https://developers.uniswap.org/dashboard) | Lane D | Gates the $7K track. Placeholder already in `Example.env`. |
| `BASE_RPC_URL` | Alchemy / QuickNode / dRPC free tier | Wave 0 | ⚠️ **Easy to miss.** `anvil --fork-url` needs an **archive-capable** endpoint. The public `mainnet.base.org` is rate-limited and will fail or crawl under forking. Every lane depends on the fork. |
| `GRAPH_API_KEY` | [thegraph.com/studio](https://thegraph.com/studio) → API Keys | Lane C | ⚠️ The x402 path deliberately needs no key — but x402 is our *risky* path. The **fallback** requires this key, so it is not optional. Free tier ≈100K queries/month. |

**Needed for the mainnet demo run (refine window, after 10:00):**

| Var | Where | Notes |
|---|---|---|
| `DEPLOYER_PRIVATE_KEY` | new wallet, funded ~$20 + gas on Base | Fresh key. Never reuse a personal wallet. |
| `AGENT_PRIVATE_KEY` | anvil default acct on fork; funded key on mainnet | The agent holds this and executes directly — that is the trust model. |
| `X402_PRIVATE_KEY` + `X402_CHAIN=base` | small wallet holding a few $ of USDC on Base | Queries cost fractions of a cent. Can be the agent key — *the agent paying for its own data is the narrative*. |
| `BASESCAN_API_KEY` | [basescan.org](https://basescan.org) → free | For `forge verify-contract`. Judges want to read verified source; Uniswap's rules require the README to point at the contracts. |

**Likely needed:**

| Var | Where | Notes |
|---|---|---|
| `NEXT_PUBLIC_WALLETCONNECT_ID` | [Reown / WalletConnect Cloud](https://cloud.reown.com) | Only if Lane E uses RainbowKit or the WalletConnect connector. Injected-MetaMask-only avoids it — Lane E should decide early, it's a 2-minute signup either way. |

**Explicitly NOT needed — don't waste time hunting these:**
- **No 1inch API key.** Aqua and SwapVM are plain on-chain contracts called via our own RPC. The
  `portal.1inch.dev` key is for their *classic swap API*, which we are not using.
- **No model API key.** Local-first via Ollama/vLLM (`OLLAMA_BASE_URL`, `MODEL_NAME`).

Non-secret config also in `.env.example`: `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_CHAIN_ID`,
`OLLAMA_BASE_URL`, `MODEL_NAME`.

Two shapes matter most. `ExecutionPlan` is how Lane D talks to Lanes A and B:
```json
{ "steps": [ { "target": "0x…", "value": "0", "calldata": "0x…", "why": "swap 1000 USDC→WETH" } ] }
```
`MarketSnapshot` must be **source-agnostic** — see Lane C. No field may be named after The Graph.

---

## 9. Rules binding every lane

1. **Commit *and push* to GitHub after every meaningful change.** Not at the end — continuously,
   with real messages. Two independent reasons, both scored:
   - 1inch explicitly disqualifies *"single-commit entries on the final day."*
   - **ETHGlobal judges verify work was built inside the hackathon window, and the pushed commit
     timeline on GitHub is that evidence.** A local-only history proves nothing. Push it.
2. **Mock-first.** Build against `/packages/schema/fixtures/`. No lane waits on another lane's code.
3. **Live data in the demo path.** The Graph disqualifies mocked/static data. Fixtures are for
   development only; the submitted path must hit the live gateway.
4. **Cross-platform only** (§3). No absolute paths, no PowerShell in the tree — macOS takes over at 10:00.
5. **Claim before you build**, in `/docs/active-work.md`. Append; never rewrite (Rule 7).
6. **Write your lane plan into `/plans/` before coding** (Rule 2), and keep it current.
7. **Usage doc per component** (`README.md`, Rule 5) + **build-log entry** for every non-trivial
   decision (Rule 1).
8. **Never edit another lane's directory.** Need a change there? File it in `/docs/active-work.md`.

---

## 10. Lane definitions

### Lane A — Contracts · `/contracts` · Foundry in `wsl -d Ubuntu-24.04`

**Owns** the vault, the factory, and the agent's authorization boundary. Publishes ABIs + addresses;
everything downstream depends on those, not on the source.

**MVP**
- **Hour 0:** `wsl -d Ubuntu-24.04`, then `curl -L https://foundry.paradigm.xyz | bash && foundryup`.
  Not the default 20.04 distro — see §2.
- `CuratedVault.sol` — OZ ERC-4626, `AGENT_ROLE` via AccessControl, sole custodian
- `execute(address target, uint256 value, bytes calldata data)` — **`AGENT_ROLE` only, target must be
  allowlisted** {Aqua, SwapVM, Uniswap UniversalRouter, Permit2, WETH}. This single generic surface is
  what lets Lane D build any calldata off-chain without ever touching `/contracts`.
- `approveVenue(token, spender, amount)` — agent-only, allowlisted spenders
- `totalAssets()` — USDC balance + non-USDC holdings valued via **Chainlink Base price feeds**.
  Keep it simple and honest; do not read Aqua virtual balances at MVP (tokens are still in the vault,
  so `balanceOf` already counts them).
- `VaultFactory.sol` — OZ Clones, one vault per strategy, emits `VaultCreated(vault, asset, agent, mandateHash)`
- Foundry fork tests against real Base state
- **Publishes:** `/contracts/out/**` ABIs + `deployments/base-fork.json` + `/contracts/README.md`

**Stretch:** ENS subname minting with `agent:mandate-hash` text record · richer accounting · pause

**Depends on:** Wave 0 only. **Blocks:** everyone — publish ABIs by **CP1 (T+4h)**, even if stubbed.

---

### Lane B — Agent harness · `/agent` · Python (Windows host)

**Owns** the model seam, output validation, the mandate, the decision loop, and the FastAPI surface.

**MVP**
- `/agent/model/` — OpenAI-compatible client over `httpx`; `backends/ollama.py`, `backends/vllm.py`
  behind one `ModelBackend` port
- `/agent/model/validation.py` — **load-bearing.** Strict JSON-schema validation of model output with
  reject-and-retry (max 3, feed the validation error back into the retry prompt). Small open models
  produce malformed structured output and this agent holds a key.
- `/agent/mandate/` — load, persist, hash, agent-side mutation. `permitted_data_sources` is a **list
  of registry keys** resolved by Lane C's registry — granting a new source is a mandate edit, not a
  code change.
- `/agent/loop/` — one cycle: `registry.snapshot(mandate.permitted_data_sources)` → prompt → validate
  → `AllocationDecision` → `Venue.plan()` → `VaultClient.execute()` → persist `AgentAction`
- `/agent/chain/` — `VaultClient` on web3.py, consuming Lane A's published ABIs
- `/agent/api/` — FastAPI implementing the **frozen routes from §8**

**Stretch:** trigger cadence/scheduler · agent-initiated mandate mutation · richer reasoning traces

**Depends on:** Wave 0 ports; Lane A ABIs (stub until CP1); Lanes C/D via ports (use fixtures).
**Blocks:** Lane E — stand the FastAPI routes up returning fixture data **within the first 2 hours**,
then swap in real implementations. Lane E must never be blocked on your internals.

---

### Lane C — Data layer · `/data` · Python (Windows host)  ← the $11K lane

**Owns** everything that reads market data. Two goals that must not be confused: (a) win three Graph
tracks now, (b) make adding a *non-Graph* source later a 30-minute job.

**Extensibility is a first-class requirement, not a nice-to-have.**
```
/data/
  registry.py          DataSource registry: name → provider, resolved from mandate config
  ports.py             the DataSource protocol
  sources/
    messari.py         Graph · Messari standardized subgraphs (yields, TVL, liquidity)
    token_api.py       Graph · Token API (prices, metadata)
    __init__.py        registration table — one line per source
  #  chainlink.py, pyth.py, defillama.py drop in here later: implement the port,
  #  add one registration line, name it in a mandate. No other file changes.
```
Design constraints that make that true:
- `DataSource.fetch()` returns a **partial contribution**; the registry merges contributions into one
  `MarketSnapshot`. Sources never see each other and never need to agree on coverage.
- **`MarketSnapshot` is source-agnostic** — no field named after The Graph, Messari, or any provider.
  Each fact carries provenance (`source: "messari"`) so the UI can show where a number came from.
- Sources are selected **by name from the mandate**, so the "user picks permitted data sources" flow
  in [initiate_plan.md](plans/initiate_plan.md) §3.1 is exactly the registry lookup. Same mechanism.
- A source failing degrades the snapshot; it never crashes the loop.

**MVP**
- The registry + port + source-agnostic `MarketSnapshot` merge described above
- `/data/curator_mcp/` — **a standalone, separately-installable MCP server** with its own
  `pyproject.toml`, `README.md` and **`SKILL.md`**. Graph Track 1 requires *reusable tooling, not a
  single end-user app* — it must be genuinely usable by any agent, with our harness visibly just its
  first consumer. Tools: `list_markets`, `get_market_yields`, `compare_protocols`, `get_token_price`.
  (Requires Python ≥3.10 — hence the 3.12 pin in §2.)
- `sources/messari.py` — **Messari standardized subgraphs.** The composition story: one query shape
  works across every lending/DEX protocol, so adding a protocol to the agent's opportunity set is a
  config line, not a new adapter. Make that concretely demonstrable — it *is* the Track 3 argument.
- `sources/token_api.py` — Graph Token API
- `/data/x402/` — hand-rolled pay-per-query: request → `402 Payment Required` → sign USDC payload
  with `eth-account` → resend with payment header. ~100 lines. **The agent paying for its own market
  data out of its own wallet is the strongest narrative beat in the demo.**

**⚠️ Risk — x402 is hand-rolled.** Keep it on a **separate code path** behind a feature flag, with an
API-key gateway query as fallback. It must not be able to break the demo. Budget 90 min; if it isn't
working by then, ship the fallback and revisit in the refine window.

**Stretch:** a Chainlink source as a live proof of the registry · Substreams · more protocols

**Depends on:** Wave 0 `DataSource` port. **Blocks:** nobody (Lane B uses fixtures until you land).

---

### Lane D — Venues · `/venues` · Python (Windows) + Foundry (`wsl -d Ubuntu-24.04`)

**Owns** both sponsor execution paths. Produces `ExecutionPlan` objects; never touches `/contracts`.

**MVP**
- **Hour 0, before anything else: register for the Uniswap API key** at
  [developers.uniswap.org/dashboard](https://developers.uniswap.org/dashboard) and put it in `.env`
  (never committed). It gates the whole $7K track.
- `/venues/uniswap/` — Trading API client: `POST /quote` → `POST /swap` → calldata; Permit2/approval
  handling; headers `x-api-key`, `Content-Type`, `Accept`. Plain HTTP, Python-native.
- `/venues/aqua/solidity/` — standalone Foundry project with a `SwapVMProgramBuilder` **view**
  contract using 1inch's official `ProgramBuilder`. Composes `_dynamicBalancesXD` + `_xycSwapXD` +
  a fee instruction. Read off-chain via `eth_call`, returns program bytes.
- `/venues/aqua/` (Python) — builds `ship()` / `dock()` calldata, sets
  `useAquaInsteadOfSignature = true` (**SwapVM mode scores higher with 1inch**), calls the builder
  contract for program bytes
- Both emit the Wave-0 `ExecutionPlan` shape behind a common `Venue` port, so a third venue is an
  adapter, not a refactor
- **Owns `FEEDBACK.md`** at repo root and submits the Uniswap Developer Feedback Form

**Stretch:** wider SwapVM instruction coverage · Dutch-auction / TWAP programs

**Depends on:** Wave 0 `Venue` port + `ExecutionPlan`; Lane A's allowlist (agree the target list at
CP1). **Blocks:** nobody.

---

### Lane E — dApp · `/web` · Next.js + TypeScript (Windows host)

**Owns** the entire judge-facing surface. This is what the judges actually experience — treat the
agent's visible reasoning as the product, not a debug view.

**MVP**
- `/create` — genesis chat with the local LLM → mandate preview (including which data sources the
  user is granting) → deploy vault (`POST /genesis/chat`, `POST /genesis/finalize`)
- `/vault/[address]` — wallet connect (wagmi/viem), deposit/withdraw, TVL + share price, mandate
  viewer, and the **agent decision feed: data consulted (with provenance) → reasoning → tx hash**
- Consumes Lane A ABIs and Lane B's frozen FastAPI routes; zod schemas from `/packages/schema/ts`

**Stretch:** position/PNL charts · ENS name display · mandate diff view when the agent mutates it

**Depends on:** Wave 0 zod mirrors + frozen routes; Lane A ABIs; Lane B API.
**Never blocked:** the routes are frozen in Wave 0 and Lane B serves fixtures from hour 2.

---

## 11. Submission gates — assign owners now, these are what actually lose prizes

| Gate | Owner | Deadline |
|---|---|---|
| The three blocking credentials (§8.1): Uniswap key, archive `BASE_RPC_URL`, Graph key — with **`.env` gitignored first** | Lane D / Wave 0 / Lane C | **hour 0** |
| `FEEDBACK.md` + Developer Feedback Form submitted | Lane D | before submit |
| README points to the exact contracts and lines (Uniswap requirement) | Lane D + A | refine window |
| MCP server standalone + `SKILL.md`, open source | Lane C | MVP |
| Live Graph data on the demo path — **no mocks** | Lane C | MVP |
| Official Aqua/SwapVM contracts used; on-chain transfers shown live | Lane D | mainnet run |
| **Pushed** hourly commit history, no final-day squash | **all lanes** | continuous |
| 2–4 min demo video | whoever is freest | refine window |
| Public repo, open source, contract addresses listed | Wave 0 owner | refine window |

---

## 12. Verification

**Per lane, before claiming done**
- A: `forge test --fork-url $BASE_RPC_URL` green in Ubuntu-24.04; `deployments/base-fork.json`
  written; ABIs exported
- B: `pytest` on validation retry (feed deliberately malformed model output, assert recovery);
  FastAPI routes return schema-valid payloads for every frozen route
- C: live query against the real gateway returns a populated `MarketSnapshot`; MCP server starts
  standalone and responds to `tools/list`; x402 path completes a paid query *or* cleanly falls back;
  **registry test: a dummy second source registers and merges without touching any existing source**
- D: real Uniswap `/quote` returns a route; `SwapVMProgramBuilder` `eth_call` returns non-empty bytes;
  both produce a schema-valid `ExecutionPlan`
- E: `pnpm build` clean; deposit and withdraw work against the fork from a browser wallet

**End-to-end (the CP2 → MVP path)**
1. `scripts/anvil-fork.sh` in Ubuntu-24.04 (`--host 0.0.0.0`); deploy via the factory
2. Genesis chat in the dApp → mandate (with permitted sources) → vault deployed
3. Deposit USDC from a funded fork account → shares minted, `totalAssets()` correct
4. `POST /vault/{addr}/tick` → agent queries live Graph data → emits validated `AllocationDecision`
5. Rotation executes through Uniswap; position ships into Aqua; `totalAssets()` still correct
6. Decision feed in the dApp shows data → reasoning → tx hash
7. Withdraw → shares burn at the right price

**Handoff check (10:00):** a fresh clone on macOS, following `docs/setup.md` alone, reaches the same
running stack. No tribal knowledge.

**Mainnet demo run (refine window, ~$20):** same flow on real Base; capture BaseScan links for the
video and submission.

---

## 13. Per-lane kickoff prompts

Paste into each instance after Wave 0 is committed, pushed, and announced.

> **Common preamble for all five:**
> Read `/CLAUDE.md`, `/INSTRUCTIONS.md`, `/plans/initiate_plan.md`, and
> `/plans/2026-07-25-master-build-plan.md`. Note §2 (environment): Windows `python` on PATH is a
> broken Store stub — use the project `uv` venv; Foundry work is `wsl -d Ubuntu-24.04`, **never** the
> default 20.04 distro. Claim your lane in `/docs/active-work.md` and write your lane plan to
> `/plans/2026-07-25-lane-<X>-<name>.md` **before** writing code. You own exactly one directory — do
> not read or edit any other lane's code; integrate only through `/packages/schema` and the other
> lanes' `README.md` usage docs. Build against `/packages/schema/fixtures/` so you never block on
> another lane. Keep everything cross-platform — a teammate on macOS takes over at 10:00. **Commit
> and push to GitHub after every meaningful change** — the pushed timeline is how ETHGlobal verifies
> the work was built during the hackathon, and 1inch scores commit history directly. Budget ~20% of
> your time for the build log, your usage doc, and your lane plan; they are deliverables, not
> overhead. Deliver the MVP list only — no Stretch items until MVP is green, documented and pushed.
> Feature freeze T+14h; MVP + handoff 10:00.

| Lane | Prompt suffix |
|---|---|
| **A** | You own `/contracts` (Foundry, in `wsl -d Ubuntu-24.04`). Install Foundry via `foundryup` first — glibc 2.39 there means the prebuilt binaries work. Build §10 Lane A MVP. Your `execute(target, value, data)` allowlist surface is what lets Lane D work without touching your code — get ABIs and `deployments/base-fork.json` published within 4 hours even if the vault is still incomplete. |
| **B** | You own `/agent` (Python). Build §10 Lane B MVP. **Within your first 2 hours, stand up the FastAPI routes frozen in §8 returning fixture data** — Lane E is blocked on you until you do. Then build the real loop behind them. Output validation is load-bearing: the agent holds a key. Resolve data sources by name from the mandate via Lane C's registry; never import a source directly. |
| **C** | You own `/data` (Python). Build §10 Lane C MVP — this lane targets three Graph prize tracks *and* is the extension point for all future data providers. The registry and a source-agnostic `MarketSnapshot` come first; the Graph adapters are its first two consumers. The MCP server must be a genuinely standalone reusable product with its own `SKILL.md`. Live gateway data only on the demo path. Timebox x402 to 90 minutes behind a feature flag with a fallback. |
| **D** | You own `/venues` (Python + your own Foundry project at `/venues/aqua/solidity/`). **Register for the Uniswap API key first, before writing any code**, and confirm `.env` is gitignored before you paste it in. Build §10 Lane D MVP. Use SwapVM in Aqua mode (`useAquaInsteadOfSignature = true`) — 1inch scores it higher. You also own `FEEDBACK.md`. Never touch `/contracts`. |
| **E** | You own `/web` (Next.js/TS, Windows host — Node 20.13 and pnpm 9.5 are already installed). Build §10 Lane E MVP against the frozen routes in §8 and Lane A's ABIs. This is the judge-facing surface — the agent's visible reasoning (data consulted, with provenance → reasoning → tx hash) is the product, not a debug panel. |

---

## 14. Known risks

| Risk | Mitigation |
|---|---|
| Instance lands in Ubuntu-20.04 (the default) and hits `GLIBC_2.34 not found` | §2 + `CLAUDE.md` state `wsl -d Ubuntu-24.04` explicitly; Lane A's prompt repeats it |
| `python` on PATH is a dead Store stub | §2 + `CLAUDE.md`; project pins 3.12 via `uv`; Anaconda 3.12.7 as fallback |
| x402 hand-rolled in Python | Feature-flagged, API-key fallback, 90-min timebox (Lane C) |
| SwapVM program encoding | Done in Solidity via official `ProgramBuilder`, not reimplemented (Lane D) |
| `totalAssets()` with mixed holdings | Chainlink Base feeds at MVP; do not read Aqua virtual balances |
| Lane E blocked on Lane B | Routes frozen in Wave 0; Lane B serves fixtures from hour 2 |
| Schema drift across Python/TS | Single JSON Schema source + shared golden fixtures |
| Data layer ossifies around The Graph | Registry + source-agnostic `MarketSnapshot` from hour 1; dummy-source test in Lane C's DoD |
| Windows-only artifacts break the macOS handoff | §3 cross-platform rules; `docs/setup.md` dual-column; fresh-clone check at 10:00 |
| Anvil unreachable from Windows clients | `--host 0.0.0.0` baked into `scripts/anvil-fork.sh` |
| API key committed | `.gitignore` for `.env` is a Wave 0 deliverable, landed before any key exists |
| Public Base RPC too slow/rate-limited to fork against | Archive-capable `BASE_RPC_URL` is a blocking hour-0 credential (§8.1), not an afterthought — every lane sits on the fork |
| Graph key skipped because x402 "doesn't need one" | x402 is the risky path; its fallback needs the key. Both listed as blocking in §8.1 |
| Instances ignore the rules | `CLAUDE.md` is auto-loaded — rules land without anyone remembering to paste them |
| Audit trail too thin for judges | Push on every meaningful change from hour 0; Wave 0 lands the first push |
| Mainnet demo run fails live | Rehearse on fork; capture BaseScan links early; keep fork demo as fallback |
