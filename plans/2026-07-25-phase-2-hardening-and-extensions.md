# Phase 2 — Hardening & Track Extensions

**Written at the MVP checkpoint, after auditing all five lanes.** Supersedes nothing; extends
[the master build plan](2026-07-25-master-build-plan.md). Same lane ownership rules apply.

---

## 1. Verified state — what I actually ran, not what the table claims

| Check | Result |
|---|---|
| `forge test` (Ubuntu-24.04, live `BASE_RPC_URL`) | **76 passed, 0 failed** — incl. 7 fork tests against real Base state |
| `uv run pytest packages/schema/python agent data venues` | **414 passed, 3 skipped** |
| `next build` | Builds (Lane E verified). Blocked *locally* right now — see §2.6 |
| Git | 65 commits, **all pushed**, clean tree |
| Deployed vault (fork) | `0x0E2c…B5d1` · 2,500 USDC · agent `0x7099…79C8` · share price exactly 1e18 |
| Live agent tick | Health green on 3 seams; returns `held` in 55.5s, 0 retries, citing **3 live Messari facts** |

**This is a genuinely strong position.** Four lanes complete, one integrated end-to-end, live Graph
data on the demo path, and every sponsor's core integration proven. The gaps below are mostly *last
mile*, not *missing middle*.

---

## 2. Critical path — do these before any extension

### 2.1 🔴 Nothing has ever been written on-chain by the agent

The single biggest risk, and it is easy to miss because every piece is independently green:

- Lane A proved an agent approval through the vault — **in a Foundry test**
- Lane D proved Aqua `ship()`/`dock()` from a contract maker — **through a test relay**
- Lane B verified `Web3VaultClient` reads, and states plainly: *"no write has been submitted
  on-chain yet"*
- Lane E: *"deposit and withdraw have never been signed"*
- The one live tick returned **`held`** — so the execution path was never exercised

Every link is tested. **The chain has never been run end to end through the real stack.**

1inch requires *"onchain execution of token transfers must be presented during demo."* Until a real
`executeBatch` lands from the harness, that gate is unmet and the demo has an untested step in it.

**Owner: Lane B + Lane A jointly. Blocking everything else.**

1. Set `AGENT_PRIVATE_KEY` to anvil account **#1** (`0x7099…79C8`) — *not* #0. Cross-lane request
   #11 warns this reads perfectly and then reverts every write on an AccessControl check.
2. Force a non-`held` decision (a mandate whose constraints make rotation obviously correct, or a
   direct `ExecutionPlan` submission) and land one `executeBatch`.
3. Record the tx hash in `docs/handoff.md`.

### 2.2 🔴 Credentials that gate whole features

`.env` currently has **4 of 9** values set.

