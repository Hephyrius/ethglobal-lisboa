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

### 2.3 🟠 One open cross-lane request, and it is safety-critical

**#17 (D→B) — do not drop or reorder Aqua approval steps.** Verified against the real contract:
`Aqua.ship()` **succeeds with zero allowance**, returning a valid strategy hash and non-zero
balances, because shipping moves no tokens — the allowance is consumed later when a taker fills.
A missing approval therefore produces a position that looks healthy in every observable way and is
**silently never fillable**. If any allowance-check optimisation is ever added to the harness, Aqua
must be exempt. Lane B should acknowledge and pin this with a test.

**#19 (C→B,E) — add `"aave"` to the golden mandate.** ✅ **Done.** `permitted_data_sources` is now
`["messari", "aave", "token_api"]`. Verified safe first: no test pins the exact list, and
`agent/tests/test_integration_lanes.py:87` asserts `granted <= registry.available()`, which holds
because Lane C registers `aave`. 414 tests green after. The moonwell-vs-aave comparison now runs on
the golden path by default.

### 2.4 🟠 Submission gates still open

| Gate | State |
|---|---|
| Uniswap Developer **Feedback Form** | ❌ **Needs a human.** `FEEDBACK.md` is written and substantive (139 lines); the *form* is a separate hard requirement |
| README points at contracts + lines | ✅ **Done.** Rewritten as a submission document; every sponsor integration links to specific files and line numbers, all 29 link targets verified to resolve |
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

### 2.6 🟡 Environment gotchas found during this audit

**A stale `next dev` blocks `next build`.** Three node processes from 04:25 hold `.next/trace`, so
the build dies with `EPERM`. Not a code defect — but it will look like one at 09:55. Kill the dev
server before building.

**`.env` had CRLF line endings.** ✅ **Fixed** — 0 CR bytes, verified clean under WSL bash. Note
`git add --renormalize .` found **zero** tracked files to fix: `.gitattributes` landed early enough
in Wave 0 that the committed tree never accumulated CRLF, so the problem was confined to the
gitignored `.env`, which renormalize cannot reach by definition.

**`BASE_RPC_URL` is the public `https://mainnet.base.org`, not an archive endpoint.** It works today
— 76 forge tests pass against it and Lane D verified state overrides — but it is the rate-limited
one, and five lanes plus a live demo is exactly the load it degrades under. An Alchemy free-tier key
is a five-minute swap that removes a class of demo-day failure.

---

## 3. Per-lane extensions, mapped to what each track actually rewards

Ordered by prize-value-per-hour. Nothing here starts until §2.1 lands.

### 3.1 The Graph — $11K across three tracks · biggest upside remaining

**Track 3 (Composable, $3K) is the weakest of the three right now** and also the cheapest to fix.
It wants *two or more Graph products composed*. We have Messari subgraphs + Token API — but Token
API is dark for want of a JWT, and x402 has never made a real payment.

| Extension | Owner | Why it scores |
|---|---|---|
| ~~Add `"aave"` to the golden mandate~~ | Wave 0 | ✅ **Done** — see §2.3 |
| **A Chainlink on-chain price source** | Lane C | See below. Unblocks price facts *without any credential* |
| **Get `TOKEN_API_KEY`** | Lane C | Lights up the Graph Token API → a second Graph product genuinely in the path. Still worth having, but no longer blocking |
| **Make one real x402 payment** | Lane C | The narrative beat: *the agent pays for its own market data out of its own wallet, no API key*. Third Graph product, and the thing judges will remember |
| **Publish the MCP server so `uvx curator-mcp` works** | Lane C | Track 1 ($5K) demands *reusable tooling, not an app*. A judge who can install and run it in their own Claude Desktop is a categorically stronger submission than a directory in our repo |

The MCP publish is the highest-leverage item on this list: Track 1 is the largest single Graph prize
and "is this genuinely reusable?" is precisely its judging criterion.

#### Price facts without a credential — use Chainlink, not CoinGecko

`TOKEN_API_KEY` needs its own Graph Market JWT (`GRAPH_API_KEY` 401s there), so prices are currently
absent from every snapshot. The obvious fallbacks are CoinGecko or a Uniswap pool spot read.
**Prefer a Chainlink on-chain source.** Verified live on the fork while writing this:

```
ChainlinkEthUsdFeed  0x71041dddad3595F9CEd3DcCFBe3D1F4b0a16Bb70   (already in deployments/base-fork.json)
latestRoundData() → answer 0x2b485f8c38, decimals 8  →  $1,858.97, fresh updatedAt
```

