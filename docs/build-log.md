# Build log

Append-only, **newest at the top**. Every non-trivial change gets an entry: what changed, **why**
(the important part), and what alternatives were rejected. Never rewrite another agent's entry.

This log is also part of the ETHGlobal audit trail — it evidences that decisions were made during
the hackathon window.

---

## 2026-07-25 — Lane A: the vault, and what "no human override" costs you

**What changed.** `contracts/` MVP complete. `CuratedVault` (ERC-4626, sole custodian, agent
`execute` surface, Chainlink valuation), `VaultFactory` (EIP-1167 clones), 69 unit tests with no
network dependency, 7 fork tests against real Base, a deploy script that publishes
`deployments/base-fork.json`, and flat ABIs in `contracts/abis/`. Usage doc at `contracts/README.md`.

**The central decision: how do you build an allowlist when nobody is allowed to hold the keys?**

The locked trust model ([initiate_plan §2](../plans/initiate_plan.md)) is that no human can override
the agent after genesis. Read literally, that means no `DEFAULT_ADMIN_ROLE` holder at all — which
also freezes the `execute` target allowlist forever. That collided with reality within the hour: the
Uniswap router address was still unconfirmed (cross-lane request #7, which Lane D resolved only by
reading a live API response), and an immutable list missing one address means every plan reverts and
the demo dies.

The resolution splits the difference along the line that actually matters — *can this power reach the
money?*

- `AGENT_ROLE` — the only role that can move value. Fixed at genesis.
- `GUARDIAN_ROLE` — can edit the target allowlist and **nothing else**.
- `DEFAULT_ADMIN_ROLE` — granted to nobody. `grantRole`, `revokeRole` and `renounceRole` all revert.

Widening the allowlist grants the guardian nothing it could exploit alone, because only the agent can
call `execute`. So the mutable thing is a blast-radius limiter, not a custody control. The residual
risk is real and is documented rather than hidden: a guardian *narrowing* the list can grief a
rebalance. That is liveness, not custody, and it was the right trade at 3am with a demo to make.

Renouncing needed closing explicitly. AccessControl lets any holder renounce its own role by default,
so the agent could have bricked the vault it curates. That is the one path where "no admin" is not
enough on its own.

**Valuation got the opposite answer, and that asymmetry is the point.** There is no setter for price
feeds at all, for anyone. That is the one place a mutable setting *is* exploitable — register a bogus
feed and you reprice every share, minting or redeeming at a number you chose. Same instinct
("operational flexibility") would have been a live vulnerability here rather than a convenience.

`VaultFactory` is where the flexibility went instead: it holds a **mutable default config** that each
vault snapshots and then freezes. Editable in the template, immutable in the instance holding
depositor money.

**Alternatives considered.** Making the allowlist agent-mutable — rejected, it makes the boundary
decorative, since the agent could allowlist anything it liked. Granting the deployer
`DEFAULT_ADMIN_ROLE` "just for the allowlist" — rejected, AccessControl's admin can grant *any* role
including `AGENT_ROLE`, so it is a human override wearing a hat. Restricting token targets to
`approve` only — genuinely attractive (it would stop `USDC.transfer(attacker, …)`), but rejected: the
trust model already grants the agent full latitude, it is not in the spec, and it would have blocked
Lane D at 4am with no one awake to unblock them. Cost of the boundary chosen: the allowlist bounds
*which contracts* the agent may reach, not what it may do there. Stated plainly in the README rather
than implied.

**Three smaller decisions worth recording.**

*`_decimalsOffset() = 12`.* OpenZeppelin's virtual-shares defence against the first-depositor
inflation attack, and it makes shares 18-decimal over a 6-decimal asset, which is what wallets
expect. The cost is a genuine trap for Lanes B and E: `convertToAssets(1e18)` returns a **6-decimal**
number. Documented loudly, asserted in tests, and flagged in `active-work.md` — including that the
Wave 0 `vault-state.json` fixture's `share_price` is 10^12 off its own totals.

*`totalAssets()` reverts on a bad price rather than valuing at zero.* Reverting blocks deposits and
withdrawals, which is unpleasant; valuing a held token at zero silently misprices shares and lets a
withdrawal drain value from everyone still in. Chose the loud failure. Softened where it is free:
a token with a zero balance is skipped before its feed is read, so a broken feed only blocks the
vault while it actually holds that token.

*`priceMaxAge = 0` disables the staleness check, and fork deploys use 0.* Not laziness — on a pinned
anvil fork the forked feed's `updatedAt` is frozen at the fork block while `block.timestamp` keeps
advancing, so any real bound starts failing minutes into a dev session and takes the whole vault down
with it. This is the sort of thing that eats an hour at 4am, so it is commented at the definition,
in the README, and in the deploy script.

