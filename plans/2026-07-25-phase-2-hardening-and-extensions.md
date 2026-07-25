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

**Keys are now generated. Two wallets need funding before they do anything.**

Generated with `cast wallet new` and written straight to `.env` — the private keys were never
echoed. Addresses verified against `cast wallet address`:

| Var | Address | State |
|---|---|---|
| `AGENT_PRIVATE_KEY` | `0x70997970C51812dc3A010C7d01b50e0d17dc79C8` | ✅ **Set** — anvil account **#1**, holds `AGENT_ROLE` on the fork vault. Well-known public test key, not a secret. §2.1 is unblocked. |
| `X402_PRIVATE_KEY` | `0x64D21ebD9C0872dab5Cc69Dafc7Acce7CF16fBb7` | ⚠️ **Set but unfunded** — needs a few dollars of USDC on **real Base** (`0x8335…2913`). Queries cost fractions of a cent. |
| `DEPLOYER_PRIVATE_KEY` | `0x50c29464C591079dd6d9b2B7464884Cba10a6909` | ⚠️ **Set but unfunded** — needs ETH for gas plus ~$20 USDC for the mainnet demo run. |

x402 settles through a facilitator from a signed payment payload, so the x402 wallet should need
USDC but little or no ETH — send a few cents' worth anyway rather than debug that assumption live.

**Now set, with caveats:**

| Var | State |
|---|---|
| `TOKEN_API_KEY` | ✅ **Set** (Graph Market JWT) and **authenticating** — the 401 is gone. But all four of Lane C's `PRICE_PATHS` are wrong; the working route is `/evm/swaps`. Fully debugged in request #22. |
| `ETHERSCAN_API_KEY` / `BASESCAN_API_KEY` | ⚠️ **Set but unusable for Base.** Etherscan V2 free tier rejects this chain outright, and basescan V1 is deprecated. **Verify with Blockscout instead — no key needed.** Request #23. |
| `GRAPH_MARKET_API_KEY` | Set. The Market key paired with the JWT; the subgraph gateway continues to use `GRAPH_API_KEY`. |

`uniswap_key` is set under the legacy lowercase name — fine, `venues/config.py:23` accepts both.

> **Swapping to mainnet:** `AGENT_PRIVATE_KEY` is currently the anvil key and is correct *for the
> fork only*. Replace it at the mainnet run — and note the plan's suggestion that the agent and
> x402 wallets be the same address there, since the agent paying for its own market data out of its
> own wallet is the narrative.

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

*The caveat that was here — "sharing an oracle with the contract means the agent cannot cross-check
a bad feed" — is now retired.* The Token API turns out to work on Base after all (request #22), and
it derives price from **executed dex swaps** rather than an oracle. Registering both gives two
genuinely independent price sources: Chainlink said **$1,858.97**, the last WETH/USDC swap on Base
said **$1,857.03** — 0.1% apart, from completely different mechanisms. That is a real
cross-validation, and a disagreement between them is exactly the signal a curator should act on.

Lane A still covers the contract side: `totalAssets()` reverts rather than returning a wrong number
when a feed is stale. Note `priceMaxAge` is `0` on the fork, so staleness checking is **off**; set
it for the mainnet run.

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

1. ✅ **`AGENT_PRIVATE_KEY` is already set for you** — anvil account **#1**
   (`0x70997970C51812dc3A010C7d01b50e0d17dc79C8`), the holder of `AGENT_ROLE` on the fork vault.
   Verified by `cast wallet address`. Your own request #11 warned that account #0 reads perfectly
   and reverts every write on an AccessControl check; that trap is closed. Just confirm the address
   the harness logs at startup matches `GET /vault/{addr}/state`'s reported `agent`.
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
3. **`X402_PRIVATE_KEY` is set** — wallet `0x64D21ebD9C0872dab5Cc69Dafc7Acce7CF16fBb7`, freshly
   generated. It is **not funded yet**, so build and test the flow against it and expect the payment
   step to fail on insufficient balance until someone sends it USDC on real Base. Everything up to
   that point — the 402, the payload construction, the signature — you can verify now. The agent
   paying for its own market data is the strongest narrative beat available.
4. **`TOKEN_API_KEY` is set and the Token API works — but your four `PRICE_PATHS` are all wrong, in
   two different ways.** Fully debugged against the live API in request #22: two of the routes do
   not exist, and the other two use `network_id=` where the API wants `network=`. The working call
   is `GET /evm/swaps?network=base&pool={pool}&limit=1`, which returns a `price` field directly.
   Read #22 before touching the file — it has the verified pool address and the response shape, and
   will save you the twenty minutes of probing it took to find.

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

## 6. Bounty compliance audit — checked against the literal prize text

