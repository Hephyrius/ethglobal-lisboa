# Submission audit — every prize requirement, checked against the repo

Audited 2026-07-25 against the live prizes page, not against our notes. Each row
quotes the sponsor's own wording and names the artifact that satisfies it.

> **The headline finding: we planned for 3 tracks worth $11K. There are 8 tracks
> worth $32K, and the repo appears to satisfy the requirements for all of them.**
> The master plan was written from an earlier read and under-counted The Graph
> ($15K across 4 tracks, not $11K) and missed both Continuity tracks. Nothing new
> needs building for the extra five — see the caveat on Continuity below.

| Sponsor | Tracks | Total |
|---|---|---|
| The Graph | 4 | $15,000 |
| Uniswap Foundation | 2 | $10,000 |
| 1inch | 2 | $7,000 |
| | | **$32,000** |

> **Wave 3 revises this down by one track.** The four-criteria pass at the bottom of this file
> recommends **dropping Uniswap Track 2 (Stack Contribution, $3,000)** rather than arguing for it.
> A shoehorned integration invites a judge to discount the five tracks where we are strong, so the
> number to plan against is **7 tracks / $29,000**.

⚠️ **Continuity tracks — confirm at the booth before counting on them.** The
prizes page states their requirements as identical to the base track. At
ETHGlobal that label often also implies a commitment to keep building after the
event, which is a claim about intent rather than about code. Ask; do not assume.

---

## The Graph — Track 1 · Best AI Tooling · $5,000

Judged: usefulness to other builders 30% · reusability & completeness 25% ·
effective use of The Graph 20% · technical execution 15% · innovation 10%.

| Requirement (their words) | Status | Evidence |
|---|---|---|
| "Submit reusable tooling or infrastructure (MCP server, SKILL, plugin, client config, or payment tooling), **not a single end-user app**" | ✅ | [`data/curator_mcp/`](../data/curator_mcp/) — a standalone MCP server with four tools. The vault dApp is visibly *a consumer* of it, not the product. |
| "The tooling must work against live blockchain data… Purely mocked or static datasets do not qualify" | ✅ | Live gateway queries; `AGENT_MODE=live` is gated by [`scripts/preflight.sh`](../scripts/preflight.sh) precisely because fixture mode answers everything convincingly. |
| "Open-source the code with a clear README or SKILL.md" | ✅ | [`SKILL.md`](../data/curator_mcp/SKILL.md) (114 lines) + [`LICENSE`](../LICENSE) (MIT). |
| "Submit a public repository and a 2–4 minute demo video" | ⬜ **human** | Repo is private until credentials are rotated. Video not recorded. |

**The 25% "reusability & completeness" criterion is the one we nearly failed.**
`pip install curator-mcp` had to actually work for a stranger. It does:
`curator-schema` 0.1.0, `curator-data` 0.2.0, `curator-mcp` 0.2.0 are on PyPI and
were verified installing into a clean Python 3.10 venv with no repo present.

## The Graph — Tracks 2 & 4 · Best AI Use Case · $3,000 + $4,000

Judged: effective use of The Graph 35% · usefulness & impact 25% · technical
execution 20% · innovation 10% · demo & clarity 10%.

| Requirement | Status | Evidence |
|---|---|---|
| "Use The Graph as a **load-bearing** source of blockchain data" | ✅ | The agent cannot decide without a `MarketSnapshot`; the Messari and Aave subgraph sources are what fill it. Remove them and the vault holds. |
| "Consume live data from a Graph provider. Mocked or static data does not qualify" | ✅ | Same gate as above. |
| "Include an AI/agent component that reasons over or acts on the data" | ✅ | A local model produces a validated `AllocationDecision`; `facts_used` ties each decision to the exact subgraph rows behind it, and the dApp renders that chain. |
| "Build the project during the event" | ✅ | Pushed commit history throughout. |

## The Graph — Track 3 · Composable or Standardized Products · $3,000

Judged: leverage of composability/standards 35% · **breadth 20%** · technical
execution 20% · usefulness 15% · demo & clarity 10%.