**Dependencies: vendored, not submodules.** `forge install` uses git submodules, which live in the
repository-root `.gitmodules` — a shared file Lane D also writes for `venues/aqua/solidity/`, and
exactly the concurrent-edit collision Rule 7 exists to prevent. Vendored sources also mean a plain
`git clone` compiles on macOS at handoff with no `--recursive` and no half-empty `lib/`. Cost: ~2MB
committed. Lane D then found the real bill — vendored paths crossed Windows' 260-character
`MAX_PATH` and **aborted a fresh clone entirely** (request #11). Fixed at the source rather than
telling every teammate and judge to set `core.longpaths`: shortened `lib/openzeppelin-contracts*` to
`lib/oz*` and pruned the trees nothing compiles. 130 → 105 chars, 480 → 240 files, 3.7M → 2.2M.
Rejected soldeer (another registry to be down at 4am) and `core.longpaths` (pushes the problem onto
everyone who clones).

**Testing: two suites, deliberately.** The unit suite is 100% mock-based and needs no network,
because `forge test` has to be green on a fresh macOS clone at 10:00 where `BASE_RPC_URL` may not
exist — `.env` still has no archive RPC. The fork suite skips itself cleanly when there is no
endpoint. Three test bugs found and worth remembering: `vm.expectRevert` binds to the next
**external** call, so `vault.grantRole(vault.AGENT_ROLE(), x)` had the cheatcode matching the getter
and four role tests were passing without testing anything; `ChainlinkPriceLib` is `internal`, so it
inlines into the test contract and `expectRevert` has no call frame to attach to; and re-entering
`execute` is caught by the *role* check, not the reentrancy guard, so the guard's real job is the
permissionless entry points — a venue re-entering `deposit()` mid-rebalance to mint shares against
an understated `totalAssets()`.

**Verified against real state, not mocks.** Deployed to a live Base fork: 5,000 real USDC → `5000e18`
shares at a share price of exactly `1000000`; the agent set a real USDC allowance to real Permit2
through the vault (the exact first step of every Lane D Uniswap plan); non-agent `execute` reverted;
redeem returned 2,500 USDC. Every address in the deploy script was confirmed with `cast code` before
being written down, which caught an Aqua constant I had transcribed by hand into a different address.

**Environment note for whoever hits it next.** `cast` and `forge` making *direct* external HTTPS
calls hang indefinitely in this WSL setup, while `curl` to the same endpoint returns instantly. It is
not a blocker: `anvil --fork-url` works fine, and once anvil holds the fork everything else talks to
localhost. Point `forge test` and `forge script` at the anvil endpoint, not at the upstream RPC.

---

## 2026-07-25 — Lane E: trad-fi visual language, and three integration corrections

**What changed.** The dApp was restyled from dark-with-accent to an institutional light theme, and
three integration problems found by running it against the real fork and the real agent API were
fixed. `pnpm build` green; every page verified in a real browser (headless Edge) rather than
inferred from the build passing.

**Why the restyle.** The default DeFi convention — near-black ground, neon accent, pill chips,
monospace everywhere — signals "crypto-native tool". This product's claim is that an agent can do a
job real allocators do, so it should look like it belongs in that world: warm paper ground, serif
headings, hairline rules, tabular figures, tight corners, and colour only where it carries meaning.
Semantic colour names (`agent` / `data` / `ok` / `bad`) meant the whole change was mostly re-pointing
token values rather than editing components. No webfont — the serif and sans stacks resolve natively
on macOS and Windows, so a fresh clone at handoff still needs no network.

**Three things a browser found that a passing build did not.**

1. **The provenance badge was claiming LIVE with nothing loaded.** The landing page issues no API
   queries at all, and the aggregate defaulted to `live` when it had no reports. That is an
   assertion about data that was never fetched. It now reports `unknown` and renders nothing.

2. **The badge could sit on green over fixture data — the deep version of the trap it exists to
   prevent.** Lane B's `GET /health` (their cross-lane note #9) reports `mode` and `status`
   independently of whether requests succeed, and with the API up in fixture mode *every* request
   succeeds and validates. The badge would have been confidently green over
   `packages/schema/fixtures` served from the other side of the wire. `/health` is now folded into
   the same aggregate: `mode: "fixture"` or `status: "degraded"` turns it amber regardless of how
   well the requests went. Verified by running the agent API in fixture mode and confirming amber.

3. **`VaultState.share_price` has no declared scale, and the two conventions differ by 1e12.** The
   Wave 0 fixture reports it 1e18-scaled; the deployed vault's `convertToAssets(1 whole share)`
   returns a 6-decimal asset amount, and Lane A flagged the same discrepancy from the contract side.
   Guessing would print the headline share price wrong by a factor of a million. So the dApp
   **derives** it from `total_assets` and `total_supply` — whose scales *are* specified — with share
   decimals read from the contract, and treats the reported field as advisory. It now renders
   correctly whichever convention Lane B emits, and needs no change to the frozen schema. Confirmed
   against the live fork: `decimals()` = 18 over a 6-decimal asset, exactly as Lane A documented.

**A third rung on the fallback ladder: agent API → chain → fixtures.** Previously an unreachable
agent API dropped the whole vault page to fixtures. But Lane B's `/vault/{addr}/state` is itself only
reading the ERC-4626 contract, so when that service is down there is no reason to fall all the way to
invented numbers — total assets, share price and balances are one `eth_call` away and they are real.
Only what the contract cannot know (decision history, the mandate behind `mandate_hash`) still needs
a fixture. `chain` is a genuine third `SourceMode`, not a shade of the other two: folding it into
`fixture` would understate the truth, and folding it into `live` would hide that the agent is down.
The aggregate takes the worst source on the page, so a page with real balances and a fixture decision
feed still reads amber — correctly.

**Fixture timestamps are re-anchored at read time.** The golden fixtures are stamped 14:05Z, so at
any earlier hour the feed rendered "in 11 hours", which reads as a clock bug rather than sample data.
The whole feed now shifts by one constant so the intervals between cycles — which the reasoning
refers to ("the last rebalance was 41 minutes ago") — stay exactly as authored. Safe to use the wall
clock because it happens inside a React Query `queryFn`, which is client-only and cannot
desynchronise a server render.

**Smaller corrections worth recording.** The vault header said `LIVE` for "not paused" while the
header also carried a `LIVE`/`FIXTURES` data badge — two differently-scoped "LIVE"s on one screen is
ambiguity a judge resolves the wrong way, so the vault one is now `ACTIVE`. The genesis panel listed
`version` among the fields still needed, which is a schema field the harness sets and not something a
user can answer.

**Process.** Lane A's request #14 is partly about `f1ab780`, which is this lane's commit — `git add
-A` swept `contracts/` into it. Acknowledged in #17; staging here is explicit paths from now on.

---

## 2026-07-25 — Lane E: the dApp — three routes, and the decision feed as the product

**What changed.** `web/` MVP complete: `/` (thesis + vault list), `/create` (genesis chat → live
mandate draft → deploy), `/vault/[address]` (state, holdings, mandate viewer, deposit/withdraw, and
the decision feed). `pnpm build` clean; all three routes render with **nothing else running** —
no agent API, no anvil, no deployed contracts. Usage doc at `web/README.md`.

**The one architectural decision everything else follows from: reads degrade, writes fail.**

Every *read* falls back to the golden fixtures when Lane B is unreachable, errors, or returns
something that does not match the frozen schema — so this lane is never blocked (cross-lane request
#3 is a courtesy, not a dependency). But the fallback is **loud**: each response carries the mode it
came from and the header badge shows it on every page.

That second half matters more than the first. The Graph disqualifies mocked data on the demo path,
and the realistic way that goes wrong is not deliberate cheating — it is standing in front of a
judge with fixtures on screen and not noticing the API fell over. A silent fallback is a trap; a
loud one is a rail you can see from across the room. Falling back on *schema mismatch* is the same
reasoning applied to Lane B drifting from the frozen interface: an amber badge and a legible zod
error beat a white screen.

*Writes do not fall back.* `POST /genesis/finalize` fails honestly rather than handing back a vault
address that was never deployed and a tx hash that does not exist — someone would eventually show
that hash to a judge. On failure the mandate stays on screen and the UI offers a clearly-labelled
fixture *preview* of the vault surface instead, so the flow is still demonstrable end to end
without ever displaying a fabricated deployment.

**Why the decision feed is laid out as three columns.** `AllocationDecision.facts_used` holding real
`Fact.id`s is the load-bearing invariant of the whole frozen interface for this lane: it is what
makes data → reasoning → transaction *drawable* rather than merely adjacent. Rendering it as three
columns makes the causality spatial instead of something a viewer reconstructs from a log. Four
choices inside it are arguments, not decoration:

- `snapshot.errors[]` renders as **"could not see"**. A failing source degrades the snapshot rather
  than crashing the loop, so the agent routinely decides on incomplete information. Hiding that
  would be the easy call and the wrong one — an agent that reasons openly about the limits of its
  inputs is more trustworthy than one that appears omniscient, and the golden decision itself cites
  a missing volatility series as its reason to size down.
- `status: "rejected"` renders **in full**, with the retry count. It is the only visible evidence
  that Lane B's output validation is load-bearing, which is exactly why the schema says to keep
  those records. A feed showing only successes looks like a feed with nothing to validate.
- `facts_used` ids that do not resolve render as **unresolved** rather than being dropped — the
  schema says that is how a model inventing numbers gets caught, so dropping them defeats it.
- Steps and tx hashes **pair by index only when the counts match**. The schema declares no
  correspondence, so inventing one would be a guess presented as a fact.

**A number we deliberately do not show.** `VaultState` carries `asset_decimals` but no share
decimals, and OZ's ERC-4626 decimals offset means the two differ (the fixture has 6-decimal assets
against 18-decimal shares). "Shares outstanding" rendered with an assumed scale would be wrong by a
factor of 1e12, so the dashboard omits it; TVL and share price are well-defined without it, and the
depositor's own position is read from the chain where the scale is known. Same reasoning drove
`lib/format/units.ts` being the only place a uint256 becomes human-readable — it stays bigint until
after the scaling divide.

**Working before Lane A exists.** Deposits and withdrawals go through the *standard* ERC-4626/ERC-20
surface, which is a standard rather than Lane A's invention, and addresses come from
`deployments/base-fork.json` instead of constants. So the wallet flow was built and type-checked
before any contract was deployed, and nothing has to be rewritten when the real ABIs land. When no
vault answers at an address, the panel says so plainly rather than rendering zeroes that look like a
funded, empty vault.

**Explorer links are suppressed on a local RPC.** The anvil fork reports chain id 8453 exactly like
mainnet, so a BaseScan link built from the chain id opens a transaction that does not exist. A dead
explorer link opened in front of a judge reads as a fabricated transaction — worse than no link, so
the hash renders as copyable text marked `fork` instead.

**Fixtures are validated at build time, not at click time.** The three feed states (executed / held
/ rejected) are hand-authored on top of the golden pair, and they are now built once at module load
so `AgentAction.parse` runs during the prerender. Any drift fails `pnpm build` rather than throwing
in a click handler mid-demo. This also closes a real gap: Wave 0's `test_conformance.py` validates
the fixtures against the JSON Schema and the *pydantic* mirror, but nothing checked them against the
*zod* mirror — importing and parsing them here is the TypeScript half of that conformance check.

**Genesis is one page, not a wizard.** The narrative beat is *a conversation produces a mandate*, and
watching the mandate assemble itself beside the chat is the point; a multi-step form would turn the
same data collection back into filling in a form. The draft accumulates across turns rather than
being replaced, because `mandate_draft` is a partial — each turn contributes what it learned.
Empty fields are listed from the start rather than progressively disclosed, so the user sees the
shape of what they are about to hand an autonomous agent.

**Two gaps in the frozen interface, filed rather than patched** (requests #5 and #6): FastAPI needs
CORS since the browser calls it directly, and no route returns a `Mandate` for an existing vault.
The second is worked around client-side — the mandate is cached at finalize and otherwise the viewer
shows the fixture badged `SAMPLE MANDATE` with a note to verify against `mandate_hash`. Neither
blocks; both are one-line fixes on Lane B's side.

---

## 2026-07-25 — Lane E: supply-chain policy for the JavaScript tree (all deps ≥180 days old)

**What changed.** Every JavaScript dependency is now pinned to an exact version at least 180 days
old, install scripts are disabled, and the policy is machine-checkable:
`pnpm --filter @curator/web audit:deps` walks the whole resolved lockfile against the npm registry
and exits non-zero if anything is too new. Result: **138 resolved packages, all ≥180 days old**, and
`pnpm build` green. Root `package.json` (new, pnpm settings only) and root `.npmrc` (new) carry the
workspace-wide half; `web/package.json` carries the direct pins.

**Why.** npm is the repo's largest untrusted-input surface and compromised releases are typically
caught and yanked within days-to-weeks, so declining to install anything from the recent window
removes most of the exposure at almost no cost. Concretely, the first install pulled packages
published *that same day*.

**Why exact pins rather than carets.** A caret is a standing instruction to fetch whatever was
published last night — precisely the window an attacker occupies. Exact pins plus a committed
lockfile also make the 10:00 macOS handoff byte-identical.

**Why `ignore-scripts=true`.** The large majority of npm compromises execute in a `postinstall`
hook, so refusing to run dependency lifecycle scripts removes the delivery mechanism rather than
the payload. Nothing here needs one — the only packages that wanted to build natively
(`bufferutil`, `utf-8-validate`) are optional accelerators for `ws` with pure-JS fallbacks.

**What did *not* work, recorded so nobody retries it.** `resolution-mode=time-based` is set and
pnpm reports it as active, but it did **not** hold transitive dependencies back: a package published
the same day still resolved into the tree. It is left in place as a mild bias but it is not the
mechanism — `pnpm.overrides` is. Do not rely on `time-based` for this.

**The change that did most of the work: dropping `wagmi` for `@wagmi/core` + `viem`.** The `wagmi`
React package depends on `@wagmi/connectors`, which drags in ~347 packages we never import — the
entire `@solana/*` kit, Coinbase's CDP SDK, MetaMask SDK, WalletConnect, socket.io, lit, preact,
axios. They accounted for 77 of the 92 initial policy violations. They had also already broken the
build once: webpack eagerly resolves the connectors barrel and fails on `@x402/evm` / `@x402/svm`,
optional peers of the Coinbase SDK. `@wagmi/core` declares three dependencies, each pinned exactly
by its own author.

- *Alternative rejected — keep `wagmi`, alias the missing modules to `false` in webpack.* Silences
  the build error but leaves 347 unused packages in the lockfile. It treats the symptom.
- *Alternative rejected — keep `wagmi`, pin the ~60 offending transitives.* Enormous override block
  to protect code we never call.
- *Cost accepted:* we write the React bindings ourselves. That is ~40 lines in
  `web/src/lib/chain/account.ts` — a `useSyncExternalStore` over `watchAccount` — because
  `@wagmi/core`'s actions are plain async functions and React Query is already in the stack to drive
  them. The one subtlety is documented there: `getAccount()` returns a fresh object per call, so the
  snapshot is cached in module scope or `useSyncExternalStore` re-renders forever.

**Two peer-dependency pins worth knowing about.** `autoInstallPeers` resolved `@tanstack/query-core`
and `abitype` to *latest* to satisfy loose peer ranges (`>=5.0.0`, `1.x`), even though their parents
depend on exact versions. Both are pinned to what the parent actually asks for — query-core to
5.90.5 (`@tanstack/react-query@5.90.5`'s exact dep) and abitype to 1.1.0 (`viem@2.38.5`'s exact
dep) — so these overrides *reduce* drift rather than force anything.

**Framework versions.** Next 14.2.33 / React 18.3.1 rather than Next 15 / React 19: the wallet stack
has been stable against React 18 for over a year, React 19's peer changes are a known source of pnpm
strict-peer failures, and a wallet that will not connect at 03:00 costs more than the modernity is
worth. No `next/font/google` either — it fetches at build time, which would make a fresh clone on
the macOS handoff depend on network access.

**Residual risk, stated honestly.** 180 days is a heuristic, not a guarantee: a long-dormant
compromise or a package that was malicious from publication would pass. The lockfile is committed,
so what is installed is what was audited here.

---

## 2026-07-25 — Lane C: live data is flowing, and what the key revealed

`GRAPH_API_KEY` arrived. `verify-live` immediately drove out things no fixture could have.

**The schema question is settled, by introspection rather than inference.** Querying
`__schema` on each subgraph:

| Subgraph | Reality |
|---|---|
| Moonwell Base | Messari standardized (`markets`) — **18 markets, USDC ~15% APY on $14.5M** |
| Uniswap V3 Base | Messari standardized (`liquidityPools`) — the DEX fallback was not needed here after all |
| **Aave V3 Base** | **Not standardized.** Exposes `reserves` — the standardized query could never have read it |

**Searching for a standardized Aave on Base, and failing.** I queried The Graph's own network
subgraph for every active Base subgraph (381 of them) and tested each lending candidate against our
real query. None work: `morpho-blue-base` answers the right shape but indexes spam (top market by
TVL is **$447**, with symbols like `MINITIMEBOTALPHAXXX` and 0% rates); `aave-v3_base` and both
Compound V3 Base subgraphs expose `markets` *without* `inputToken`, so they are a third schema, not
an older Messari version; Seamless and ExtraFi have no `markets` at all. Every rejection is recorded
in `protocols.py` so the next person does not repeat the search.

**So Aave got its own source — and that is the extensibility claim being exercised, not described.**
`sources/aave.py` plus one line in the registration table was the entire change. `registry.py`,
`facts.py`, `queries.py`, the frozen schema, the MCP server and the agent were all untouched.
*Alternative rejected:* a second query shape inside `messari.py`. It would have been slightly less
code, but `Fact.source` is **provenance** — the string the dApp shows under "where did this number
come from" — and labelling data pulled from Aave's own subgraph as `messari` is simply false.

**Three unit traps in Aave's schema, each derived from live values and pinned by a test.** None are
documented anywhere obvious:
- `liquidityRate` is an **APR in RAY** (1e27), not a fraction.
- `price.priceInEth` **actually holds USD with 8 decimals** despite the name — USDC read `99990000`
  → $0.9999, cbBTC read `6675885000000` → $66,758.85.
- `utilizationRate` is already a ratio but comes back **negative** for some reserves (USDbC read
  `-3.4406`). Dropped rather than clamped: clamping −3.44 to 0 asserts "this market has no
  borrowing", which is a claim about the market, not a repair of the data.

**Hardening that only real data could have prompted.** The live Uniswap V3 Base subgraph returns
scam pairs with fabricated TVL — an actual reading was `WETH/SLUG: $130,563,280,368,069,680,230,825,984`
(1.3e29, roughly a billion times global GDP). Permissionless chain, permissionless pools. Anything
above `MAX_PLAUSIBLE_USD` (1e11, when total DeFi TVL is order 1e11) is now dropped and counted in a
note. Dropped, again, rather than clamped: this feeds an agent that allocates capital by comparing
TVL. Timeouts also went 15s→30s and 20s→45s, because uniswap-v3's indexers answer in ~20s and the
old ceiling turned a working source into a permanently failing one.

**The tests stopped being hermetic the moment a real key existed.** Three changed behaviour and
several others quietly started making live network calls — slow, rate-limited, and green or red
depending on whose machine they ran on. `tests/conftest.py` now strips credentials and disables
`.env` discovery for every test, so the suite asserts the same thing on a laptop with a full `.env`
and on a fresh macOS clone with none. Live behaviour stays where it belongs: in `verify-live`.

**What the demo now shows.** `compare_protocols("USDC")` against live gateway data:

```
moonwell   APY 12.74%  TVL $ 14,543,736  util 0.91   (source: messari)
aave-v3    APY  3.41%  TVL $174,873,960  util 0.84   (source: aave)
best_apy -> moonwell        deepest_tvl -> aave-v3        errors -> []
```

Two protocols, two independent sources, merged into one source-agnostic snapshot with per-fact
provenance — and the highest yield is *not* the deepest market, which is exactly the tradeoff
`SKILL.md` teaches an agent to reason about.

**Still outstanding:** the Token API rejects `GRAPH_API_KEY` with HTTP 401 — it needs its own JWT
from The Graph Market. Prices are therefore the one capability still unavailable; everything else is
live. Lending yield, TVL and utilization do not depend on it.

---

## 2026-07-25 — Lane C: three live findings that contradict the documented values

Probed the real endpoints rather than waiting for `GRAPH_API_KEY`. Two of the three would have
failed silently or misleadingly at demo time. (Supersedes the "unverified" paragraph in the entry
below.)

**1. The subgraph gateway answers an unauthenticated request with HTTP 200, not 401.**

```
POST https://gateway.thegraph.com/api/subgraphs/id/<id>
-> HTTP 200  {"errors":[{"message":"auth error: missing authorization header"}]}
```

Our transport classified any GraphQL `errors[]` as a *query* error — "our GraphQL is wrong". So a
missing or malformed key would have printed `Type 'Market' has no field...`-shaped guidance and sent
whoever hit it at 3am to debug the schema instead of putting a key in `.env`. `_looks_like_auth_failure`
now inspects the message and raises `GatewayAuthError`, with the live wording (`auth error`,
`malformed API key`) covered by tests. Confirmed end to end: `GRAPH_API_KEY=not-a-real-key
curator-data verify-live` now reports *"gateway rejected the request: auth error: malformed API key"*
against all three subgraphs.

**2. `token-api.thegraph.com` does not resolve. At all.**

That host is what The Graph's own Token API documentation names, and it was our default. It fails
DNS resolution; the docs now redirect to Pinax, a Graph core developer who operates the service. The
live host is **`https://api.pinax.network/v1`** (`GET /health` → `{"status":"OK"}`). Had this shipped,
every price fact would have been a `ConnectError` and the agent would have valued non-USDC holdings
at nothing — while the snapshot still looked structurally fine.

**3. The price endpoint path shape was wrong too.** Probing distinguishes 401 (route exists, needs
auth) from 404 (route does not exist):

| Path | Result |
|---|---|
| `/evm/prices?network=base&contract=<addr>` | **401 — exists** |
| `/evm/ohlc/prices?network=base&contract=<addr>` | **401 — exists** |
| `/prices/evm/<addr>?network_id=base` | 404 — does not exist |

The verified shapes now lead `PRICE_PATHS`. The 404 shapes are kept last rather than deleted: this
API has already moved host *and* layout once during its beta, so a stale entry costs one wasted
request while a missing one costs the whole source. The source remembers whichever answers first.

**What this validates, beyond the fixes.** All three subgraph IDs are routable and the gateway URL
construction is correct, so the only thing standing between us and live Graph data is the key
itself. **Still genuinely unverified:** whether each subgraph answers the *Messari standardized*
schema. Aave V3 and Moonwell are expected to; the Uniswap V3 entry may answer Uniswap's own `pools`
shape, in which case it degrades into `errors[]` and `verify-live` names it — a one-line config fix,
which is why the protocol table is data.

**Method worth repeating:** an invalid credential exercises the whole network path and the whole
error-classification path without needing a valid one. Both fixes came from running `verify-live`
with a deliberately bad key, which cost nothing and found a dead hostname.

---

## 2026-07-25 — Lane C: the data registry, two Graph sources, a standalone MCP server, x402

**What changed.** `/data` — a pluggable market-data registry (`curator-data`), Messari and Token API
adapters, a separately-installable MCP server (`curator-mcp`) with its own `SKILL.md`, a `verify-live`
CLI, and feature-flagged x402 pay-per-query. 109 tests, no network, no credentials.

**Why the registry came before the Graph adapters.** This lane has two goals that look opposed: win
three Graph tracks *now*, and make adding a non-Graph provider later a 30-minute job. They only
conflict if the adapters drive the design. So the order was registry → `MarketSnapshot` merge →
adapters, and the constraint is asserted rather than trusted:
`tests/test_source_agnostic.py` fails if any provider name appears in executable code above
`sources/`. Docstrings may name providers — that documentation is how the next person finds the
extension point — but behaviour may not.

**Why sources declare capabilities instead of being named by callers.** First cut had
`MARKET_SOURCES = ("messari",)` in the query layer. The source-agnosticism test caught it, and it was
a genuine flaw, not a style nit: adding a Chainlink price source would have needed a *second* edit
outside `sources/`, quietly making the one-line extension claim false. Sources now declare
`provides = ("price", ...)` and the registry resolves by capability. A new price source joins price
queries the moment it is registered. Mandate permissions intersect on top, so access control still
wins over capability. *Alternative rejected:* a capability registry separate from the source table —
more indirection for a property that belongs on the source itself.

**Why a partial-failure channel was added to the source contract.** The frozen port models a source
as all-or-nothing: return facts, or raise and land in `errors[]`. Real sources are not — `messari`
queries three protocols and any one can be down. Returning the other two silently would tell the
model it saw the whole market when it did not, which is the most dangerous failure mode available to
a system that holds a key. Sources may now call `self.note(...)`; the registry folds notes into
`errors[]` via an optional `drain_notes` hook. **This is additive, not a schema change** — `key` +
`fetch` still satisfies the frozen protocol, and a source ignoring the mechanism behaves exactly as
before. No request against `packages/schema` was needed.

**Why protocol and token tables are data, not code.** Messari publishes one standardized schema per
protocol *type*, so every lending market answers the identical GraphQL document — asserted in
`test_one_query_shape_serves_every_lending_protocol`. Adding a protocol is therefore one
`Protocol(...)` line with no adapter. That *is* the Track 3 composition argument, so it is printable
(`curator-data protocols`) rather than merely claimed. Token addresses get the same treatment, with
one rule: an unknown symbol produces a note naming the fix, never a guessed address. On a system that
trades with a real key, a wrong address is the most expensive possible bug.

**Why `FactBuilder` has `apy_from_percent` and `apy_from_fraction` rather than one `apy`.** Messari
reports `InterestRate.rate` as a percentage (`4.32`); the frozen schema requires `0.0432`. A 100×
error here would not crash anything — it would make the agent believe every market yields 400% and
rebalance into whichever it misread worst. Naming the constructors after the unit they *consume*
makes the conversion a decision at the call site instead of an assumption.

**Why the MCP server is a separate distribution.** Graph Track 1 asks for reusable tooling, not a
single end-user app, and a server that only runs inside our repo fails that on its face. `curator-mcp`
has its own `pyproject.toml`, `README.md`, `SKILL.md`, licence and entry point, and imports nothing
from `agent/`. The claim is tested rather than asserted: it installs into a clean Python 3.10 venv
*outside* this repo and answers `tools/list`. That also pins the 3.10 floor — which is why `/data`
carries its own ruff config at `py310` and avoids `datetime.UTC` and the `TimeoutError` alias, both
3.11+. Our harness talks to the registry directly, so it is visibly *a* consumer, not *the* consumer.

**Why x402 is a transport decorator rather than a data source.** The agent paying for its own data is
the best narrative beat we have and also hand-rolled EIP-712 signing against a spec we cannot
rehearse. Making it a decorator over `GatewayClient` means the fallback is the *design*, not an error
handler bolted on: there is no code path where enabling x402 loses data the API-key path would have
returned. 13 of its 20 tests are failure tests — no key, amount over ceiling, unsupported scheme or
network, rejected payment, malformed body, empty `accepts`, 5xx, DNS failure — each asserting the
caller still got its data. A client-side ceiling of 1 USDC refuses to sign an absurd demand. It needs
the flag **and** a key, because a flag alone would fall back on every query instead of failing
obviously. Came in under the 90-minute timebox.

**Deviation from the plan's sketch:** the master plan showed `/data/registry.py` importing as
`data.registry`. Shipped as `/data/curator_data/` instead — `data` is far too generic a top-level
import name for a shared venv, and the MCP server needs a real distribution boundary to depend on.
Lane B imports `curator_data`.

**Environment findings, recorded so nobody else loses time:**
- **`uv sync --extra data` prunes every package not in the named extras.** It silently uninstalled
  Lane B's `fastapi`/`web3` and Lane D's `eth-abi` from the shared venv. Always sync all lanes:
  `uv sync --extra dev --extra data --extra agent --extra venues`. Noted in `/data/README.md` too.
- Windows consoles are cp1252 and turn an em dash in an error message into a mojibake box, so every
  string that can reach a terminal is ASCII — asserted by a test on the `verify-live` report.

**Blocked on a credential, not on code.** `GRAPH_API_KEY` is absent from `.env` and cannot be
self-served. Every unit test runs offline against `httpx.MockTransport`, and `curator-data verify-live`
is the one command that proves the live demo path the moment the key lands — it checks credentials
first (otherwise every downstream failure is ambiguous), queries each enabled subgraph concurrently,
and exits non-zero if anything failed *or was skipped*, because "we did not check" is not proof.

**Unverified against live data (the honest list).** The subgraph IDs are from Graph Explorer but
their schema *family* could not be confirmed without a key. Aave V3 and Moonwell are expected to
answer the Messari standardized `markets` shape; the Uniswap V3 entry may answer Uniswap's own `pools`
schema instead, in which case it degrades into `errors[]` and `verify-live` names it. Fixing that is a
one-line config edit, which is exactly why the table is data. The Token API's exact path layout is
also unconfirmed — its docs now redirect to Pinax — so that source tries a short ordered list of known
path shapes and remembers the first that answers.

---

## 2026-07-25 — Lane D: a contract maker works, and an Aqua ship can fail silently

**What changed.** `venues/aqua/solidity/test/VaultRelayFork.t.sol` — 7 fork tests running a complete
Aqua `ExecutionPlan` through a vault-shaped relay against the real deployed Aqua. 25 Foundry tests
total.

**The gap this closed.** `AquaShipFork.t.sol` pranks a plain address, so `msg.sender` at Aqua is an
EOA. In production the maker is the **vault** — a contract with no key — and calls arrive relayed
through `execute()`. That is a materially different path, and it is the entire reason
`useAquaInsteadOfSignature = true` exists. Now proven rather than assumed: a contract maker can ship,
balances are credited to the vault (not to the agent that authorised the call), and dock works the
same way. The relay is a minimal stand-in built from Lane A's *published* `execute`/`executeBatch`
signature — it does not test their vault, which is theirs to test, and no `contracts/` source was
read.

**The finding, which arrived as a failing test I had written wrongly.** I asserted that shipping
before the approvals land would revert. **It does not.** `ship()` succeeds with zero allowance,
records full virtual balances, and returns a valid strategy hash.

That is correct Aqua behaviour once stated plainly: shipping moves nothing, so there is nothing to
approve *yet* — the allowance is consumed later, when a taker fills and Aqua `pull()`s from the
maker's wallet. But the consequence is worse than a revert. **A plan that omitted the approval steps
would look completely successful** — non-zero balances, valid hash, no error anywhere — and then
quietly never be filled. The position would earn nothing and nothing would say why.

So the approval steps in `AquaVenue.plan()` are not defensive ordering; they are the only thing that
makes the position real, and their absence is undetectable at execution time. That is now pinned by
two tests (`…SucceedsButLeavesThePositionUnfillable` and `…LeavesTheAllowancesAFillRequires`), and
corrected in `calldata.py` and the README — all three of which previously said "a missing approve
reverts the plan", which is true for Uniswap and false for Aqua.

Worth noting how this surfaced: the test was written to confirm something I believed, and it was the
*failure* that carried the information. A test that had passed would have left the wrong model in
place and the wrong claim in the README.

---

## 2026-07-25 — Lane D: allowlist is now read from Lane A's manifest, not hardcoded

**What changed.** `addresses.EXPECTED_ALLOWLIST` (a compiled-in constant) became
`addresses.allowlist()`, which reads `deployments/base-fork.json` →
`executeAllowlist.targets`. `FALLBACK_ALLOWLIST` remains for when no manifest exists.
`BASE_RPC_URL=https://mainnet.base.org` added to `.env`. 59 Python + 18 Foundry tests green.

**Why, beyond Lane A asking for it.** Their answer to request 1 said "read it from there, never
hardcode", and their build log explains what I could not have known from outside: the vault's
`allowedTargets()` is **mutable** — a `GUARDIAN_ROLE` can widen or narrow it after deploy. A constant
in this lane is therefore not merely duplicated, it is *guaranteed to go stale eventually*, and the
symptom would be an on-chain revert rather than the clear, seam-naming failure this lane tries hard
to produce. Reading it means a guardian narrowing the list narrows ours in the same breath.

Their published list turned out to be exactly the seven addresses I had, with the checksums I had
just fixed. That is a good outcome and also exactly why the reconciliation test exists rather than a
shrug: `test_our_fallback_agrees_with_what_lane_a_actually_deployed` fails if this lane could ever
emit a target the deployed vault would reject. Agreement today is not a reason to stop checking.

Cache is keyed on the file's mtime, so a redeploy is picked up without a restart. A missing or
malformed manifest falls back rather than raising — a venue adapter should not be the reason a fresh
clone cannot import.

**The credential answer that mattered more than expected.** With `BASE_RPC_URL` now set to the
public endpoint, I checked the thing the whole Aqua path depends on: **`https://mainnet.base.org`
supports `eth_call` state overrides.** It returns byte-identical program bytes to anvil. So the
maker path needs no archive node, no deployed builder and no funded key — on the public endpoint,
today. That closes the last "will this work on the demo machine?" question in the lane, and it is
why `AQUA_PROGRAM_BUILDER_ADDRESS` stays an escape hatch rather than a requirement.

---

## 2026-07-25 — Lane D: proving the Aqua integration against the real contract, and two wrong checksums

**What changed.** `venues/aqua/solidity/test/AquaShipFork.t.sol` — 5 tests that execute our `ship()`
and `dock()` against **Aqua at its real Base address** on a mainnet fork. Plus
`venues/tests/test_addresses.py`. 54 Python + 18 Foundry tests green.

**Why this test exists.** Everything else in the lane proves we *build* correct calldata. None of it
proved 1inch's live contract would *accept* it. Those are different claims, and the gap between them
would have been discovered at the mainnet demo. The fork test closes it: real address, real token
approvals via `deal()`, real `ship()`.

Three assertions carry real weight:

1. **The `strategyHash` Aqua returns equals the one we compute off-chain.** If it did not, every
   `dock()` would target a position that does not exist — and we would only find out when trying to
   close one.
2. **`ship()` moves zero tokens.** This is the Pattern 1 custody invariant, and until now we had only
   *asserted* it in prose. It is now checked against the contract itself: maker balances unchanged,
   Aqua custodying nothing. If this ever fails, Aqua is not the venue we think it is and the entire
   1inch rationale collapses — better to learn that from a test than from a judge.
3. **Virtual balances match the shipped amounts**, so the position is genuinely fillable rather than
   merely recorded.

**A real bug this surfaced: two invalid EIP-55 checksums.** solc refused to compile
`0x499943e74Fb0ce105688bEEe8ef2ABEc5d936d31` (Aqua) and the SwapVM equivalent. The master plan lists
both in lowercase; I hand-cased them and got them wrong. **Python never noticed** — every address
comparison in this lane lowercases first, so the allowlist, the encoder and all 37 tests passed
happily. But `web3.py`, a wallet, or Lane E doing strict validation would reject an address this
lane published as correct in its README. Now parametrised over every address constant so it cannot
recur.

The general lesson, which is the reason this is in the log rather than just the commit: *our own
tolerance hid the defect.* Case-insensitive comparison is right for matching and wrong for
publishing, and the tests that "passed" were passing on a weaker property than the one we needed.
Where a value crosses a boundary to someone else, validate it in its strict form.

**Fork URL note.** The public `https://mainnet.base.org` is entirely sufficient for these five tests
— a handful of calls, not the archive-heavy workload that made `BASE_RPC_URL` a blocking credential.
So this suite runs today even though that credential is still unset.

---

## 2026-07-25 — Lane D: Aqua maker path, and why the program builder needs no deployment

**What changed.** `venues/aqua/solidity/` (Foundry, 13 tests incl. a 256-run fuzz) and
`venues/aqua/{program,calldata,venue}.py` plus `venues/rpc.py`. Both venues complete; 37 Python
tests green, 7 against a live node/API. `venues/README.md` and `FEEDBACK.md` written.

**Why the SwapVM program is compiled in Solidity and not encoded in Python.** Programs are packed
bytecode — `opcode ‖ argLength ‖ args`, repeated. Encoding that in Python means maintaining a
second, unverified copy of 1inch's instruction format; any drift produces a program that encodes
cleanly, passes our own tests, and behaves wrongly with real money behind it. The builder imports
1inch's `ProgramBuilder`, `MakerTraitsLib`, `Opcode` and `FeeArgsBuilder` unmodified from their
published packages, and Python treats the result as opaque bytes. A Foundry test pins the exact
byte encoding, so if 1inch renumber an opcode we fail in CI rather than at a live `ship()`.

**The decision that removed a whole step from the critical path: no deployment.** The obvious design
is "deploy the builder, record the address, `eth_call` it" — which needs a funded key, a deploy
script, an address registry, and a redeploy whenever the contract changes. But the builder is
`pure`. So instead we inject its runtime bytecode at a throwaway address via an `eth_call` **state
override** and run it there. Nothing to deploy, nothing to fund, nothing to keep in sync.

Two consequences worth stating. First, because the builder needs no Base state, it runs against a
**bare anvil** — which is why this lane's live tests pass while `BASE_RPC_URL` (a blocking Wave 0
credential) is still unset. Second, not every endpoint supports overrides, so
`AQUA_PROGRAM_BUILDER_ADDRESS` still selects a deployed instance; the error message says exactly
that rather than failing obscurely.

*Alternative rejected:* committing a deploy script and address. More moving parts, and it puts a
funded key on the path to building a pure function.

**The artifact is committed (`venues/aqua/program_builder.json`, 3.3 KB).** `out/` is gitignored, so
without this the Python side would require a Foundry toolchain just to *use* the lane. Lane B and
the macOS teammate now consume `venues/aqua/` with no forge installed at all. `solidity/build.sh`
regenerates it — reusable, documented tooling rather than a one-off (Rule 6).

**Deviation from the master plan, deliberate.** §10 Lane D specifies composing `_dynamicBalancesXD`.
`DynamicBalances` (opcode `0x91`) is **not wired into `AquaOpcodes` at all** — under Aqua the
virtual balances come from the `ship()` amounts themselves, so the instruction would be dead weight
or a revert. The program follows 1inch's own `AquaStrategyBuilders.buildProgram`: fee → `XYCSwap` →
`Salt`, with the fee first because `Fee.sol` reverts if applied after swap amounts are computed.

**Two bugs found while wiring this, the second more interesting than the first.** The sentinel
override address contained a `U`, which is not a hex character, so the node rejected the call. But
the *error classifier* then reported that malformed address as "this endpoint does not support state
overrides" — because it matched on JSON-RPC code `-32602` alone, and both malformed-params and
no-override-support share that code. Matching on a generic error code silently reclassified a real
bug as a graceful-degradation path. Now the message must actually mention overrides. Worth
remembering wherever we degrade on a broad exception: a fallback that swallows genuine errors is
worse than no fallback.

**Correctness detail with a test named after it.** `MakerTraitsLib` requires `tokenA < tokenB`, and
on Base **WETH `0x4200…` sorts below USDC `0x8335…`** — the reverse of how "the quote asset comes
first" reads. The strategy sorts its own tokens, so the adapter re-pairs amounts to *that* order
rather than the caller's. Keeping the caller's order would pair 1,000 USDC with WETH: a position
wrong by twelve orders of magnitude that would still ship successfully. My first draft of the
Foundry test asserted the sort backwards and caught it.

**Salt is derived from vault state, not random.** A random salt means a retried tick opens a
*second* position rather than rebuilding the same one. Deterministic salting makes `plan()`
idempotent, which matters because the harness may retry after a transport failure without knowing
whether the first attempt landed.

**Aqua approvals are for the exact shipped amount**, not `type(uint256).max` as 1inch's own tests
use. A vault holds other people's money; an unbounded standing allowance is a worse default than
re-approving on the next ship.

**Dependency plumbing.** Solidity deps come from npm rather than forge submodules: it is how 1inch
ship these (their `remappings.txt` points at `node_modules/`), and it avoids writing to the
repo-root `.gitmodules` that Lane A's Foundry project would be touching concurrently. **`pnpm
install` here needs `--ignore-workspace`** — without it pnpm walks up, finds the root workspace, and
installs Lane E's web dependencies into this directory while ignoring the local `package.json`.
There is no `.npmrc` key for it; learned by doing it wrong once. Documented in `build.sh`, the
README and `.npmrc`.

---

## 2026-07-25 — Lane D: Uniswap taker path live, and three findings that contradict our fixtures

**What changed.** `/venues` scaffolded and the Uniswap adapter finished end to end: `config.py`,
`addresses.py`, `abi.py`, `errors.py`, `registry.py`, and `uniswap/{client,plan,venue}.py`.
18 tests green, 4 of them against the live gateway.

**Three things the live API does that our written assumptions did not.** All found in the first
hour, because the alternative is finding them at CP2 with the vertical slice on the line.

1. **`routingPreference: CLASSIC` is rejected** with HTTP 400 `"routingPreference" must be one of
   [BEST_PRICE, FASTEST]` — yet a *successful* response echoes `"routing": "CLASSIC"` back. The
   value you read out of a response is not a value you may send. Headed for `FEEDBACK.md`; there is
   a regression test pinning it so we notice if they fix it.
2. **The swap target is `0x6fF5693b…D299b43`, not the `0x2626664c…e481` UniversalRouter** in
   `packages/schema/fixtures/execution-plan.json`. Had we trusted the fixture, every swap would have
   reverted on an allowlist check. Filed to Lane A as cross-lane request 7.
3. **`swap.value` comes back hex-encoded (`"0x00"`)** while `ExecutionPlan.value` requires
   `^[0-9]+$`. A straight copy produces a plan that passes casual inspection and fails schema
   validation. Normalised in `plan.py::_to_int`, with a test.

**The design decision that matters: how a contract vault gets a Permit2 allowance.** The quote
response hands back a `permitData` block to sign as an EIP-712 `PermitSingle`. **The vault cannot
sign anything** — it is a contract, it holds no key, and the agent's key is external to it. Options
were (a) implement ERC-1271 so the vault validates a signature the agent produces, or (b) use
Permit2's other, signature-free entry point, `approve(token, spender, amount, expiration)`, which is
an ordinary call the vault can make through `execute()`. **Chose (b).** It needs nothing from Lane
A beyond the generic `execute()` that already exists, whereas (a) would have put a contract change
on Lane A's critical path for no functional gain. Confirmed viable by observing `POST /swap` return
200 with no signature supplied. Every plan is therefore three ordered steps: ERC-20 approve → Permit2
approve → router execute.

**Approvals are re-emitted on every plan** rather than checked against current allowance first. A
redundant approve costs gas and always succeeds; a missing one reverts the whole plan. Given the
vault executes plans rarely and atomically, that is the right side to err on. `include_approvals=False`
exists for a vault with standing allowances.

**Why no web3.py.** This lane needs ABI encoding, keccak, and eventually one `eth_call` — all of
which are a few lines over the `httpx` client already in the tree. `eth-abi` + `eth-utils` are a
fraction of the dependency weight, and the root `pyproject.toml` already documents a broken global
web3 breaking pytest collection. Added as a `venues` extra, following the per-lane extras pattern
Lane B established rather than inventing a second convention.

**Rejected: a standalone `venues/pyproject.toml` with its own workspace.** Written first (while the
root config was broken) and then deleted once Lane B fixed root. It worked, but it meant a second
`.venv` in the tree and a macOS teammate at 10:00 guessing which one to activate. One venv,
per-lane extras, `uv sync --all-extras`.

**Client/translator split.** `client.py` speaks HTTP and knows nothing about our schema; `plan.py`
speaks our schema and never touches the network. That is what lets the plan builder be tested
against recorded responses — the offline suite covers step ordering, unit conversion and allowlist
enforcement with no quota and no market dependency — and it confines a future Uniswap API change to
one file.

---

## 2026-07-25 — Lane B: bound to Lanes C and D for real, and stopped returning opaque 500s

**What changed.** The late-binding seams are wired to what Lanes C and D actually published, proven
by `agent/tests/test_integration_lanes.py`; domain failures now map to real HTTP status codes; live
mode has its own API test suite. 104 tests green.

**The refs, and why they differ from the master plan's sketch.** `AGENT_DATA_REGISTRY=curator_data:build_registry`
and `AGENT_VENUE_REGISTRY=venues:get_venue`. §8 sketched `data.registry`, but Lane C shipped
`curator_data` (correctly — `data` is far too generic an import name for a shared venv). **Neither
lane had to change anything and neither did this one**: that was the entire point of resolving
providers from a config string, and it is now a tested claim rather than a design intention.

**Lane D publishes a lookup *function*, not a mapping.** `get_venue(key)` rather than
`{"uniswap": venue}`. Both are reasonable ways to publish a registry and neither is worth a
cross-lane request, so `_lookup_venue` accepts three shapes — a mapping, an object with `.get(key)`,
and a bare callable. A lookup that *raises* for an unknown key (their `UnknownVenueError`) is treated
as "not found", so the harness reports a missing adapter instead of leaking another lane's exception
type into a decision cycle.

**Lane D's three-step plans validate the `executeBatch` choice.** Their Uniswap path emits ERC-20
approve → Permit2 approve → router execute, and re-emits approvals every time. Submitting those as
three separate transactions is exactly the half-applied-plan failure `executeBatch` was chosen to
make impossible: an approval landing without its swap leaves the vault holding a live allowance no
decision authored. One atomic batch, one hash for the feed.

**Integration tests skip rather than fail when a lane is absent.** This suite has to stay runnable
from a fresh clone with only `/agent` installed, and a neighbouring lane mid-edit is a normal state
during a five-instance build — which is the whole reason the harness binds late. A test that failed
in that situation would punish the design for working.

**Why `GET /health` now names the ref that failed.** It previously reported
`fixture (fallback: ModuleNotFoundError…)` — true, and useless, because it omitted *which* ref was
tried. Now: `fixture (tried curator_data:build_registry: ModuleNotFoundError…)`. "It fell back" is
not actionable at 3am; the ref plus the reason is a fix. Found by writing the test for it.

**Domain failures now map to status codes.** A vault this harness never deployed was surfacing to
the dApp as `500 Internal Server Error` — indistinguishable from a crash, for a condition as ordinary
as opening a bookmarked link. `MandateNotFound` → 404, `AmendmentRejected` → 422, and a live mode
missing `AGENT_PRIVATE_KEY` or `VAULT_FACTORY_ADDRESS` → 503 with the setting *named*, because a 500
during a demo sends someone to read tracebacks instead of `.env`. The mapping is deliberately narrow:
anything unrecognised stays a 500, since converting real bugs into tidy 4xx responses hides them.
**None of this touches `POST /tick`** — a cycle that held, was rejected or reverted is still a 200
carrying an `AgentAction` that says so.

**Why live mode gets its own API tests.** Fixture-mode coverage cannot catch a field that only exists
on the live path, and the two zod wire-format traps (no nulls, UTC-with-`Z`) are exactly the kind of
thing that would first appear in Lane E's browser. The live suite scripts the model backend and uses
the stub chain client, so it needs no GPU, no credential and no network — it runs on the build machine
and it will run on the macOS box at 10:00.

---

## 2026-07-25 — Lane B phases 3–6: the decision cycle, the journal, and the signing chain client

**What changed.** The loop is real. `agent/loop/` (engine, planning, cycle, journal), `agent/mandate/`
(store, amendment), `agent/chain/` (ABI loading, web3 client, stub), `agent/service/live.py` wiring
it behind the frozen routes, and the genesis prompt. 78 tests green.

**Why every path through the cycle returns a journaled `AgentAction` instead of raising.** This is a
deliberate contract with Lane E: `POST /tick` renders a feed entry no matter what happened, so the
dApp never shows "something went wrong" — the feed says what went wrong and the record persists.
Keeping the five statuses distinct is what makes that honest, and the split that matters most is
`rejected` vs `failed`. A rejection means validation or a mandate limit stopped it and **nothing
reached the chain**; a failure means the model, a data source or the chain broke. A dead Ollama is
`failed`, never `rejected` — reporting an unreachable server as a validation failure would make the
feed lie about the one thing this project is arguing for.

**Why a whole plan is one `executeBatch` rather than N calls to `execute`.** Lane A published both.
Submitting steps separately lets a plan land *half* applied — approval granted, swap reverted —
leaving the vault in a state no decision authored and no depositor was shown. `executeBatch` makes
the tick atomic and yields one transaction hash, which is also what the feed wants. The `VaultClient`
port warns that a partially-applied plan is an outcome the caller must record; making it impossible
is better than recording it accurately.

**Why the rebalance cooldown is checked *before* the model is called.** The alternative is to ask for
a decision and then refuse to act on it, which spends a model call to learn something already known
and produces a feed entry where the agent's stated intent contradicts what happened. Only `executed`
cycles start a cooldown — holding or being rejected did not move capital, so they must not block the
next tick. The snapshot is still taken and shown, so a cooldown hold still displays what was observed.

**Where each mandate limit is enforced, and why they are not all in one place.** Asset lists, weight
sums, position caps, the cash floor and action counts are checkable from the decision alone, so they
live in `mandate/constraints.py` and run inside validation. **Slippage cannot be** — the decision
expresses intent and only the venue knows the price impact of filling it — so it is checked on the
merged plan in `loop/planning.py`. Quote staleness likewise. Splitting them by *what information the
check needs* keeps the constraint module testable with no venue, no model and no event loop.

**Why plans are merged into one.** `AgentAction.plan` is a single `ExecutionPlan` but a mandate may
allow several intents per tick. Merging is the honest reading rather than a workaround: the vault
executes a flat ordered sequence of calls, so "the plan for this tick" genuinely is the concatenation.
Step order is preserved because approvals must precede the calls that need them, and the merged plan
reports the *worst* slippage and *earliest* expiry of its parts, since those are what actually bind.

**Agent-side mandate amendment, and the invariants free text cannot enforce.** §2 locks the mandate
as mutable *only by the agent*. An agent that can rewrite its constraints can rewrite them away, and
`update_rules` is prose that no code can check. So four structural invariants are enforced regardless
of what the model asks for: `base_asset` can never change (the ERC-4626 asset is fixed at deployment,
and every share-price calculation would silently change meaning), the base asset must stay in
`allowed_assets`, `version` is assigned by the harness and always increments, and the merged result
must satisfy the full schema or it is rejected whole. A refused amendment does not fail the tick —
the decision may still be sound under the existing mandate — but it is logged.

**Reading `contracts/out/` is integration, not a boundary crossing.** `docs/active-work.md` states
that directory is committed on purpose as Lane A's way of publishing ABIs. So the harness loads the
compiled artifact and never opens `contracts/src/`: the ABI is the contract, the Solidity is Lane A's
business. A minimal fallback ABI covers the case where the artifact is missing (fresh clone, mid
`forge build`) so the tests still run. Similarly, the base-asset address is read from
`deployments/base-fork.json` rather than hardcoded — a chain constant in the harness would drift.

**A fixture bug worth recording because it would have surfaced only this afternoon.** The golden
`execution-plan.json` carries `quote_expires_at: 2026-07-25T14:06:30Z`. The harness refuses to submit
a stale quote, so replaying that timestamp verbatim made fixture mode work all morning and start
rejecting *every* tick after 14:06 today — during the demo window. The fixture venue now re-stamps
quotes relative to now, the same fix already applied to the fixture decision feed. General lesson for
the other lanes: **golden fixtures contain absolute timestamps, and anything that compares them to
`now` needs them re-stamped, not replayed.**

**Share price is computed, not read from `convertToAssets`.** Derived from `totalAssets`,
`totalSupply` and both decimals so it matches the golden fixture's definition exactly — assets per
whole share in 1e18 fixed point. Two lanes disagreeing about what "share price" scales to is a bug a
depositor sees before we do.

**Genesis fails differently from the decision loop, on purpose.** A malformed genesis response
degrades to "show the text, skip the draft update": a human is present, can see what happened and can
restate themselves. A malformed *decision* has nobody in the loop, so rejection is the only safe
answer. Same harness, opposite posture, because the trust model differs on either side of genesis.
`finalize` is strict regardless — it validates the full `Mandate` before deploying, since the mandate
becomes immutable to humans the moment it does.

**Known gap, stated plainly:** there is no Ollama on this machine (`ollama` is not on PATH, nothing
listening on 11434), so **the live model path has never run against a real model**, and no anvil fork
was up, so `Web3VaultClient` has not executed against a real chain. Everything around both is tested
via the scripted backend and the stub client, and both degrade visibly rather than silently —
`GET /health` reports `degraded` whenever live mode falls back. Flagged in `agent/README.md` under
"known gaps" as the first job for whoever has a GPU and a fork.

---

## 2026-07-25 — Lane B phase 2: the model seam and the validation layer that guards the key

**What changed.** `agent/model/` — an OpenAI-compatible client shared by an Ollama and a vLLM
backend, a scripted backend for tests, the curator prompt, and the four-layer output validator with
reject-and-retry. `agent/mandate/constraints.py` holds the mandate checks. 40 new tests; 60 green.

**Why validation is four separately-named layers instead of one `try: parse`.** The layering exists
to make *retries actually work*. A model told "invalid output, try again" learns nothing and burns
the tick; a model told "cbETH is not permitted; the mandate allows only USDC, WETH" fixes it on the
next attempt. So each layer produces a message written to be fed straight back:

| Layer | Catches | Told to the model |
|---|---|---|
| 1 extract | fences, prose, `<think>`, trailing commas | "return only a JSON object" |
| 2 schema | wrong types, unknown fields, bad enums | the pydantic error, compacted to 6 lines |
| 3 mandate | forbidden asset, weights ≠ 1, too many actions | the breach **and the limit it broke** |
| 4 grounding | citing facts that were never in the snapshot | the invented ids **and the real ones** |

Layer 3 reports *every* breach at once rather than the first: one retry that fixes three problems
beats three retries.

**Why the correction is appended as a conversation turn rather than a rewritten prompt.** The retry
puts the model's own rejected output back as an `assistant` message and the failure as a `user`
message. Models correct a visible, concrete mistake far more reliably than they avoid an abstract one
described in a system prompt, and it leaves the original task text intact. The echoed output is
capped at 1200 characters so three failures cannot crowd the real prompt out of a small context
window.

**Why grounding is a validation layer and not a UI nicety.** `facts_used` must cite real `Fact.id`s
from the snapshot the model was given. Two things ride on it: the dApp joins facts → reasoning → tx
hash to show *why* the agent acted, and a model citing `f9` when the snapshot stopped at `f6` has
demonstrably stopped reading its inputs. That is the cheapest signal available that the reasoning is
confabulated — and a confabulated rebalance spends real money. Also rejected: any non-`hold` action
citing no facts at all. Holding while citing nothing stays legal, because "nothing could be read this
tick" is an honest reason to hold.

**The golden fixtures settled a constraint ambiguity that would otherwise have been a coin flip.**
The golden mandate sets `max_position_pct: 0.6` and `min_cash_pct: 0.2`; the golden decision
allocates USDC 0.70 / WETH 0.30 with `base_asset: "USDC"`. Reading `max_position_pct` as a cap on
*every* allocation makes the shared fixture violate the shared mandate. So it caps **risk positions**
— non-base assets — while the cash leg is governed from the other side by `min_cash_pct`. WETH 0.30 ≤
0.60 and USDC 0.70 ≥ 0.20, consistent. A test asserts the golden decision is legal under the golden
mandate, so if another lane ever reads these fields differently the disagreement surfaces here rather
than as a mystery rejection at demo time.

**Why coherence between `action` and `venue_intents` is enforced.** A `rebalance` carrying no intents
executes nothing while reporting that it acted; a `hold` carrying swap intents trades while claiming
to have stood still. Both are schema-valid and both make the decision feed lie to a depositor, which
is the one thing this product cannot afford — the feed *is* the product.

**Why the backend split is one hook and not two HTTP clients.** The only real difference between
Ollama and vLLM is how you request structured output: Ollama takes `response_format: {"type":
"json_object"}` (syntax only), vLLM accepts full JSON-Schema-guided decoding. That is a single
callable passed into the shared client, so each backend file is a dozen lines. Neither hint is
treated as a guarantee — `ports.ModelBackend` says so and it is true: guided decoding can produce a
perfectly well-formed decision that breaks the mandate, so layers 3 and 4 run identically on both.

**Why `scripted` is not in the backend registration table.** It is a real `ModelBackend` (the harness
cannot tell it from Ollama, so tests exercise the true code path), but it is constructed directly and
deliberately *not* selectable via `AGENT_MODEL_BACKEND`. Nothing should be able to put a canned model
in front of a live vault by setting an environment variable.

**`ModelUnavailable` is distinct from a validation failure**, and the cycle records it as `failed`
rather than `rejected`. Conflating "the server is down" with "the model is unreliable" would make the
decision feed misreport why a tick produced nothing.

**Rejected:** relying on `response_format` / guided decoding *instead* of validating — it constrains
syntax and at best shape, never mandate legality, and the agent holds a key. Also rejected: repairing
model JSON beyond trailing commas. Silently "fixing" a malformed decision is exactly the risk the
layer exists to prevent; only a repair that cannot change semantics is acceptable.

---

## 2026-07-25 — Lane B phase 1: frozen routes live on fixtures; late binding to Lanes C and D

**What changed.** `/agent` stood up: config, typed fixture access, the FastAPI app with all five
frozen routes from §8 plus `GET /health`, `GET /genesis/sources` and `GET /vault/{addr}/mandate`,
fixture-mode services behind a port, canonical mandate hashing, and 20 tests. Lane E is unblocked
(cross-lane request #3).

**Why route handlers depend on a service port rather than calling the loop.** The obvious shape is
"routes call the decision loop, and fixture mode is a branch inside them." Rejected: the branch then
lives in every handler and the fixture path drifts from the live path exactly where it matters. A
`VaultService` / `GenesisService` Protocol means `agent/api/deps.py` is the *only* module that knows
which mode we are in, and the endpoint Lane E integrates against at hour 2 is byte-identical to the
one running at the demo. There is no fixture-only endpoint to migrate off.

**Why other lanes are resolved from a `"module:attribute"` string instead of imported.** This is the
most consequential decision in the lane. Rule 7 forbids importing another lane's internals, and
neither Lane C nor Lane D existed when this was written. Options:

- *Import Lane C's registry directly once it lands* — violates Rule 7, and makes `import agent` fail
  whenever a neighbouring lane is mid-edit. With five instances pushing concurrently that is a
  guaranteed outage of the API Lane E develops against.
- *Copy a minimal interface and adapt later* — that is schema drift with extra steps.
- *Late binding from config* ← **chosen.** `AGENT_DATA_REGISTRY=data.registry:registry` is imported
  on first use, checked against the `DataSourceRegistry` Protocol, and **any** failure — missing
  module, bad attribute, wrong shape — degrades to the fixture provider with a warning instead of
  raising. Lane C and Lane D each cost this lane one environment variable and zero code changes, and
  `import agent` never transitively imports another lane, so the test suite runs with no other lane
  installed. Cost: a typo'd ref fails soft, which is why `GET /health` reports what each seam
  actually resolved to — a live run quietly serving fixture numbers is the failure mode that
  matters, and it is now visible in one curl.

**Why fixture mode serves a feed covering every `AgentAction` status.** The golden fixture is a
single `executed` action. Serving four copies of it would let Lane E ship a decision feed that has
never rendered `rejected` or `failed` — and those states would first appear during the live demo.
Fixture mode therefore synthesizes a hold, a validation rejection and an on-chain failure alongside
the success, with timestamps counting back from *now* so the feed never reads as stale. It also
attaches the `MarketSnapshot` to executed actions, which the golden fixture omits: Lane E's MVP
requires showing data consulted (with provenance) → reasoning → tx hash, and that view is impossible
if the snapshot never crosses the wire.

**Why `mandate_hash` is computed for real in fixture mode.** It would have been easier to return a
constant. But the hash is what a depositor uses to verify the mandate they were shown is the one the
vault was deployed against, so fixture and live must agree byte-for-byte. Canonical form is defined
once in `agent/mandate/hashing.py` — UTF-8 JSON, sorted keys, no whitespace, unset optionals omitted
— and both modes call it. `exclude_none` matters: an explicit `"update_rules": null` must not hash
differently from an absent one.

**Two wire-format traps found by testing rather than at the demo.** Both are legal JSON Schema and
both break zod in the browser while passing any Python-only test:

1. `z.string().datetime()` accepts **only** UTC with a `Z` suffix — it rejects `+02:00` and rejects
   naive timestamps. Pydantic serializes whatever it is handed, so a plain `datetime.now()` on the
   Lisbon demo machine (UTC+1) emits `...+01:00` and Lane E's parser rejects it. All timestamps now
   go through `agent/clock.py`, and a test asserts the `Z` shape on **every** datetime-looking leaf
   of every response, not just the fields a test remembers.
2. zod's `.optional()` accepts a missing key but **rejects an explicit `null`.** Pydantic's unset
   optionals serialize to null by default. Every route sets `response_model_exclude_none=True` and a
   test asserts no response contains a null anywhere. It caught `/health` immediately, which is the
   point — the guard is cheap and the failure it prevents is a demo-time 500 in someone else's lane.

**Why tests validate against `packages/schema/*.json` and not the pydantic models.** Validating a
pydantic-produced payload with pydantic proves only that the harness agrees with itself. The JSON
Schema is the declared source of truth and is what Lane E's zod mirror was written from, so the
tests load the schemas into a `referencing` Registry (they cross-reference by relative URI) and
validate there.

**Additive routes, and why they do not breach the freeze.** `GET /vault/{addr}/mandate` (Lane E's
request #5 — `VaultState` carries only `mandate_hash`, so the mandate viewer had no source),
`GET /genesis/sources` (the user must grant data sources at genesis; that list has to come from what
Lane C registered, not a copy hardcoded in the dApp), and `GET /health`. The freeze prevents
*changing* agreed shapes; adding a route breaks no consumer. All five frozen routes are untouched.

**Rejected:** `pydantic-settings` for config — one more dependency to read a dozen env vars that
`os.environ` plus the already-present `python-dotenv` handles; a dataclass keeps the defaults
readable in one screen.

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