Re-read [the prize page](https://ethglobal.com/events/lisbon2026/prizes) and checked each
deliverable against the exact wording rather than from memory. One item is a real scope problem, one
turned out to be much less of a problem than assumed.

### ✅ The 1inch mainnet worry was overblown — read the parenthetical

> *"Onchain execution of token transfers **should** be presented during the final demo
> **(local forks are ok)**."*

**Local forks are explicitly acceptable, and it says "should", not "must".** The mainnet run is
therefore *polish, not a gate* — demote it accordingly (§7).

One subtlety that still matters: **an Aqua `ship()` transfers no tokens.** That is the entire point
of virtual balances. So a ship alone does not satisfy "onchain execution of token transfers" — the
qualifying event is either the **Uniswap swap** through the vault or a **taker filling** the Aqua
position. Lane B's §2.1 write closes this on the fork, with no mainnet needed.

Everything else here is already met: official Aqua/SwapVM contracts ✅, SwapVM used (scored higher)
✅, 65+ commits with no final-day squash ✅.

### 🔴 The MCP server does not install outside this workspace — and that is 25% of Track 1

Verified empirically, simulating what a judge does:

```
$ uv pip install ./data/curator_mcp        # in a clean venv, outside the repo
× No solution found when resolving dependencies:
╰─▶ Because curator-data was not found in the package registry and
    curator-mcp==0.1.0 depends on curator-data, ...unsatisfiable.
```

The chain is `curator-mcp → curator-data → curator-schema`, and **none are published**. Anyone
following the `uvx curator-mcp` invocation in our own `SKILL.md` hits this immediately.

This is not cosmetic. Track 1's published judging criteria are **Usefulness to builders 30% ·
Reusability & completeness 25% · Effective use of The Graph 20% · Technical execution 15% ·
Innovation 10%**. An uninstallable package fails the second-heaviest criterion outright, and the
track's defining requirement is *"reusable tooling or infrastructure … not a single end-user app."*
A server nobody but us can run is, functionally, part of our app.

**Fix — publish to PyPI. All three names are free** (verified: `curator-mcp`, `curator-data`,
`curator-schema` all return 404 on PyPI). Publish bottom-up: `curator-schema` → `curator-data` →
`curator-mcp`, then verify `uvx curator-mcp` from a clean machine. That works regardless of repo
visibility, which matters because the repo stays private until submission.

*Alternatives considered:* `[tool.uv.sources]` git refs only work once the repo is public, so they
cannot be tested before submission day. Vendoring `curator-data` into the server duplicates the code
the registry design exists to share. Publishing is both the cleanest fix and the strongest possible
evidence of reusability. **Owner: Lane C.**

### 🟠 Smaller gaps

| Gap | Requirement | State |
|---|---|---|
| `LICENSE` | Track 1: *"Open-source the code"* | ✅ **Added** (MIT, matching what `curator_mcp/pyproject.toml` already declared) |
| Demo video | **All three** Graph tracks: *"a 2–4 minute demo video"* | ❌ Not started. Note the length is specified — 2–4 minutes, not 5. |
| Uniswap Feedback Form | *"a completed submission to the Uniswap Developer Feedback Form"* — *"Submissions without it will be reviewed and audited before winners are finalized"* | ❌ **Needs a human** |
| Public repo | Graph (all tracks) + Uniswap | ⏳ Private by choice until submission. **Flip before submitting** — it is a stated requirement everywhere. |

### Requirements already satisfied — no action

*"Build the project during the event"* (all commits 24–25 July) · *"Consume live data from a Graph
provider; mocked or static data does not qualify"* (verified live Messari facts in Lane B's tick) ·
*"an AI/agent component that reasons over or acts on the data, not just prints a raw query result"* ·
*"compose two or more of The Graph's products"* (Messari standardized subgraphs + Aave + Token API +
x402) · *"README clearly points to the relevant contracts and lines of code"* (done, 29 links
verified) · `FEEDBACK.md` ✅ · valid Uniswap API key ✅.

One wording note for the submission form: Track 2 asks you to *"briefly describe how The Graph is
used (which Subgraphs, endpoints, tools)"*. Name the specific subgraph IDs — that is a cheap point
on a 10% "demo & clarity" criterion.

---

## 7. What I would cut if time runs short

Revised after the compliance re-read (§6). **The mainnet run moved sharply down** — 1inch accepts
local forks in writing, and no other sponsor asks for mainnet at all. It is credibility polish now,
not a gate, and it is the most expensive remaining item in both time and risk.

Drop in this order: ENS subnames → SwapVM params in the UI → **mainnet run** → taker fill.

**Never cut, in priority order:**

1. **The on-chain write** (§2.1) — the only thing standing between "every part is tested" and "the
   thing works". Also what satisfies 1inch's token-transfer requirement, on the fork.
2. **Publishing the MCP server** (§6) — 25% of the $5K track's score, and currently a hard fail.
3. **The Uniswap Feedback Form** — a stated requirement, and it needs a human.
4. **A 2–4 minute demo video** — required by all three Graph tracks.
5. **Flipping the repo public** before submitting.

Note the top two are cheap and the bottom three are the ones that get forgotten at 3am.