| Missing | Consequence |
|---|---|
| `AGENT_PRIVATE_KEY` | §2.1 — no on-chain writes at all |
| `TOKEN_API_KEY` | Price facts absent from every snapshot. Needs its **own** Graph Market JWT — `GRAPH_API_KEY` returns 401 (Lane C, request #19) |
| `X402_PRIVATE_KEY` | The x402 path has never made a real payment — see §3.1 |
| `BASESCAN_API_KEY` | No `forge verify-contract`; judges cannot read the source Uniswap's rules require the README to point at |
| `DEPLOYER_PRIVATE_KEY` | No mainnet demo run |

`uniswap_key` is set under the legacy lowercase name — fine, `venues/config.py:23` accepts both.

### 2.3 🟠 Two open cross-lane requests, one safety-critical

**#17 (D→B) — do not drop or reorder Aqua approval steps.** Verified against the real contract:
`Aqua.ship()` **succeeds with zero allowance**, returning a valid strategy hash and non-zero
balances, because shipping moves no tokens — the allowance is consumed later when a taker fills.
A missing approval therefore produces a position that looks healthy in every observable way and is
**silently never fillable**. If any allowance-check optimisation is ever added to the harness, Aqua
must be exempt. Lane B should acknowledge and pin this with a test.

**#19 (C→B,E) — add `"aave"` to the golden mandate.** Blocked because the golden mandate lives in
frozen `packages/schema/fixtures/`. **I own Wave 0, so I will action this** — see §3.1.

### 2.4 🟠 Submission gates still open

| Gate | State |
|---|---|
| Uniswap Developer **Feedback Form** | ❌ **Needs a human.** `FEEDBACK.md` is written and substantive (139 lines); the *form* is a separate hard requirement |
| README points at contracts + lines | ❌ Root README is still *"Birds aren't real part 2"* |
| Demo video (2–4 min) | ❌ Not started |
| `docs/handoff.md` | ⚠️ Only Lane E has written a section |
| Mainnet demo run | ❌ Not attempted |
| Commit attribution | ⚠️ See §2.5 |

### 2.5 🟡 `git add -A` has muddied per-lane attribution

Requests #14/#21, still open. Commit `f0f51fd` ("Lane B: verified against Lane A's real fork")
contains 23 `web/**` files — a day of Lane E's work attributed to Lane B. Lane D reports the same
happening to its `docs/` edits twice.

Nothing is lost and nothing needs reverting. But 1inch scores commit history, so from here every
lane stages explicit paths: `git add <lane-dir>/ docs/build-log.md docs/active-work.md`.

### 2.6 🟡 Two environment gotchas found during this audit

**A stale `next dev` blocks `next build`.** Three node processes from 04:25 hold `.next/trace`, so
the build dies with `EPERM`. Not a code defect — but it will look like one at 09:55. Kill the dev
server before building.

**`.env` has CRLF line endings.** Sourcing it in bash emits `$'\r': command not found`. Harmless
today because the values still parse, but `scripts/anvil-fork.sh` sources it, and a value with a
trailing `\r` will produce a baffling failure. Convert to LF.

---

## 3. Per-lane extensions, mapped to what each track actually rewards

Ordered by prize-value-per-hour. Nothing here starts until §2.1 lands.

### 3.1 The Graph — $11K across three tracks · biggest upside remaining

**Track 3 (Composable, $3K) is the weakest of the three right now** and also the cheapest to fix.
It wants *two or more Graph products composed*. We have Messari subgraphs + Token API — but Token
API is dark for want of a JWT, and x402 has never made a real payment.

| Extension | Owner | Why it scores |
|---|---|---|
| **Add `"aave"` to the golden mandate** | **Wave 0 (me)** — fixtures are frozen | Turns the feed from one protocol into a real comparison: **moonwell 12.74% on $14.5M vs aave-v3 3.41% on $174.9M**. "Highest yield is not the deepest market" is exactly the reasoning a curator should visibly do, and it is *one word*, no code — which is itself the Track 3 argument about shared schemas |
| **Get `TOKEN_API_KEY`** | Lane C | Lights up price facts → a second Graph product genuinely in the path |
| **Make one real x402 payment** | Lane C | The narrative beat: *the agent pays for its own market data out of its own wallet, no API key*. Third Graph product, and the thing judges will remember |
| **Publish the MCP server so `uvx curator-mcp` works** | Lane C | Track 1 ($5K) demands *reusable tooling, not an app*. A judge who can install and run it in their own Claude Desktop is a categorically stronger submission than a directory in our repo |

The MCP publish is the highest-leverage item on this list: Track 1 is the largest single Graph prize
and "is this genuinely reusable?" is precisely its judging criterion.

### 3.2 1inch — $5K · one gap between proven and demonstrable

Aqua/SwapVM in Aqua mode is done and proven from a contract maker. What is missing is the thing
they explicitly ask to *see*.

| Extension | Owner | Why |
|---|---|---|
| **Land a real `ship()` from the deployed vault on the fork** | Lane B + D | Closes §2.1 for this track specifically |
| **Show a taker filling the position** | Lane D | Aqua's whole thesis is virtual balances becoming real transfers on fill. A fill is the *token transfer* the rules name — and it demonstrates the vault earning as a maker, which nothing currently shows |
| **Surface the SwapVM program in the UI** | Lane E | "Agent chose these program parameters" makes SwapVM visible rather than implied. They score SwapVM usage higher; make it legible |

### 3.3 Uniswap — $7K · integration done, evidence thin

| Extension | Owner | Why |
|---|---|---|
| **Submit the Developer Feedback Form** | **Human** | Hard requirement. `FEEDBACK.md` alone does not satisfy it |
| **Rewrite root `README.md`** | Wave 0 / whoever is free | Their rules: *"make sure your README clearly points to the relevant contracts and lines of code."* Currently a two-line joke |
| **Execute one real swap through the vault** | Lane B + D | "Core functionality such as trade execution" — currently proven only in tests |

### 3.4 Lane A — contracts

Solid: 76 tests, deployed, ABIs published, every request against it closed. Extensions are
optional polish:

- `forge verify-contract` on the mainnet deploy (needs `BASESCAN_API_KEY`) — judges reading verified
  source is worth more than another test
- ENS subname with `agent:mandate-hash` text record — the parked stretch. **Only if everything else
  is done**; it is narrative, not a submission gate, and we are not entering the ENS track

### 3.5 Lane E — dApp

- **Sign a deposit** (~2 min per the handoff doc) — closes the last unverified path
- Point `NEXT_PUBLIC_RPC_URL` at a real RPC for the mainnet run so explorer links return
- Show the x402 payment and the multi-protocol comparison in the feed once §3.1 lands

---

## 4. Sequencing

**Now → +2h — unblock the demo**
1. `AGENT_PRIVATE_KEY` = anvil #1 → land one `executeBatch` on the fork (§2.1)
2. Add `"aave"` to the golden mandate (Wave 0)
3. `TOKEN_API_KEY`, `X402_PRIVATE_KEY`, `BASESCAN_API_KEY`
4. Lane E signs a deposit
5. Everyone writes their `docs/handoff.md` section — macOS takes over at 10:00

**+2h → +5h — track extensions**
6. Publish the MCP server (Graph Track 1 — highest leverage)
7. Real x402 payment (Graph Track 3)
8. Aqua ship from the deployed vault + a taker fill (1inch)
9. Rewrite root README pointing at contracts and lines (Uniswap gate)

**Refine window**
10. Mainnet deploy + one funded end-to-end cycle, capture BaseScan links
11. Demo video
12. **Submit the Uniswap Developer Feedback Form** — do not leave this to the last hour

---

## 5. What I would cut if time runs short

In order of what to drop first: ENS subnames → taker fill → mainnet run (the fork demo is honest and
works) → SwapVM params in the UI.

**Never cut:** the on-chain write (§2.1), the Uniswap feedback form, the README rewrite, or the demo
video. Those are the difference between a working project and a scored one.