| Requirement | Status | Evidence |
|---|---|---|
| "Either compose two or more of The Graph's products, **or** build meaningfully on a standardized schema" | ✅ **both** | Three products — Messari subgraphs via the gateway, the Token API, and **x402 pay-per-query** — and the Messari *standardized* schema is what lets one query shape span N protocols. |
| "Simply querying one Subgraph with no composition or standardization does not qualify" | ✅ | Explicitly not that. |
| "Make the standards leverage clear" | ✅ | [`data/README.md`](../data/README.md) states it, and [`sources/protocols.py`](../data/curator_data/sources/protocols.py) is the demonstration: adding a protocol is a config row, not an adapter. |

**Breadth (20%) improved materially in Wave 1** — eight registered sources, four
added after the registry froze, each one file plus one line. `chainlink` is the
strongest single piece of evidence: it is a *contract read*, not an HTTP API, so
the registry demonstrably merges kinds of provider rather than kinds of endpoint.

## 1inch — Tracks 1 & 2 · Build an Aqua App · $5,000 + $2,000

Judged: "Projects utilizing SwapVM receive higher scoring during final judging."

| Requirement | Status | Evidence |
|---|---|---|
| "Official Aqua/SwapVM contracts must be used" | ✅ | Aqua `0x4999…6d31`, SwapVM `0x8fDD…958f` — the deployed contracts, unmodified. Programs are compiled by 1inch's own Solidity `ProgramBuilder` read via `eth_call`, never hand-encoded. |
| "Onchain execution of token transfers should be presented during the final demo (**local forks are ok**)" | ✅ | The Uniswap rotation moves real tokens on the fork. Note an Aqua ship deliberately moves none — that is the custody argument — so the swap is the qualifying transfer. |
| "Proper Git commit history (**no single-commit entries on the final day**)" | ✅ | Continuous pushed history. |
| SwapVM used (scoring bonus) | ✅ | Aqua mode, `useAquaInsteadOfSignature = true`. |

**R5 is green:** 7 e2e tests, gated on the vault→Aqua **allowance** rather than on
`safeBalances()`. A ship with no approval produces non-zero balances, a valid
hash and a successful transaction — and a position that can never be filled. The
allowance is the only observable that separates the two.

## Uniswap — Track 1 · Best API Integration · $7,000