Four reasons it wins here:

1. **The vault already prices holdings with it.** `totalAssets()` values non-base holdings through
   `ChainlinkPriceLib.sol`. If the agent priced WETH from CoinGecko while the contract priced it
   from Chainlink, the agent could compute a rebalance the vault then values differently — the two
   would disagree about what the portfolio is worth. One oracle means agent, contract and UI cannot
   drift apart.
2. **The golden mandate already constrains to it.** `update_rules` permits widening `allowed_assets`
   *"only to assets with a Chainlink Base feed and >$50M TVL"* — so a Chainlink source covers, by
   construction, every asset the mandate can ever permit. The design already agrees with itself.
3. **No key, no rate limit** — an `eth_call` against the fork Lane C already has. CoinGecko's free
   tier is ~10–30 calls/min and will throttle mid-demo.
4. **It is a stronger proof of the registry claim.** Every source so far is GraphQL-over-HTTP. An
   on-chain RPC source shows the `DataSource` port abstracts *kinds* of provider, not just
   endpoints — which is the composability argument made concrete.

CoinGecko is reasonable as a *third* rung if coverage beyond Chainlink's feed list is wanted. Skip
Uniswap pool spot: `sqrtPriceX96` math plus pool discovery, for a manipulable number Chainlink
already gives cleanly — and Lane D's `/quote` path already yields a market-derived price if one is
ever needed.

**Keep `token_api` registered regardless.** It degrades into `snapshot.errors`, which is the designed
behaviour, and lights up the moment a JWT appears. Removing it would weaken Track 3; Messari + Aave
subgraphs + x402 still carry the composition either way.

*Caveat worth stating:* sharing an oracle with the contract means the agent cannot cross-check a bad
feed. Lane A covers that at the contract layer — `totalAssets()` reverts rather than returning a
wrong number when a feed is stale. Note `priceMaxAge` is `0` on the fork, so staleness checking is
**off**; it should be set for the mainnet run.

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

Per-lane detail is in §5. This is the shape of it.

**Already done (Wave 0)** — ~~golden mandate grants `aave`~~ · ~~submission README~~ ·
~~`.env` line endings~~

**Now → +2h — unblock the demo**
1. **Lane B:** `AGENT_PRIVATE_KEY` = anvil #1 → land one `executeBatch` (§2.1). *Blocks 3 of 5 lanes.*
2. **Lane C, in parallel:** publish the MCP server; add the Chainlink price source (§3.1)
3. **Human:** `X402_PRIVATE_KEY`, `TOKEN_API_KEY`, `BASESCAN_API_KEY`; consider swapping
   `BASE_RPC_URL` for an archive endpoint (§2.6)
4. **Lane E, once B confirms:** sign a deposit
5. **Everyone:** write your `docs/handoff.md` section — macOS takes over at 10:00

**+2h → +5h — track extensions**
6. Real x402 payment + Token API live (Graph Track 3)
7. Aqua ship from the deployed vault, then a taker fill (1inch — the transfer they ask to see)
8. SwapVM program parameters surfaced in the feed

**Refine window**
9. Mainnet deploy + one funded end-to-end cycle, capture BaseScan links
10. Demo video
11. **Submit the Uniswap Developer Feedback Form** — needs a human, do not leave it to the last hour

---

## 5. Lane continuation briefs — **find your lane and start here**

### Read this first, whichever lane you are

The fork on `localhost:8540` is **live and holds state other lanes depend on**. Verified at the time
of writing: block 49,077,777, chainId 8453, vault `0x0E2c0e50E67B96C9C401C94e111a3DBD00DEB5d1`
holding **2,500 USDC**, agent account funded with gas.

> ⚠️ **Do not restart anvil.** The deployed vault exists only in that instance's memory. Restarting
> destroys it and forces a Lane A redeploy — the easiest way to lose twenty minutes here.

Also: read `/CLAUDE.md` and your claim in [docs/active-work.md](../docs/active-work.md). Stage
explicit paths (`git add <your-dir>/ docs/build-log.md docs/active-work.md`), **never `-A`** —
requests #14 and #21 show a day of Lane E's work already got attributed to Lane B that way, and
1inch scores commit history. Write your `docs/handoff.md` section; macOS takes over at 10:00 and
only Lane E has written one. Commit and push continuously.

### Three lanes touch the same vault — sequence, don't collide

Lane B's write, Lane E's deposit and Lane D's taker fill all mutate vault `0x0E2c…B5d1`. Lane E
already flagged this and deliberately did not broadcast, *"because it would have mutated fork state
other lanes assert against."* They were right. So:

| Start | Lane | Why now |
|---|---|---|
| **Now** | **B** | Blocking everything. Needs the vault to itself. |
| **Now** | **C** | Never touches the chain — fully parallel, and holds the highest-value work left. |
| After B confirms its write | **E** | Deposit mutates the vault B is asserting against. |
| After B lands a ship | **D** | A taker fill needs a position to fill. |
| Probably not | **A** | Done. Only remaining work needs `BASESCAN_API_KEY`. |

---

### Lane B — `agent/` · **start now, blocking**

**Land the first on-chain write.** Every piece of the write path is independently green and the
chain has never been run end to end — you verified reads and said so yourself in request #11. 1inch
requires on-chain token transfers in the demo, so this gate is unmet and the demo currently contains
an untested step. Nothing else in phase 2 starts until this lands.

1. Set `AGENT_PRIVATE_KEY` to anvil account **#1** —
   `0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d` (`0x7099…79C8`).
   **Not account #0.** Your own request #11 warns the wrong key reads perfectly and reverts every
   write on an AccessControl check — it looks healthy until the first `executeBatch`.
2. Force a non-`held` decision. The vault holds USDC and no WETH, so a USDC→WETH rotation through
   Uniswap is the natural first write.
3. Land one `executeBatch`. **Record the tx hash in `docs/handoff.md`.**
4. **Acknowledge request #17 and pin it with a test** — `Aqua.ship()` succeeds with zero allowance
   and silently produces an unfillable position, so any allowance-check optimisation must exempt
   Aqua. This is the one place in the system where dropping a step fails quietly rather than loudly.

### Lane C — `data/` · **start now, parallel**

Highest-value work remaining, and zero chain contention.

1. **Publish the MCP server so `uvx curator-mcp` works for someone who has never seen this repo.**
   Graph Track 1 is $5K — the largest single prize on the board — and it asks exactly one question:
   is this reusable tooling, or an app? A directory in our repo does not answer that; a judge
   installing it into their own Claude Desktop does. **Verify from a clean temp dir, not from the
   workspace** — that is the whole point of the exercise.
2. **Add a Chainlink on-chain price source** — see §3.1. Unblocks price facts with no credential,
   stays consistent with how the vault values holdings, and proves the registry abstracts kinds of
   provider rather than just endpoints. Keep `token_api` registered alongside it.
3. If `X402_PRIVATE_KEY` and `TOKEN_API_KEY` appear, make one real x402 payment and light up the
   Token API. The agent paying for its own market data is the strongest narrative beat available.

### Lane E — `web/` · **after Lane B confirms its write**

1. **Sign the deposit.** It is the ~2 minute procedure in your own `docs/handoff.md`, and it is the
   last unverified path in the project. Wait for Lane B — you were right that broadcasting mutates
   state other lanes assert against.
2. Point `NEXT_PUBLIC_RPC_URL` at a real RPC for the mainnet run so explorer links come back.
3. Once Lane C lands, surface the x402 payment and the moonwell-vs-aave comparison in the feed.

> Gotcha that will look like a code failure: a stale `next dev` holds `.next/trace` and makes
> `next build` die with `EPERM`. Kill the dev server before building.

### Lane D — `venues/` · **after Lane B lands a ship**

1. **Demonstrate a taker filling an Aqua position.** Aqua's whole thesis is virtual balances
   becoming real transfers on fill — that fill *is* the on-chain token transfer 1inch asks to see,
   and nothing currently shows the vault earning as a maker. Prep the harness against your relay
   while you wait.
2. Optional: surface the chosen SwapVM program parameters so Lane E can render them. They score
   SwapVM usage higher; make it legible rather than implied.
3. `FEEDBACK.md` is written and good. **The Developer Feedback Form still needs a human** — it is a
   separate hard requirement and cannot be done by an agent.

### Lane A — `contracts/` · **likely nothing**

Done: 76 tests, deployed, every request against it closed. Only remaining items need
`BASESCAN_API_KEY` (`forge verify-contract`), and ENS subnames are explicitly cut. Also worth
setting `priceMaxAge` to something non-zero before any mainnet run — staleness checking is currently
off on the fork.

---

## 6. What I would cut if time runs short

In order of what to drop first: ENS subnames → taker fill → mainnet run (the fork demo is honest and
works) → SwapVM params in the UI.

**Never cut:** the on-chain write (§2.1), the Uniswap feedback form, the README rewrite, or the demo
video. Those are the difference between a working project and a scored one.
