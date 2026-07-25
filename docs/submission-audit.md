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

## What is actually left, and who can do it

**Only three things, and all three need a human.**

1. **Rotate the credentials** exposed in `env.txt` (request #53). PyPI publish
   token first — it can push malicious versions of three packages that are
   already live.
2. **Flip the repo public.** Six of the eight tracks require it. Do this *after*
   step 1: going public is what turns a private-repo exposure into a published
   one, because the whole history goes with it.
3. **Record the 2–4 minute video** and **submit the Uniswap Developer Feedback
   Form.**

Nothing on this list is code.