| Requirement | Status | Evidence |
|---|---|---|
| "Integrate the Uniswap API with a valid API key from the Uniswap Developer Platform" | ✅ | `POST /quote` → `POST /swap`, `x-api-key`. [`venues/uniswap/client.py:155`](../venues/uniswap/client.py#L155) · [`:160`](../venues/uniswap/client.py#L160). |
| "A public GitHub repository with open-source code" | ⬜ **human** | Private until rotation. MIT licensed. |
| "a FEEDBACK.md file" | ✅ | [`FEEDBACK.md`](../FEEDBACK.md), 183 lines. |
| "a completed submission to the Uniswap Developer Feedback Form" | ⬜ **human** | Not submitted. |
| "Make sure your README **clearly points to the relevant contracts and lines of code**" | ✅ | Nine line-anchored links, all re-verified 2026-07-25. |

> Two of those links had silently drifted by one line when an unrelated
> `LoopBoundClient` refactor touched `client.py` earlier the same day. **A
> submission requirement can be broken by a change two files away**, so re-check
> the anchors immediately before submitting rather than trusting this row.

## Uniswap — Track 2 · Best Stack Contribution (Continuity) · $3,000

| Requirement | Status | Evidence |
|---|---|---|
| "Build on or extend the Uniswap open-source ecosystem using **any part of the Uniswap stack**" | 🟡 | We consume the Trading API rather than extending the stack. Defensible, not slam-dunk — the honest framing is the Permit2 signature-free path in [`venues/uniswap/plan.py`](../venues/uniswap/plan.py), which is a contract-maker integration pattern the API's `permitData` flow does not document. Worth asking the booth whether that counts. |
| FEEDBACK.md + form + public repo | see above | |

---

# Wave 3 · The four criteria, applied honestly

Everything above answers **criterion 1 — done to spec**, quoting the sponsor's wording against an
artefact. The Wave 3 feedback names three more, and the third is the one nobody usually does:

| # | Criterion | The question that actually tests it |
|---|---|---|
| 1 | Done to spec | Quote the sponsor's wording; show the artefact |
| 2 | Full potential | Are we using one endpoint where the prize rewards depth? |
| 3 | **Not shoehorned** | **If this integration were removed, would the product still work?** If yes, it is decoration. |
| 4 | Actually working | Verified live, *this* build — not "it worked once" |

**Verdicts re-derived 2026-07-26 against the running stack, not carried forward.** Two inherited
claims did not survive that, and both are corrected below.

| Track | 1 · Spec | 2 · Depth | 3 · **Not shoehorned** | 4 · Working now |
|---|---|---|---|---|
| Graph · AI Tooling | ✅ | ✅ | ✅ | ✅ |
| Graph · AI Use Case ×2 | ✅ | ✅ | 🟡 **see below** | ✅ |
| Graph · Composability | ✅ | ✅ | ✅ | ✅ |
| 1inch · Aqua + SwapVM | ✅ | ✅ | 🟡 | ✅ |
| Uniswap · API | ✅ | 🟡 | ✅ **strongest** | ✅ |
| Uniswap · Stack Contribution | ❌ **recommend dropping** | — | — | — |

## Criterion 3, track by track — and one inherited claim that is now false

### The Graph · AI Use Case — 🟡, and the audit above overstates it

The row above says *"Remove them and the vault holds."* **That was true when it was written and is
false in this build.** Measured rather than asserted, via `registry.sources_providing(kind)`:

| Fact kind | Graph-backed | Non-Graph | Survives removal? |
|---|---|---|---|
| `yield` | `messari`, `aave` | `defillama`, `morpho`, `peers` | **yes** |
| `price` | `token_api` | `chainlink` | **yes** |
| `tvl` | `messari`, `aave` | `defillama`, `morpho`, `peers` | **yes** |
| `utilization` | `messari`, `aave` | `morpho` | **yes** |
| `liquidity` | `messari` | — | **no — the only casualty** |

Wave 1 and Wave 2 added `defillama`, `morpho` and `chainlink`, and in doing so made the agent able
to decide without any Graph source at all. Strictly by criterion 3's test, that is a *yes, the
product still works.*

**The honest verdict, and we should say this ourselves rather than have it found:** The Graph is
**load-bearing in the shipped configuration and replaceable in principle.** Every preset and every
archetype grants `messari`; the demo path reads it; `liquidity` — the fact that distinguishes a real
rate from one quoted on a thin market, which is the whole thesis of the conservative mandate — comes
from nowhere else. But a data layer whose entire purpose was to be source-agnostic *should* survive
losing a provider, and ours does. **We should not claim irreplaceability that our own architecture
was designed to prevent.** That is a better answer than pretending the fallbacks are not there.

### 1inch · Aqua + SwapVM — 🟡, honestly

Would the product work without Aqua? **Yes** — Uniswap, Aave and Morpho cover swapping and lending,
and the vault would function as a yield rotator. Aqua is what makes it a *market maker*, which is a
capability, not a dependency.

What stops this being decoration is that the capability is real and now demonstrated end to end.
Lane D closed #29 this wave by **reading the deployed instruction table rather than trusting a
published tag** — no published version matches the deployment, and an `XYCConcentrate` entry `v1.0.1`
lacks put salt and the flat fee each one opcode low. Five previously-skipped tests now pass against
the real deployed Aqua and SwapVM: **a third-party taker fills, real ERC-20s move, and the vault
earns its maker fee.**

Against criterion 3 the fair statement is: **used for real, on-chain, not merely referenced — but
removable.** Idle capital routing through Aqua as a *standing* strategy would make it load-bearing;
what we have is a genuine, verified, optional capability.

### Uniswap · API — ✅, and it is our strongest criterion-3 answer

Remove it and **the vault cannot swap at all.** Aqua is a maker venue; Aave and Morpho are lenders.
Every rebalance in the product goes through the Trading API. This is the one integration whose
removal breaks the product outright, and it should be led with.

Criterion 2 is 🟡 rather than ✅: we use `/quote` → `/swap` and nothing else.

### Uniswap · Stack Contribution — ❌, and the recommendation is to **drop it**

The plan said *"make that argument properly or drop the track"*, so here is the call: **drop it.**

We consume the Trading API. We do not extend the stack. The available argument — that the Permit2
signature-free path in `venues/uniswap/plan.py` is a contract-maker pattern their `permitData` flow
does not document — is a *usage note*, and we already submit it through the channel that exists for
usage notes, which is `FEEDBACK.md`. Dressing the same material up as a stack contribution is
precisely the shoehorn criterion 3 exists to catch, **and a shoehorned integration is worse than an
absent one because it invites a judge to discount the five tracks where we are strong.**

Submit `FEEDBACK.md` against Track 1, where it is a requirement rather than a stretch.

## Criterion 4 — what is actually working, right now

Verified against the running stack on 2026-07-26, not inherited:

| | State |
|---|---|
| `scripts/preflight.sh` | **6/6** — ollama, fork at block 49078205, contracts deployed, funded, API live on all three seams, dApp responding |
| Aqua ship e2e (`test_slice_ship.py`) | **green** — 7 tests, gated on the vault→Aqua *allowance*, restored this wave after Lane A's ABI change erred them |
| `test_slice_read` · `test_slice_decide` · `test_slice_wave2` | green |
| **`POST /genesis/finalize`** | 🔴 **500 on every call — request #99.** The agent builds a 6-field `CreateParams` against the published 7-field ABI. Eight `test_slice_genesis` tests error, and the injection e2e cannot deploy its victim vault. **This is on the demo's critical path and must be fixed before any recording.** |
| Injection e2e (`test_slice_injection.py`) | Hostile vaults plant and verify on-chain; the behavioural half **skips** behind #99 |

### The "scripted decision" caveat is closed — with a correction

Wave 2 recorded that `act_000020`'s Aqua ship came from the `scripted` backend, so the submission had
to caveat that the decision was not model-authored. **That caveat is dead.** Read from the live
journal:

| Action | Backend | Retries | On-chain |
|---|---|---|---|
| `act_000036` | `qwen2.5:3b` | **0** | executed |
| `act_000046` | `qwen2.5:3b` | 2 | executed |
| `act_000049` | `qwen2.5:3b` | 1 | executed |

Three model-authored Aqua ships, one first-try. **We may say a model authored the market-making
decisions, and that it went on chain.**

⚠️ **Do not quote the bake-off's ❌ ship column against this.** That harness measures single-shot
authoring at temperature 0 on one synthetic book; the live loop retries. I had that backwards for
about an hour and the reasoning is written up in [`scripts/bakeoff/README.md`](../scripts/bakeoff/README.md).

### The model backing every claim here changed

The default backend is now **Grok** (`grok-4.20-0309-non-reasoning`) when `XAI_API_KEY` is set,
falling back to local Ollama without one. Measured: **~2s and ~$0.0015 per decision against 56s on
the 3B.** Zero invented facts across 24 measured trials on both models. Note that `GET /health`
currently reports the *Ollama* tag while running Grok (#100) — do not read it as evidence of which
model is live.

---

## What is actually left, and who can do it

**One code fix, then three things that need a human.**

0. 🔴 **Fix #99 — `POST /genesis/finalize` 500s.** Lane B. Genesis is the demo's primary path. Note
   the ordering trap: appending `deployer` alone will *revert* against the fork, which still runs the
   6-field factory. Either Lane A redeploys first, or the agent selects on deployed bytecode the way
   `tests/e2e/conftest.py` now does.

1. **Rotate the credentials** exposed in `env.txt` (request #53). PyPI publish
   token first — it can push malicious versions of three packages that are
   already live.
2. **Flip the repo public.** Six of the eight tracks require it. Do this *after*
   step 1: going public is what turns a private-repo exposure into a published
   one, because the whole history goes with it.
3. **Record the 2–4 minute video** and **submit the Uniswap Developer Feedback
   Form.**

Nothing on this list is code.
