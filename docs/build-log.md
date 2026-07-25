# Build log

Append-only, **newest at the top**. Every non-trivial change gets an entry: what changed, **why**
(the important part), and what alternatives were rejected. Never rewrite another agent's entry.

This log is also part of the ETHGlobal audit trail — it evidences that decisions were made during
the hackathon window.

---

## 2026-07-25 — Lane A: rehearsing R0 found the landmine under R8

**What changed.** `script/Deploy.s.sol` no longer reads the mainnet deployer key on a fork, and
refuses to start a deploy the signer cannot pay for. 92 tests. Filed requests #44 and #45.

**Why rehearse a rung Wave 0 owns.** The [e2e plan](../plans/2026-07-25-e2e-local-deployment.md)
assigns Lane A nothing — the four narrative breaks belong to B, C and D. But R8, the plan's actual
deliverable, replays `Deploy.s.sol` from a cold anvil, and the plan's own rule is *"every integration
failure in this project so far has been a lower rung assumed rather than checked."* The deploy half of
R0 was assumed. So: a throwaway clone, a scratch anvil on port 8541, and the shared fork left alone.

It failed, in a way that would only have shown up during R8.

**The trap: the deploy worked in a bare shell and failed in the documented one.** `run()` read
`DEPLOYER_PRIVATE_KEY` — which `.env.example` defines as the funded *mainnet* wallet, "Fresh wallet,
funded ~$20 + gas on Base". That variable was unset when this script was written and is set now. It
has zero balance on a fresh fork **by definition**, because it is a mainnet wallet. So the deploy
succeeded from a clean environment and failed the instant `.env` was sourced — which every
`scripts/*.sh` does, and which any runbook tells a human to do. The variable that broke it was the one
whose own documentation says it is for something else.

Fork deploys now ignore it and use anvil #0, with `FORK_DEPLOYER_PRIVATE_KEY` as the override. The
mainnet key is reserved for real networks, which is all it was ever documented to be.

**The second defect was worse, and it is the one worth remembering.** `forge script` simulates the
entire script before broadcasting. So the unfunded deployer ran all the way through `_publish`,
**wrote `deployments/base-fork.json`**, and only then died in the broadcast phase. I checked what it
had published: `cast code` on the factory address returned `0x`. Nothing there.

That is a genuinely nasty failure. Four lanes read that file for addresses. They would have found a
factory with no bytecode and concluded "the contracts are broken" — debugging Lane A while the actual
fault was an unfunded key three steps earlier. The error message on offer was `Internal EVM error
during simulation`, which names neither the cause nor the account.

The fix is a balance precheck that runs before the guards' work is published — `DeployerCannotPayGas
(deployer, balance, minimum)`, thrown at the top of `run()`. Confirmed by observation that a failed
run now leaves the deployments file untouched. **The general lesson: in a `forge script`, anything with
a side effect outside the EVM — writing a file, in this case — happens during simulation, so it
happens even when the broadcast fails. Validate before you publish, not after.**

**One good discovery for R8.** A cold deploy signed by anvil #0 at nonce 0 is deterministic, so it
reproduces the demo vault at *the same address*, `0x0E2c…B5d1`. R8 is therefore far less disruptive
than the plan fears — `deployments/base-fork.json` need not change at all. Passed to Wave 0 as #44.

**A flaky test of my own making, fixed at the root.** The first version of the deployer-key tests
passed alone and failed in the full suite: `vm.setEnv` persists for the whole `forge test` process, so
one test setting `FORK_DEPLOYER_PRIVATE_KEY` changed what a later test observed. The tempting fix is
to order the tests or clear the variable. The better one was to notice the design smell — the
precedence *rule* was tangled up with environment *I/O*. Split out a pure `_chooseDeployerKey(isFork,
forkKeyOrZero, mainnetKeyOrZero)` and the policy became exhaustively testable with no environment at
all, order-independent by construction. Verified stable across three consecutive runs. A flaky test
is usually telling you something about the code, not about the test.

**One thing I broke, reported rather than buried.** `scripts/seed-fork.sh` sources `.env` with
`set -a` *before* reading `ANVIL_RPC_URL`, so it overwrites a value the caller already exported. My
`ANVIL_RPC_URL=…:8541` was silently discarded and it seeded the **shared** fork on 8540 — topping up
three anvil accounts to 100,000 USDC. The vault itself was untouched (its movement since is Lane B's
second rotation), and the script is designed to be idempotent and re-run, so the effect is benign. But
it is someone else's node state that I changed without meaning to, so it is written down in #45 along
with the fix. `scripts/` is Wave 0's active claim, so I filed rather than edited — the exec-bit change
earlier was a zero-byte fix to an ownerless file, which is a different situation.

---

## 2026-07-25 — Lane A phase 2: guarding the one deploy that cannot be undone

**What changed.** `script/Deploy.s.sol` now refuses to deploy to a real network with fork-grade
configuration, `priceMaxAge` is derived from the target network instead of defaulting to `0`, and
`script/verify.sh` verifies on Blockscout. 10 new tests, 86 total. Usage doc and handoff section
updated.

**Why a deploy script earned its own test suite.** Testing a script is usually not worth it. Here it
is, because of a property this lane chose deliberately in phase 1: **everything the guards check is
immutable after genesis.** The role graph is frozen — `DEFAULT_ADMIN_ROLE` is granted to nobody and
grant/revoke/renounce all revert — and there is no valuation setter for anyone. That is the right
design, and its exact cost is that a vault deployed wrong cannot be repaired. It can only be
abandoned. So the deploy is a one-shot, real-money, unfixable decision, run once, under time
pressure, at 3am. That is precisely the shape of thing to put a test around.

Two failure modes, each one forgotten environment variable away:

*An anvil account as agent.* The fork run **defaults** `DEPLOYER_PRIVATE_KEY` to anvil #0 and
`AGENT_ADDRESS` to anvil #1, which is what makes a fork deploy need no configuration at all — a
genuinely good property that turns into the trap. Anvil's private keys are published in Foundry's own
documentation. A mainnet vault whose `AGENT_ROLE` is anvil #1 is drainable by anyone who has ever
read those docs, and because the role graph is frozen it could never be revoked. Checked for
deployer, agent and guardian.

*Staleness checking left off.* `priceMaxAge = 0` is correct on a pinned fork and wrong everywhere
else — it makes `totalAssets()` trust a Chainlink answer of any age, so shares would price off a
frozen feed during exactly the volatility that makes feeds stall. Phase 2 flagged "remember to set
this" twice (§3.1, §5). Deriving it from `DEPLOY_NETWORK` beats remembering it, so the default is now
`0` for `base-fork` and `3600` for anything else.

**The classification fails safe, which is the part worth copying.** Only the exact string
`base-fork` gets fork defaults; every other value — including a typo like `base-forks` — is treated
as a real network and gets the strict settings plus the guards. A misspelling therefore causes a loud
revert rather than a quiet vault with its safety checks disabled.

**Reverting rather than warning** was the other deliberate call. A warning scrolls off the top of a
broadcast log. Given the decision is unfixable afterwards, a hard stop that costs thirty seconds to
override correctly is the cheaper error.

*Alternatives considered.* Documenting the requirement in the README and trusting the operator —
which is what phase 1 did, and phase 2's audit then flagged the same gap twice, so documentation
demonstrably was not enough. A `--force` escape hatch — rejected: it would be pasted reflexively the
first time the guard fired, which defeats the purpose; setting the three env vars properly is the
same amount of typing. Deriving `isFork` from `block.chainid` — rejected, because the fork
deliberately *reports* chain id 8453 to look like mainnet, so chain id cannot distinguish them.

Verified in the real script against the fork, not only in unit tests: an anvil deployer reverts,
non-anvil keys pass with `priceMaxAge` auto-set to 3600, and an explicit `PRICE_MAX_AGE=0` reverts.
The guard caught one of my own verification commands that had used anvil #1's key by mistake, which
is a fair demonstration of the failure mode being realistic rather than theoretical.

**Blockscout, not Etherscan** (cross-lane request #23 from Wave 0). There is no free Etherscan path
for Base: the V2 API rejects the chain outright and `api.basescan.org` V1 now refuses as deprecated.
Blockscout needs no API key and gives judges the same thing — readable verified source.
`script/verify.sh` reads addresses from `deployments/<network>.json` so it verifies what was actually
deployed rather than what someone remembered to paste, and it uses `--guess-constructor-args` for the
factory rather than asking anyone to hand-encode a struct array. **Stated plainly because it matters:
it has never been run against a live Blockscout instance,** since nothing is deployed to real Base
while `DEPLOYER_PRIVATE_KEY` is unfunded. Its error paths and address extraction are tested; expect to
debug the rest on first real use. Vault instances are EIP-1167 clones with no source of their own —
verifying `CuratedVault` is what makes every vault readable.

**The phase 1 design got its real validation this window, and not from a test.** Lane B landed the
first genuine agent write — fork tx `0x789066d4…8a4b`, one atomic `executeBatch` with three
`Executed` events: `USDC.approve` (a *token* as target), `Permit2.approve`, then
`UniversalRouter.execute`. Every answer this lane gave Lane D held up in production: token addresses
work as `execute` targets (request #8), the router address Lane D verified against the live API is on
the allowlist (request #7), and `executeBatch` did the job it was added for — a three-step plan that
cannot land half-applied. Recomputing the WETH leg independently from the live Chainlink answer gives
`749880448`, exactly what `holdings()` reports, so agent, contract and UI agree on the portfolio's
value. That last point is the argument for sharing one oracle with the contract, made concrete.

**One correction for anyone reading request #11:** it records the fork vault's share price as
"exactly `1e18`". On-chain it is `999952` — `convertToAssets(1e18)` returns a **6-decimal** number
because shares are 18-decimal over a 6-decimal asset. Lane E's UI renders `1.00` correctly, so
nothing is broken; noting it so the `1e18` figure is not copied into the submission text.

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

## 2026-07-25 — Lane E: unblock-by-default in practice, and one gap it exposed

Not a code change so much as an application of
[unblock-by-default](../plans/2026-07-25-unblock-by-default.md). Worth logging because the plan's
own thesis — that latency, not difficulty, is what has cost this build most — held up.

**Took the shared agent API live rather than filing a request about it.** §5 lists "restart the
agent API in live mode" as an *Anyone* item blocking R4 verification for everyone, and §2 makes it a
standing authorization. It had been in fixture mode for hours. Restarted; `:8000` now reports live
on all three seams. Also stopped the duplicate live instance I had been running on `:8001` — two
live agents is its own confusion — and updated both my docs, which still told people to run a second
agent and point the dApp at it. **The default config is now the live config**, which is what a
teammate following the README actually gets.

**Corrected a claim attributed to this lane.** §5's R8 row says "Lane E reports the vault redeploys
to the same address" and leans on it to call the replay less disruptive than feared. I never
reported that, and git has recorded exactly one deploy of `deployments/base-fork.json`, so there is
no evidence either way. `Clones.clone()` uses CREATE, so the address holds only if the deployer's
nonce and the deploy sequence are identical on the replayed fork; any extra deployer transaction
shifts it. What I *did* say and stand behind is narrower: the dApp reads the deployments file, so a
changed address is harmless here. Grepping the literal address across the tree bears that out —
`web/` is clean, while two Lane B test files and the root README carry it. Reported without opening
them.

**The gap this exposed: a transaction can be real and still not be demonstrable.** Lane B closed R5
with an agent-driven Aqua ship, and it is genuinely on-chain — `0x16eae7a2…`, status 1, block
49077798, 8 logs, agent → vault, confirmed by receipt. But the decision journal holds 12 actions and
**not one carries an `aqua` intent**; every intent is `uniswap:swap`. The ship was driven directly
rather than through a tick, so it produced no `AgentAction` and the feed cannot show it. e2e R7 asks
the feed to render R4's *and R5's* transactions: R4 is there, R5 is not.

That distinction is the whole reason this lane exists. The 1inch centrepiece being *true* and being
*visible to a judge* are different properties, and only the second one is what the decision feed
delivers. Filed as #51 with the fix (one ship through `POST /vault/{addr}/tick`) and — per the
plan's ladder — with what is already done meanwhile, so nobody is waiting on me: the renderer is
proven against a fixture, verified down to the DOM.

**R6 confirmed from the UI side.** The genesis-created vault renders with badge `LIVE`, no
missing-contract notice, and **no `SAMPLE MANDATE` warning** — `GET /vault/{addr}/mandate` returns
its own mandate. That is cross-lane request #6 paying off end to end: a vault this browser never
created still shows the mandate it was actually deployed with, rather than a fixture standing in.

---

## 2026-07-25 — Lane E: a mislabelled number, and surviving a cold restart

Two fixes found by reading other lanes' findings and by thinking about what the e2e plan's R8 rung
does to this app.

**`expected_slippage_bps` was being rendered as a claim about what happened.** Lane B's request #26
points out the field is populated from the Uniswap API's slippage *tolerance* — 250 bps by default,
where the realised fill was 0.035%. The badge said "250 bps slip", which reads as *this
low-drawdown vault just took a 2.5% hit*: wrong, and precisely the number a judge stops on. It now
reads "≤ 250 bps slippage", and the tooltip says it is the venue's tolerance rather than a
prediction. The schema field name is frozen and stays; the label does not have to inherit its
inaccuracy.

Better, the badge now **turns red when it exceeds the mandate's own `max_slippage_bps`**, naming the
limit. That is exactly why the harness refuses to execute (#26 again — the golden mandate's 50 bps
rejects every Uniswap plan), so the feed now explains its own rejections instead of leaving a reader
to infer the cause from two numbers on different screens.

**Plans now render on `rejected` and `failed` actions, not just successful ones.** A plan rejected on
slippage still *has* a plan, and the numbers that caused the rejection are in it. Showing them turns
"rejected" from an assertion into something checkable. Verified against the live stack: the failed
cycle's 3-step Uniswap plan and its slippage now appear beside the revert message.

**The app now diagnoses a restarted anvil instead of silently falling back.** The e2e plan's R8 rung
kills anvil and replays from cold, and the runbook lists "vault address 404s" as a failure mode —
fork state lives in memory, so a restart destroys every deployed vault while the address survives in
`deployments/base-fork.json`, in localStorage and in bookmarks. Previously the page just showed
fixtures with an amber badge: honest, but it does not say *why*, which is the part that costs twenty
minutes. A `getBytecode` check now distinguishes "no code at this address" from "cannot reach the
node" — only a successful empty read means the vault is gone — and renders **NO CONTRACT AT THIS
ADDRESS** with the cause and the fix.

Same reasoning applied to the docs: the two-minute wallet procedure no longer hardcodes the vault
address, because R8 will change it. Tx hashes stay — those are historical evidence, not
instructions.

**Verified against the fully live stack** (8 real cycles, badge green `LIVE`) by dumping the
rendered DOM rather than eyeballing a screenshot: 3 × "≤ 250 bps slippage" — two executed plans and
the failed one that previously showed no plan at all — zero instances of the old label, 8 × "Yield
comparison · USDC" correctly scoped, and all five `AgentAction` statuses rendering.

---

## 2026-07-25 — Lane E phase 2: the write path lands, and two things the feed left implicit

**What changed.** Phase 2 §3.2 and §3.5 for this lane: `venue_intents` (including SwapVM program
parameters) and a multi-protocol yield comparison now render in the decision feed, and the vault
write path is verified on-chain.

**The write path is no longer the project's last untested link.** Phase 2 §5 sequenced Lane E after
Lane B because a deposit mutates the vault Lane B asserts against; once their `executeBatch` landed,
approve → deposit → redeem all went through against the deployed vault. 100 USDC in →
`100.004782308691914570` shares worth `99.999999` USDC → redeemed back. Hashes in `docs/handoff.md`.

*Why a script and not the browser.* Signing needs a wallet extension and a headless environment has
none. Driving one over CDP would have meant hand-rolling a WebSocket client — Node 20 has no global
`WebSocket` — to test a layer that is `@wagmi/core` plus MetaMask rather than our code.
`web/scripts/verify-vault-write-path.mjs` instead issues the same three calls with the same ABI
fragments and argument shapes as the deposit panel. It is a reusable tool rather than a one-off
(Rule 6): parameterised on rpc/vault/amount/key, wired as `pnpm --filter @curator/web
verify:write-path`, and re-runnable by whoever takes the lane over. The honest boundary is stated in
all three docs: this proves the calldata and the share accounting, not the wallet handshake.

**It leaves the shared fork as it found it.** Deposit, verify, then redeem exactly the shares just
minted — net effect 1 wei of USDC and zero shares, with the wei being ERC-4626 rounding in the
vault's favour, which is the correct direction. Three other lanes are working against that fork and
Lane D still needs a clean vault for a taker fill; `--keep` opts out when a position is wanted.

**Why `venue_intents` needed rendering at all.** They were not displayed anywhere, which meant the
most distinctive part of the 1inch integration — the agent choosing a SwapVM program shape and maker
fee — was something a judge had to take on faith. A ship now reads "SwapVM · constant-product (xyc)
curve · 30 bps maker fee" beside the tokens committed. Phase 2 §3.2 asks for exactly this: they
score SwapVM usage higher, so make it legible rather than implied.

**Why the yield comparison is a table.** Individual fact cards render each observation faithfully but
scatter the comparison across six of them — a reader holds "moonwell 12.74%" in their head while
scrolling to "moonwell $14.5M TVL" and then to the Aave pair. The interesting fact is a
*relationship*: the highest headline yield is not the deepest market. A list cannot render a
relationship, so yields are pulled together, sorted, with TVL and utilization beside each and the
spread stated. That is the reasoning the mandate literally asks for — "prefer lending markets with
deep liquidity … over the highest headline APY" — and this is where a reader checks the agent
actually did it. Built only from facts already in the snapshot, so it invents nothing and adds no
data dependency, and it hides itself below two yields because one row is not a comparison.

**Intent amounts have no declared scale.** `AquaShipIntent.amounts` are base-unit strings with no
decimals attached. The scale comes from the vault's own holdings — it is sole custodian, so its
holdings are authoritative for any token an intent can mention. Where a token is not held, the raw
value renders labelled "base units" rather than divided by a guess. Same principle as the
`share_price` decision below.

**Then live data found a flaw the fixture could not, which is the argument for testing against it.**
The golden snapshot happens to carry one lending market per protocol. A real one does not: Aave's
Base deployment reports **USDC at 3.48% and WETH at 1.46%**, so the comparison ranked yields on
different assets against each other and named Aave's $174.8M *WETH* market "deeper" than a USDC
market it has nothing to do with. Comparing a stablecoin lending rate to an ETH one is meaningless;
stating it as a conclusion is worse than not showing it. Now grouped by market asset — only
protocols lending the same asset are compared, and a market with a single protocol is not a
comparison, so it drops out on its own.

**Verified against the fully live stack**, badge green `LIVE`, all three seams on real registries:
the comparison renders moonwell 4.18% on $15.1M at 88% utilization against aave-v3 3.48% on $173.2M
at 85%, with *"Deepest is aave-v3 — not the highest yield"* — Lane C's composability argument made
visible from two different Graph sources. Derived share price came out at exactly `1.00`, matching
`convertToAssets(1 share)` on chain, which independently confirms the derive-don't-trust decision
below was right. Ran the live agent on **port 8001** rather than restarting the fixture-mode instance
on 8000, so another lane's running service was left undisturbed.

**Genesis picked up Lane C's new `chainlink` source with no change here** — the source list is read
from `GET /genesis/sources` rather than hard-coded, so a newly registered provider simply appears.
That is the registry claim holding up in practice rather than in principle.

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

## 2026-07-25 — Lane C phase 2: Chainlink, real prices, and x402 signature-verified

Four items from the phase 2 brief. Three landed; the fourth is one funded wallet away.

**A Chainlink source — and why an on-chain source was the right fourth one.** Every previous source
speaks HTTP to somebody's API. This one reads a contract over JSON-RPC, which is the strongest
available evidence that the `DataSource` port abstracts *kinds of provider* rather than just
endpoints: a contract read and a GraphQL query merge into the same `MarketSnapshot` with neither
aware of the other. It also removes a dependency — price facts now survive a missing API key
entirely. Chosen over CoinGecko because **the vault already values holdings through
`ChainlinkPriceLib`**, so any other oracle would let the agent compute a rebalance the contract then
values differently, and because the golden mandate already restricts new assets to *"assets with a
Chainlink Base feed"*. The design agreed with itself before we got here.

*Rails, because a wrong price is the expensive kind of wrong.* Every feed address was confirmed
on-chain via its own `description()` rather than copied from a list, and the source **re-verifies at
runtime**. That check is not ceremony: a wrong feed address does not error, it returns a confident,
well-formed, completely wrong number. Demonstrated live — pointing WETH at the USDC/USD aggregator
would have priced WETH at **$1.00**, and the guard refused. Also: `observed_at` is the oracle's
`updatedAt`, not our clock (the frozen schema is explicit that staleness is the agent's problem, and
that only works if we report when the *oracle* spoke); non-positive answers are dropped
(`latestRoundData` returns a **signed** int); incomplete rounds dropped; >24h flagged but returned.

No web3.py — three argument-free selectors and one `eth_call` is a POST and some slicing on the
`httpx` client already present. Lane D reached the same conclusion independently.

**The Token API works, but request #22's advice would have shipped a 3.4-million-times error.** That
request did the hard work of finding the right route and I would have wasted twenty minutes without
it. But its recommendation — read the `price` field off `limit=1` — is unsafe, because **that field
flips with the direction of the swap**:

```
WETH -> USDC   price = 1858.0228     (USDC per WETH)
USDC -> WETH   price =    0.0005     (WETH per USDC)
```

Consecutive trades in the same pool. Nothing in the response says which you got, and this number is
what the agent values holdings with. Price is now computed from both legs **matched by contract
address**, so orientation is irrelevant, and taken as a **median over 10 swaps** so one fat-fingered
trade cannot set it. Two further live findings: the free plan caps `limit` at **10** (`limit=20`
403s), and that 403 is a *parameter* complaint rather than a rejected credential — the first cut
killed the whole source over it, which is the same misclassification as the gateway's
auth-error-as-HTTP-200. Quota 403s now degrade to a note.

**A flaw the second price source exposed.** `queries.prices()` was last-source-wins, so registering
Chainlink *alongside* the Token API silently discarded one of them — throwing away the only
cross-check the agent has. It now keeps every observation, reports the median as consensus, and
flags disagreement beyond 1%. Live: **WETH $1,857.18 via chainlink + token_api, 0.19% apart** — an
oracle and executed dex swaps agreeing by unrelated means. A wide gap there is a real signal (stale
oracle, manipulated pool, dislocated market), which is precisely what a curator should act on rather
than average away.

**The MCP server installs outside the workspace now.** Phase 2 §6 called this a hard fail on 25% of
Track 1's score, and it was: `uv pip install ./data/curator_mcp` died with *"curator-data was not
found in the package registry"*. Fixed without PyPI — relative `[tool.uv.sources]` for the two
siblings, verified in a clean Python 3.10 venv outside the repo. Two non-obvious details: the
sources must be `editable = true` or `uv sync` fails with *"conflicting URLs for package
curator-data"* against the root workspace, and the versions had to move to 0.2.0 because **uv caches
built wheels by name+version** and was serving a stale 0.1.0 wheel missing the new modules.
Publishing is prepared and verified up to the credential wall: all three distributions build, and
installing from `--find-links` with no repo present resolves the whole chain — which proves the
wheel metadata carries real dependency names rather than the local path hints.
[data/PUBLISHING.md](../data/PUBLISHING.md) has the commands and the bottom-up upload order.
`curator-schema` is Wave 0's to publish, not Lane C's.

**x402: the signature verifies. Only the money is missing.** The brief expected a failure on an
unfunded wallet. It failed somewhere more interesting first — **The Graph's gateway does not speak
the x402 v1 spec this was written against, and the mismatch was silent**: every request fell back to
the API key while appearing to have tried. Five differences, all found by probing:

| | v1 (what we had) | The Graph's gateway |
|---|---|---|
| terms location | JSON body | base64 `payment-required` **header** — the 402 body is *empty* |
| version | 1 | 2 |
| price field | `maxAmountRequired` | `amount` |
| network | `"base"` | `"eip155:8453"` (CAIP-2) |
| payment header | `X-PAYMENT` | `Payment-Signature` |

v2 also restructures the payload, echoing the accepted offer and resource back rather than restating
scheme/network. The error messages tracked progress precisely: *"Payment-Signature header is
required"* → *"Invalid or malformed payment header"* → **`invalid_exact_evm_insufficient_balance`**.
That last one is the end of the road without funds: the gateway parsed the payload, **validated the
EIP-712 signature against chain 8453**, matched scheme, asset and recipient, and refused only on
balance. Send a few dollars of USDC to `X402_PRIVATE_KEY` on real Base and it should settle at
$0.01/query. Both protocol versions remain supported — the spec is visibly in motion, and reading
terms from header-or-body while sending both header names costs a few bytes.

Throughout, the fallback did its job against the real gateway: **every query returned live data**.
That is the property the decorator design exists for, now demonstrated rather than argued.

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

## 2026-07-25 — Lane D: an ordinary market condition was escalating into a broken integration

**What changed.** `_api_error` in `venues/uniswap/client.py` now classifies `ResourceNotFound` and
three more phrasings as `NoRouteError`. Live tests quote a demo-realistic 1,000 USDC and skip cleanly
on `NoRouteError`. `FEEDBACK.md` §5 added. 103 Lane D tests; all 10 live tests green.

**Found by my own tests flaking, which is the useful part.** A live test failed with
`HTTP 404 (ResourceNotFound) : No quotes available`. The temptation was to call it a transient
network blip and move on. It was not: our classifier matched only `QUOTE_ERROR`, `NO_ROUTE` and
bodies containing `"no route"` — the documented forms — so `ResourceNotFound` fell through to the
generic `VenueAPIError` path. **For an autonomous agent that means "there is no route for this trade
right now", an entirely normal market condition, surfaces as a hard API failure mid-tick.** The
harness would record a failed action instead of a held one, and during a demo it reads as a broken
Uniswap integration.

**Then the more interesting bit: it is size-dependent.** Same pair, seconds apart —

| Amount | Result |
|---|---|
| 1 USDC | `504` (a Cloudflare **HTML** page, not JSON) or `404 No quotes available` |
| 100 USDC | `200`, routed |
| 1,000 USDC | `200`, routed |

Small trades are apparently not worth routing. Reasonable — but it presents as intermittent breakage
rather than as "below minimum". Our live tests quoted **1 USDC** precisely because it seemed the most
harmless amount to ask for repeatedly, and that choice manufactured flakes that looked like
integration bugs. They now quote what the demo quotes.

**Two smaller judgements.** Live tests `skip` rather than fail on `NoRouteError`: they exist to check
*our integration*, not Uniswap's liquidity, and a suite that goes red on market conditions trains
everyone to ignore red. And 5xx from that host returns HTML, so any body parsing needs a non-JSON
fallback — ours had one, but only by luck of an earlier defensive `except ValueError`.

**The general point.** A flaky test is evidence, not noise. This one was reporting a real defect in
error classification *and* a real property of the API, and the instinct to re-run it until green
would have shipped both to the demo.

---

## 2026-07-25 — Lane D: my own R5 assertion would have passed on a dead position

**What changed.** `venues/aqua/balances.py` gained `read_allowance`, `PositionHealth`, `read_health`
and `assert_position_fillable`. `assert_position_live` is kept as a deprecated alias that now
performs the *full* check. 24 tests on this module; 99 Lane D tests green.

**The defect, and it was mine.** An hour earlier I shipped `assert_position_live()` built on
`Aqua.safeBalances()` and told Lane B and Wave 0 (request 35) that it was "the R5 assertion".
Lane B came back with request 39: **`safeBalances()` being non-zero does not prove a position is
fillable**, so that assertion would pass on a dead position.

They were right, and the evidence was my own earlier finding. Request 17 — which I wrote — says a
ship with no approvals produces *"a position that looks healthy in every observable way (**non-zero
`safeBalances`**, valid hash, no error, a successful tx) and is silently never fillable"*. I
documented that failure mode accurately in the module docstring and then named the function after
the weaker check anyway. The docstring even said a missing approval "produces none of these" — the
correct statement sitting directly above an API that ignored it.

**Why this was worse than having no check.** An assertion that passes on a broken position does not
merely fail to help; it manufactures confidence in the 1inch centrepiece, and it does so in the one
place where the failure is otherwise invisible. Lane B would have gated R5 on it and gotten a green
rung over a position no taker could ever fill.

**The fix.** Fillability is gated on the **ERC-20 allowance from the vault to Aqua**, because that is
what Aqua pulls against on fill — zero in the broken case, at least the shipped amount in the good
one. `PositionHealth` now separates four states that look alike from outside: never shipped
(`None`), shipped-but-empty, **shipped-but-unapproved** (`dead` — perfect balances, nothing
fillable), and correct. Each raises a distinct message, because they are three different bugs with
three different fixes and a shared message sends people to the wrong one.

Partial allowance is called out separately rather than lumped in with either: a position approved for
half its shipped amount is not dead, it is *smaller than it appears*, and silently treating it as
healthy would overstate the vault's market-making by the difference.

**Why the old name was strengthened rather than removed.** `assert_position_live` had already been
published to two lanes. Deleting it would break them; leaving it weaker than its name implies is
precisely the failure being corrected. So it delegates to the full check — an existing caller gets
strictly more safety without touching their code.

**The lesson, which is about naming rather than Aqua.** The docstring described the failure mode
correctly while the function name asserted something stronger than the code checked. Names are
load-bearing: another lane imported this on the strength of `assert_position_live` and a one-line
summary, not by reading the implementation. When a check cannot support its name, the name is the
bug.

---

## 2026-07-25 — Lane D: the agent refused every trade over one unset environment variable

**What changed.** `UNISWAP_SLIPPAGE_BPS` wired from the environment through `VenueConfig` and
`get_venue()` into `UniswapVenue(default_slippage_bps=…)`, closing cross-lane requests 26 and 32 and
unblocking rung **R4** of the e2e plan. `price_impact_bps()` added and surfaced in `expected_effect`.
77 Python tests green.

**Why this mattered more than its size.** Both ends of the fix already existed —
`QuoteRequest.slippage_bps` and `UniswapVenue(default_slippage_bps=…)` — and nothing connected them,
so the adapter was always built with `None` and the Uniswap API applied its own **250 bps** default.
This lane reported that faithfully, the harness compared it against the golden mandate's **50 bps**
ceiling, and rejected. **The symptom is an agent that reasons correctly over live Graph data and then
declines to trade** — which reads as a model or prompt problem and costs hours in the wrong place. It
was one environment variable.

**Requesting the bound is better than tolerating a looser one.** The alternative fix — raise the
mandate's ceiling to 300 — was explicitly rejected in request 32 and rightly: a mandate that
advertises "conservative, low drawdown" while permitting 3% slippage is exactly the inconsistency a
judge notices, and the real fill was 5 bps. Requesting 50 bps means the constraint is baked into the
swap calldata's `minimumAmount`, so the agent tells Uniswap the bound it is actually under rather
than accepting a looser one and checking afterwards. Verified live: request `slippageTolerance: 0.5`
→ response `slippage: 0.5`, plan reports 50 bps, harness accepts.

**Tolerance and impact are different numbers and the distinction is now explicit.**
`expected_slippage_bps` stays the *bound* — it is what the harness checks, and a ceiling must be
compared against a worst case, not an expectation. Reporting the API's `priceImpact` there would
have made plans pass more easily while understating the risk the mandate exists to cap. Instead
`price_impact_bps()` is reported separately in `expected_effect` ("~5 bps price impact"), so the feed
shows the bound and the estimate side by side. A judge reading "50 bps tolerance, 5 bps impact"
learns more than either number alone.

**A bad value now fails loudly.** `UNISWAP_SLIPPAGE_BPS=abc` or `=10001` raises rather than falling
back to `None` — silently ignoring a typo'd bound would restore the exact failure this change exists
to remove, and the fallback is indistinguishable from success.

**Test hygiene note.** Two tests asserting the *absent* case failed once `.env` carried the variable,
because `VenueConfig.from_env()` loads it. Fixed with a `no_dotenv` fixture that neutralises
`load_env`, following the hermetic pattern Lane C established in `data/tests/conftest.py`. Tests
about a code path should not depend on the developer's local configuration — on a demo machine, where
the variable is always set, those assertions would otherwise be unprovable.

---

## 2026-07-25 — Lane D: our SwapVM programs were compiled against the wrong version of SwapVM

**What changed.** `@1inch/swap-vm` pinned from the default branch to **v1.0.1**;
`SwapVMProgramBuilder` rewritten to inherit `AquaOpcodes` and pass function pointers instead of enum
constants; artifact regenerated; opcode assertions updated in both suites. 25 Foundry tests pass, 1
skipped and documented. 59 Python tests green.

**The bug.** Phase 2 asked for a taker fill. Building it surfaced something much worse than a missing
feature: **the programs this lane produced could not have been executed correctly by the contract
deployed on Base.**

`package.json` depended on `github:1inch/swap-vm` with no ref, which resolves to the default branch.
That branch has moved past what is deployed, and the two encode instructions in fundamentally
different ways:

| | deployed (v1.0.x) | default branch |
|---|---|---|
| Opcode numbering | **positions in `AquaOpcodes._opcodes()`**, an ordered array of function pointers | a banked hex enum in a new `OpcodeList.sol` |
| `XYCSwap` | 17 | `0x50` |
| Taker entry point | `swap(Order, address tokenIn, address tokenOut, uint256, bytes)` | `swap(Order, uint256, bytes)` |
| Token pair | passed to `swap()` | baked into the order via `MakerTraitsLib.Args` |

So we were emitting `0x50` where the VM expects `17`. `0x50` is 80 — far past the end of a 35-entry
table.

**Why every test we had still passed.** `Aqua.ship()` stores the strategy as **opaque bytes** and
never interprets it. Our fork tests exercised Aqua — ship, dock, virtual balances, custody, contract
makers — all of which are genuinely correct and remain so. Nothing in that path ever asks SwapVM to
*run* the program. The first execution of a program is a **taker fill**, which is precisely the thing
we had not built. A whole class of bug sat behind the one untested door.

**How it was found.** The fill reverted at 299 gas — a missing-selector signature, not a logic
failure. Extracting `PUSH4` selectors from the deployed runtime bytecode showed `hash(Order)` and
`AQUA()` present (so the address is SwapVM) but neither `swap` overload from the default branch.
Regenerating candidate signatures against the deployed dispatcher matched the v1.0.x form exactly.

**The fix, and why it is structurally better than what it replaces.** The builder now inherits
`AquaOpcodes` and calls `p.build(XYCSwap._xycSwapXD)` with real function pointers;
`ProgramBuilder.findOpcode` resolves each to its index in 1inch's own table at compile time. **No
opcode number appears anywhere in our source.** If 1inch reorder their table, a recompile follows
them. That is what "use their official builder" should have meant from the start — the previous
version imported their `Opcode` enum, which looks equally official and silently encoded a different
scheme.

**What is still open, stated plainly.** The deployed table does not match v1.0.1 either. Probed
empirically: a program of `[17,0][20,32,salt]` reverts with
`DecayShouldBeCalledBeforeSwapAmountsComputation`, so the deployed VM reads index 20 as **Decay**,
where v1.0.1 puts Decay at 19 — one extra entry ahead of it. And no index we probed produced a real
constant-product quote; every one returned `amountOut == amountIn`, the VM's pass-through default,
meaning no pricing instruction ran at all.

`AquaTakerFillFork.t.sol` is therefore committed but `vm.skip`ped, with the evidence and the next
step in its header. **Deliberately not guessing the indices**: a wrong opcode yields a position that
ships successfully, looks healthy, and misprices on fill — strictly worse than no position. The next
step is to get the exact deployed source or ABI from 1inch, which is a five-minute question at the
venue and hours of probing otherwise.

**What this does and does not invalidate.** Unaffected and still verified against real contracts:
ship, dock, virtual balances, the zero-token-movement custody invariant, contract-maker support, and
the whole Uniswap path. Not verified: that the strategy **prices correctly when executed**. The
README now says exactly that rather than implying the integration is complete.

**The lesson worth carrying.** An unpinned dependency on a protocol's default branch is not
"latest" — it is "whatever they are working on", which is by definition not what is deployed. For
anything that must interoperate with a live contract, pin to the deployed release and verify the
pin against the chain, not against the docs. The selector check that found this (extract `PUSH4`s
from runtime bytecode, match against candidate signatures) took two minutes and should probably be
the first thing done against any third-party integration.

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

## 2026-07-25 — Lane B: unblock-by-default in practice — restarted a shared service, wrote two rungs

**What changed.** Took two of the unblock plan's standing authorizations rather than filing requests:
restarted the shared agent API, and wrote the R5/R6 e2e tests. Also corrected one of my own claims.
240 agent tests, 25 e2e tests.

### The shared API had been serving fixtures for hours

`GET :8000/health` reported `mode: fixture` on all three seams, against
`ollama:qwen2.5:14b-instruct` — **a model that is not even pulled.** Lane E's default
`NEXT_PUBLIC_API_URL` points at 8000, so every browser read was fixture data and R4 could not be
verified by anyone. §2 makes restarting a shared service a standing authorization precisely for this,
so it was restarted live and announced rather than requested. Lane E's separate instance on 8001 was
left alone.

This is the failure the plan calls out as "presents as success": a fixture-mode API answers every
request and validates every response, so nothing looks wrong until you check `/health`.

### A correction to my own report

I briefly reported `UNISWAP_SLIPPAGE_BPS` as unset and R4 therefore still blocked. **That was wrong,
and the cause was my own test harness** — it passed the variable as an empty string, which overrode
the value `.env` already had. Verified properly: a clean run produces a Uniswap plan at **50 bps**,
which the golden mandate's 50 bps ceiling accepts. #32 works and R4 is unblocked by default.

Recorded because the plan's §4 asks for exactly this — say so plainly and move. It also cost nothing
except the minute it took to re-check, which is the argument for re-checking.

`.env.example` had no entry for it, so one was added: unset, the API applies its own 250 bps default
and every plan is rejected on slippage, which reads as *"the agent will not trade"* rather than as a
missing variable.

### R5 and R6 have tests now, and R5 is gated on the right thing

Both rungs were proven on-chain earlier but had no test. Wave 0's `tests/e2e` tree was clean —
nothing in flight — and ladder rung 3 says write the test rather than wait, so they were written
following Wave 0's own conventions: public surfaces only, skip rather than fail when the stack is
down, a fresh vault per run so the shared demo vault is never touched.

**R6** asserts `vault.mandateHash() == the hash shown at genesis`, and **recomputes the hash
independently from the mandate** — an API echoing a value it had invented would satisfy the equality
and prove nothing. It also asserts the vault has bytecode, which is what distinguishes a real
deployment from the stub client's plausible-looking address.

**R5 is deliberately not gated on `safeBalances()`**, which is what the e2e plan asks for. Per #39:
request #17 established that a ship with no approvals yields non-zero `safeBalances`, a valid hash
and a successful transaction while being silently unfillable — so that check passes on precisely the
failure it was written to catch. The test instead asserts the **vault→Aqua allowance** moved from 0
to the shipped amounts and is bounded rather than infinite, plus the Pattern 1 property:
`totalAssets()` and both token balances unchanged, because shipping moves no tokens. It builds the
whole chain itself — fresh vault, deposit, Uniswap rotation, Aqua ship — so it proves the narrative
rather than asserting historical state.

**Verified the plan's own tooling check:** with the stack down the e2e suite reports **25 skipped, 0
failed**, so a fresh clone running everything stays green.

### Small thing worth not fixing yet

`Web3VaultClient` never closes its `AsyncWeb3` provider, so a long e2e run prints `Unclosed client
session` at exit. Harmless, but noise in a demo log. Filed as #46b rather than fixed mid-rung —
finishing the rung was worth more than the warning.

---

## 2026-07-25 — Lane B: e2e rungs R5 and R6 closed, and R5's stated proof does not prove it

**What changed.** The two narrative breaks the e2e plan assigns to this lane are closed, the
validation guards have been shown catching for the first time, and one item in the plan's own
definition of done turns out to be insufficient. 240 tests green.

### R6 — genesis actually deploys now

`createVault` had never been submitted. Live mode fell back to the stub client because
`AGENT_PRIVATE_KEY` was unset; both it and `VAULT_FACTORY_ADDRESS` are set now, so the real path ran:

```
POST /genesis/finalize -> createVault
vault 0xCa58ff3ebe6CD8FAFB1f5f35Ae59e47e3BE59F29   tx 0x9868681c…
hash shown at genesis == on-chain mandateHash      0xf6d84803…  ✓
```

That equality is R6's actual proof and the depositor's only verification handle. Genesis mints a
*fresh* vault every run, so the shared vault three lanes assert against is never touched.

Also switched `VaultCreated` parsing to `errors=DISCARD`. Creating a vault emits the clone's own
initialization events, which cannot decode against the *factory* ABI and are not supposed to — the
default printed a `MismatchedABI` warning per undecodable log, four alarming paragraphs mid-genesis,
for nothing.

### R5 — the Aqua ship, and why the plan's proof is wrong

Agent-driven `ship()` from the real vault, tx `0x16eae7a2…`, three steps in Lane D's order as one
atomic `executeBatch`:

```
allowance USDC->Aqua   0 -> 500000000            exactly the shipped amount
allowance WETH->Aqua   0 -> 250000000000000000   exactly the shipped amount
vault                  50.0% / 50.0%, totalAssets 2,498.51 — UNCHANGED
```

`totalAssets()` unchanged with a position open is the **Pattern 1 proof**: capital never left the
vault. That property is the entire reason Aqua is load-bearing rather than cosmetic, and it is now
demonstrated rather than argued.

**But the plan gates R5 on `Aqua.safeBalances()` being non-zero, and that check cannot distinguish a
live position from a dead one.** Request #17 says so in as many words: a ship with no approvals
produces *"non-zero `safeBalances`, valid hash, no error, a successful tx"* and is silently never
fillable. So the stated proof passes on precisely the failure #17 exists to warn about — the plan
cites the finding and then asks for a check the finding rules out.

**The allowance is what separates the two cases**: zero in the broken case, equal to the shipped
amount in the good one, and readable with a standard ERC-20 ABI without touching Lane D's source.
Filed as request #39 asking that R5 be gated on it. Keeping `safeBalances()` as a liveness check is
fine; treating it as evidence of fillability is not.

### The guards, finally seen catching

The plan notes the layers "have never been demonstrated catching the failures that motivated them."
All three now have been, on the live stack against a real vault, each producing a journaled
`AgentAction(status="rejected")` with no plan and no transaction:

| layer | fed a decision that | rejected with |
|---|---|---|
| 4 grounding | cited fact ids absent from its snapshot | the invented ids *and* the real ones |
| 5 direction | sold the underweight asset | *"selling WETH, already at 50.0% against a 60.0% target … swap the other way"* |
| 6 outcome | swapped 100% of holdings | cash floor, position ceiling and overshoot, both legs |

Worth recording: **layer 5's first attempt was caught by layer 4 instead.** The fact ids came from a
snapshot fetched separately rather than the tick's own, so grounding rejected them — correctly. It
cost a rerun and it is exactly the behaviour that layer is for, so it stays in the record rather than
being tidied into a clean narrative.

### A small vindication of following a published interface

Lane A's `contracts/out/**` was deleted in the working tree mid-rebuild while this work was running.
Lane B was unaffected, because `agent/chain/abi.py` reads `contracts/abis/*.json` — the curated flat
arrays Lane A asked consumers to prefer in request #2 — and only falls back to `out/**`. Had this lane
stayed on the raw artifacts it would have broken at exactly the wrong moment. Noted as #42.

---

## 2026-07-25 — Lane B: the autonomous loop traded twice, was wrong twice, and every layer passed it

**What changed.** Two new validation layers and a rewrite of how schema errors are reported. All
three came from watching the loop execute real transactions rather than from reasoning about it.
238 tests green.

### The loop works. That is how the gaps were found.

Two consecutive live ticks decided, planned and executed entirely autonomously, **zero validation
retries on either**. Both were bad trades.

| tx | diagnosis | direction | size | result |
|---|---|---|---|---|
| `0x129da1a0…` | right | **wrong** | — | 70/30 → 79/21, away from its own 50/50 target |
| `0x704f54a2…` | right | right | **`pct_of_holdings: 1.0`** | 79/21 → **0/100**, breaching two mandate limits at once |

Every existing layer passed both, and **each was right to**. In the first: well-formed JSON, valid
schema, permitted assets, weights summing to 1, the action label agreeing with the intents, every
cited fact real. The model even *said the right thing* — *"deviates from the target allocations by
more than the tolerance of 5 percentage points"* — and then sold the underweighted asset. The
decisions were internally consistent in every respect except the one that decides whether they make
money.

**The structural cause, which is the finding worth keeping: the mandate limits were being checked
against what the model *declared it wanted*, never against what its trade would actually *do*.**
`target_allocations` of 50/50 is legal on its face; a swap that lands the vault at 0/100 is not.
Declared intent and realised effect are different objects, and only the second one spends money.

- **Layer 5 — direction.** You may not sell an asset already below its target, nor buy one already
  above it.
- **Layer 6 — projected outcome.** The swaps are projected forward at current valuations and the
  *result* is validated: the cash floor and position ceiling must survive, and a book that was
  materially off target must end closer to it.

Both compare the decision against reality rather than against the mandate's text, so they hold
whatever a mandate says. Weights come from the vault's own `value_in_asset` — the Chainlink figure
`totalAssets()` is built from — so the checks agree with the contract instead of forming a second
opinion. Both stay silent where they cannot know honestly: no targets, an unpriced holding, an empty
vault, an Aqua ship (which posts liquidity rather than changing composition), or a swap sized in
token units, which cannot be projected without a price. Inventing a weight would be worse than
declining to judge.

**A judgement call worth recording.** The first draft of layer 6 rejected the **frozen golden
fixture**: it declares a 70/30 target on a book already at 70/30 and then trades, which the overshoot
rule read as moving away from target. Rather than override the shared contract, the rule was narrowed
to assets *already materially off target*, matching layer 5's threshold — "if you claim to be closing
a gap, close it". Where there is no gap the model is expressing a view rather than correcting a
drift, and the floor and ceiling still bound where it can land. Both real bad trades are still
caught. A check that fails the shared fixture needed a better reason than I had.

### The retry hint was the bug, not the model

The next tick was rejected after three attempts and 260 seconds. The model had omitted `token_out` on
a swap — one field. But `VenueIntent` is a union of three shapes, so pydantic reported failures for
**all three**: twelve errors, truncated to six, with the real cause buried under complaints that the
swap was not a valid `AquaShipIntent`.

```
SwapIntent.token_out: Field required; AquaShipIntent.venue: Input should be 'aqua';
AquaShipIntent.kind: ...; AquaShipIntent.tokens: ...  (and 6 more)
```

Three attempts, each given all the information needed to fail again. **Layer 2 exists to teach the
model what to fix; a message describing two shapes it never attempted is worse than no message.**
Errors are now grouped per union location and only the variant with the fewest errors is kept — the
one it plainly meant — with the variant name stripped from the path, since the model wrote
`venue_intents[0]`, not `venue_intents[0].SwapIntent`. Pointing at a path it never wrote is one more
thing to be confused by.

```
after: venue_intents.0.token_out: Field required
```

This is the third time this lane has found that **the quality of the correction determines whether
retries work at all**, and the first time the harness itself was the one being unclear.

### The meta-lesson across all of it

Every defect this lane found tonight came from the same place: **running the real thing, and reading
what it actually said.** Not one of them — the fabricated APY, the cross-unit arithmetic, the wrong
direction, the oversized swap, the union-error noise — was visible in a passing test suite, and
several were in code that had tests. The suite proves the harness agrees with itself. Only the live
loop shows whether it agrees with reality.

---

## 2026-07-25 — Lane B phase 2: the first on-chain write, and two more model confabulations

**What changed.** Phase 2 §2.1 closed — the agent signed and landed a real `executeBatch`. Lane D's
request #17 acknowledged and pinned. Two further prompt-shaped model failures found and fixed.

### §2.1 — the chain has now been run end to end

```
tx        0x789066d43ed0f54be903312dbc732a5c1b03ffb14dcdac0a5cd1e6f8ffa28a4b
block     49077778   status 1   gas 280,971   selector 0x34fcd5be (executeBatch)
effect    2,500.000000 USDC / 0 WETH  ->  1,750.000000 USDC / 0.403383 WETH
          totalAssets 2500.000000 -> 2499.880448
```

Lane D's Uniswap adapter built the 3-step plan from a live quote; this lane submitted it as one
atomic batch signed by the agent's own key. **11 logs, 4 of them ERC-20 `Transfer` events** — the
onchain token transfer 1inch asks to see, on a fork, which their rules permit in writing.

Quoted ~0.403526 WETH, delivered 0.403383: **0.035% off**. The 0.12 USDC drop in `totalAssets` is the
execution cost, priced by the vault through Chainlink — the accounting agreeing with reality rather
than a number we asserted.

Every link in this chain was independently green before this and the chain had never been run end to
end. That gap is the whole reason §2.1 was written as blocking, and it was right to be.

**Deliberately not done: submitting to Lane A's fork beyond this.** Three lanes assert against that
vault. One write, announced immediately in request #24 so Lane E and Lane D could sequence behind it.

### Request #17 — acknowledged, and the guard is mutation-tested

Lane D found that `Aqua.ship()` **succeeds with zero allowance**: it records full virtual balances and
returns a valid hash, because shipping moves no tokens and the allowance is only consumed later when a
taker fills. So an Aqua plan missing its approvals does not revert — it produces a position that looks
healthy in every observable way and is **silently never fillable**.

That makes it the one place in the system where an optimisation which is obviously correct everywhere
else — "skip the approve, the allowance is already sufficient" — fails quietly rather than loudly.
The harness never inspects, reorders, merges or skips venue steps, and `test_aqua_approvals.py` now
asserts it. **Verified the guard actually guards**: temporarily adding a `(target, calldata)` dedup to
`build_execution_plan` makes the test fail. A guard nobody has seen fail is a guess.

### Two more confabulations, both fixed in the prompt because neither was catchable downstream

**1. It invented a value for a real fact.** Shown `f6 | liquidity | uniswap-v3 USDC/WETH |
$12,400,000`, the model reported *"the highest headline APY of 10.43%"*. Grounding validation checks
that cited **ids** exist; it cannot check that quoted **numbers** are right.

**2. It did arithmetic across units and got it wrong — and that changed the decision.** Shown
`1,750.0000 USDC` and `0.4034 WETH`, it reported *"403.4 WETH, which is a 23.1% allocation (0.4034 /
1750 * 100)"*, concluded the book was balanced, and declined to rebalance a 70/30 book against a
50/50 target.

The second is the more instructive. Weighing a portfolio requires a price, and asking a 3B to apply
one to raw token balances invites exactly this. **The vault already computes it** — every holding is
valued through the same Chainlink feed `totalAssets()` uses, and it crosses the wire on
`Holding.value_in_asset`. So the weights are now *given*, in the units the mandate expresses targets
in, with an explicit instruction not to recompute them. The arithmetic error disappeared and the model
began quoting live yields correctly.

The general lesson, and it generalises past this project: **when a small model has to combine two
numbers to reach a decision, compute it for them.** Every derivation left to the model is a place it
can be confidently wrong in prose that passes every schema check.

The fact-table fix from the earlier entry and this one are both *rendering* changes, not validator
changes, because there is no downstream defence — nothing can tell that a number in free text was
invented. `test_prompt_rendering.py` pins the properties that stopped each.

**A test that earned its place immediately:** asserting the rendered prompt is pure ASCII found three
em dashes still in prompt-facing strings. Lane C's finding is that Windows consoles are cp1252 and
mangle them, and the prompt reaches a terminal through `agent.bench`.

### Two operational findings worth more than the code changes

**Ollama evicts an idle model after ~5 minutes**, and the next tick then pays a ~2 GB reload before
generating. A warm decision is ~33s; the first cold one blew through the 120s timeout and surfaced as
`ModelUnavailable` — which reads as *"the server is down"* when the server is merely slow. That is a
demo-shaped failure: it fires precisely when the stack has been idle while someone explains the
architecture. `model_timeout_s` now defaults to 300s so a cold load completes, and
**`OLLAMA_KEEP_ALIVE=30m` on the Ollama server** is documented in three places as a demo
prerequisite. Passing `keep_alive` in the request body does **not** work — verified, the
OpenAI-compatible endpoint silently ignores it and the TTL stays at 5 minutes.

**Uniswap plans report `expected_slippage_bps: 250`** — the API's default *tolerance*, not expected
impact. The harness compares that against `Mandate.max_slippage_bps`, so the golden mandate's 50 bps
**rejects every Uniswap plan**. Filed as request #26 rather than quietly loosened: when a ceiling and
an estimate are indistinguishable, refusing to trade is the correct default, and the right fix is a
demo mandate that permits it or a tighter tolerance requested from the API.

### Process notes

**Uncommitted doc edits get attributed to whoever commits next.** My `OLLAMA_KEEP_ALIVE` note sat in
the working tree and was swept into Lane E's commit by their `git add`. Nothing lost, but it is §2.5
in reverse — the fix is to commit doc edits promptly, not just to stage narrowly. Every Lane B commit
in phase 2 staged explicit paths.

**`uv run` was broken repo-wide** for a period by Lane C's in-flight `pyproject.toml` edits for the
PyPI publish (conflicting `curator-data` URLs, one editable and one not). Not this lane's to fix, and
they were actively working in it. Worked around locally by invoking `.venv/Scripts/python.exe -m
pytest` directly, which uses the already-installed environment and skips re-resolution — worth
knowing, because it un-blocks any lane during someone else's dependency edit.

---

## 2026-07-25 — Lane B: the model is real now — measured, and it confabulated on the first run

**What changed.** Ollama landed, `qwen2.5:3b-instruct-q4_K_M` pulled, and the loop ran end to end
against an actual model for the first time. Measured rather than estimated, one prompt bug found and
fixed, defaults retuned. 192 tests green.

### Measured on this machine (i5-8265U, no GPU, 16GB DDR4-2400)

| | before prompt fix | after |
|---|---|---|
| median validated decision | 40.6s | **32.7s** |
| spread | 39.6–47.6s | **32.1–33.1s** |
| validation retries | 0 of 3 runs | **0 of 3 runs** |
| tokens | 921 in / 277 out | 983 in / 270 out |

**Zero retries across every run.** That is the finding that decides the model choice. The worry
going in was the retry multiplier — a model that fumbles JSON twice turns a 40s tick into two
minutes — and it simply does not materialize with this model on this prompt. Reliability at
structured output matters more than raw capability at this scale, and a 3B that gets the schema right
first time beats a 14B that would take ten minutes a token-bound tick regardless of how well it
reasons. Reproduce with `uv run python -m agent.bench --model <tag> --runs 3`.

### The important finding: it cited a real fact and invented its value

First live run on an all-USDC vault produced this reasoning:

> *"…significantly lower than the highest headline APY of **10.43%** for uniswap-v3 USDC/WETH (f6)"*

**`f6` is `liquidity` — $12.4M of pool depth, not a yield, and 10.43% appears nowhere in the
snapshot.** The decision passed all four validation layers: the JSON was well-formed, the schema
matched, no mandate limit was breached, and `f6` is a genuine fact id from the snapshot it was given.

That is the sharpest possible illustration of what this layer can and cannot do. **Grounding
validation catches invented *ids*; it does not catch invented *numbers*.** Checking quoted values
against cited facts in free-form prose is a fuzzy problem and not something to hand-roll under time
pressure with a key on the line, so the defence had to be to make the row unmisreadable instead:

- Each fact now names **what it measures** in words (`pool depth`, `lending yield`) rather than a
  bare enum.
- Dollar values are suffixed `(dollars, not a rate)`; only yields render as `% per year`.
- The table is followed by an explicit line: *"Yields available this tick: f1, f2. No other row is a
  yield."*

Re-run after the change: the model read f1 and f2 correctly as the only yields and stopped inventing
an APY for f6. It costs 84 tokens of prefill (+10%) and, unexpectedly, made the whole thing **20%
faster with a third of the variance** — a clearer table appears to produce a more decisive answer
rather than a hedging one. Still 3/3 valid.

**Left honest in the README:** the reasoning is better but not right. The same run described 91%
utilization as "low", which is a qualitative judgement error rather than a fabricated figure. A 3B
model is a 3B model. The decision it produced was *safe* — legal under the mandate, correctly
holding — while the prose justifying it was partly wrong, and that gap is precisely why the mandate
constraints are enforced in code rather than trusted to the model's reasoning.

### The reject-and-retry loop, working against a real model

Same run also produced `action: "hold"` carrying a venue intent. The coherence check caught it, fed
back *"action is 'hold' but 1 venue intent(s) were supplied"*, and the retry returned a valid
decision. Cost: 103.9s instead of ~40s. So the retry multiplier is real (≈2.5×) — it just is not
being paid on the normal path.

### A configuration bug the measurement exposed

`GET /health` reported the configured model as `qwen2.5:14b-instruct` when `.env` contained **no**
`MODEL_NAME` at all. Cause: defaults were declared **twice** — once as `Settings` dataclass fields,
once as literals inside `_build()` — and only the field had been updated. Tests construct
`Settings(...)` directly and would read the field; the running server goes through `settings()` and
would read the literal. A stale literal therefore yields a green suite and a differently-configured
process, which is close to the worst shape a config bug can take. `_build()` now reads its fallbacks
off `Settings()`, and `test_config.py` asserts every defaulted field agrees between the two.

**Defaults retuned:** `MODEL_NAME` → `qwen2.5:3b-instruct-q4_K_M` in `agent/config.py` and
`.env.example`, with the measurement and the reasoning recorded next to it so the macOS teammate can
raise it on better hardware and re-measure rather than guess.

**Also corrected: Ollama tags are exact.** The health probe had matched on the base name before the
colon, so a server holding only the 3B reported ready to serve `qwen2.5:14b-instruct`. Settled
against the live server — `/api/show` answers 200 for the exact tag and 404 for `qwen2.5:3b`,
`qwen2.5` and `qwen2.5:14b-instruct` — and matching is now exact, with the single allowance that a
bare name means `:latest`. I had encoded the wrong assumption into a test, which is why it passed;
the fix was to go and ask the server instead of reasoning about it.

**Full live stack now green:** `GET /health` in live mode reports `status: ok` with
`data_registry: curator_data:build_registry`, `venue_registry: venues:get_venue`,
`model_reachable: true`. Every seam bound to the real thing.

---

## 2026-07-25 — Lane B: verified against the real fork, and what a real chain caught

**What changed.** `Web3VaultClient` read Lane A's deployed vault on the anvil fork for the first
time. It failed immediately, on a bug no stub could have surfaced. Fixed, tested, and the lane's
second known gap is now closed. 166 tests green.

**The bug: `bytes.hex()` has no `0x` prefix.** Reading `mandateHash()` returned raw bytes, and
`.hex()` gave `d00e91f7…` where the frozen schema demands `^0x[a-fA-F0-9]{64}$`. `HexBytes.hex()`
*has* included the prefix in some versions and not others, which is exactly why writing the
conversion by eye and moving on is a mistake. There is now one `to_hex_string` helper that accepts
bytes, bytearray, prefixed or unprefixed str, and always produces `0x`-prefixed lowercase — with a
parametrized test over every representation. The stub client never caught it because the stub built
its hex by string concatenation, so it was correct for the wrong reason.

**Confirmed correct against the live contract:** ABI decoding of `holdings()`, ERC-20 symbol
resolution (USDC/WETH), asset decimals, and share price. The deployed vault holds 2,500 USDC against
2,500e18 shares and reports `share_price` exactly `1000000000000000000` — and a test now pins the
formula against the golden fixture's own figure (50,000 USDC / 49,875 shares → `1002506265664160401`),
so if any lane ever reads "share price" at a different scale, it fails here rather than in front of a
depositor.

**⚠️ Operational finding worth more than the bug: the vault's `AGENT_ROLE` is anvil account #1
(`0x7099…79C8`), not account #0.** Reading state with the wrong key works perfectly; every
`executeBatch` then reverts on an AccessControl check. That is a nasty failure shape — everything
looks healthy until the first write. `AGENT_PRIVATE_KEY` must be
`0x59c6995e…78690d` on the current fork, and `GET /vault/{addr}/state` reports the vault's expected
`agent` so it can be compared against the address the harness logs at startup. Recorded in
`agent/README.md`.

**Two other fixes from having real infrastructure present.**

- **`/health` reported green with no model pulled.** `ollama serve` answers happily with an empty
  model list, so a server-is-up check passed right until a tick would die with `model not found`.
  Health now probes whether the *configured* model is served, only in live mode. Name matching
  tolerates tags in both directions (`qwen2.5:3b` ↔ `qwen2.5:3b-instruct-q4_K_M`) because a health
  signal that cries wolf gets ignored on the night it is right.
- **Action ids could be reused.** The cycle numbered actions from `journal.count()`, which counts
  *parseable* records — so a truncated line, the exact case the journal tolerates by design, shrinks
  the count and the next tick mints an id already in the feed. The dApp uses ids as list keys, so a
  duplicate silently renders one decision over another. Ids now come from a line count, which cannot
  go backwards and does not parse.

**A self-inflicted one, recorded because the lesson generalizes.** The cross-lane integration tests
called Lane C's registry, which reaches the live Graph gateway — ~12s of connection timeouts each
without a credential. The suite went from 5s to 43s and silently acquired an internet dependency,
contradicting the runs-anywhere property the whole lane is built for and which the macOS handoff
depends on. Now gated behind `AGENT_TEST_NETWORK=1`; binding and port conformance stay unconditional
because those are what catch a real integration break. **Rule of thumb for the other lanes: a test
that touches another lane's *I/O* is a different kind of test from one that touches its *interface*,
and only the second belongs in the default run.**

**Coverage added while waiting on a 1.9 GB model download** — the journal's quiet failure modes (a
process killed mid-write must cost one record, not a vault's whole history) and the mandate-hash
properties a depositor's verification actually rests on (key order, unicode, and null-versus-absent
must not move the hash; anything of substance must). The null case was a documented claim in
`hashing.py` with nothing enforcing it — a client that serializes nulls would otherwise invalidate
the on-chain commitment on a round trip.

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

## 2026-07-25 — Wave 0: the integration seam nobody owned (R0–R3)

**What changed.** `scripts/seed-fork.sh`, `scripts/preflight.sh`, and a new top-level `tests/e2e/`
with 10 tests, per [the e2e plan](../plans/2026-07-25-e2e-local-deployment.md).

**Why it did not already exist.** Rule 7 gave every lane a directory and forbade crossing
boundaries, which is exactly why five parallel agents converged instead of colliding. But the seam
*between* all five belongs to no lane, so nobody built it. Every lane was green and the whole was
never run. Claimed under Wave 0 because `scripts/` and root config are already its territory and no
lane directory is touched.

**Why a new top-level `tests/` (Rule 4).** Component-scoped tests live with their component and
should stay there. These are different: they assert the *narrative* across all five and belong to
none of them. Putting them in any lane's directory would make that lane's owner responsible for
other lanes' failures.

**Why pytest here rather than a shell script**, when `contracts/script/check-deployment.sh` set a
good precedent. The frozen schemas exist precisely so responses can be validated structurally; bash
can only check for HTTP 200. Python asserts against `VaultState` and `AgentAction` directly, reusing
`curator_schema`. The shell convention still holds for `seed-fork.sh` and `preflight.sh`, which
orchestrate rather than assert.

**Impersonation over `anvil_setStorageAt` for seeding.** Writing the balance slot is shorter and
wrong: USDC on Base is a proxy, a hardcoded slot breaks silently on upgrade, and the failure
presents as "the transfer didn't happen". Impersonating a holder survives that. Morpho Blue
`0xBBBB…FFCb` was chosen by inspection — ~179M USDC at the fork block — not by reputation.

**`preflight.sh` checks rather than starts.** The obvious artifact is a one-command `up.sh`, and it
would be a trap: anvil runs in WSL while Python and Node run on the Windows host, so a single script
must shell across that boundary — fragile exactly when you would depend on it. Checking is
cross-platform, read-only, and re-runnable. It found the running agent API still in fixture mode on
its first run, which is the failure it exists for.

**e2e creates its own vault per run.** The shared demo vault is asserted against by three lanes; an
integration test that quietly mutates it would be worse than no test. The one exception is the tick
in R3, which needs holdings worth reasoning about — so nothing there asserts on balances.

**Skips, never fails, when the stack is down**, following `test_integration_lanes.py`. Notably it
treats *fixture mode as absent*: a green e2e run against fixture data would prove nothing, so that
is a skip with an explicit message rather than a pass.

**Two bugs found by writing this**, both in my own code and both the kind only a real run catches:
`process_receipt(errors=0)` needs the `DISCARD` enum, and `preflight.sh` tripped `set -u` on an
unset `SEED_ACCOUNTS`. Also confirmed the ollama eviction window empirically — the model was gone
again within the hour, twice.

**Verified:** seed-fork idempotent (second run a no-op, demo vault untouched); preflight correctly
names fixture mode as blocking; R2 4/4 and R3 5/5 green against an isolated live API on port 8001
with its own `AGENT_STATE_DIR`, so Lane B's running process and journal were never touched.

---

## 2026-07-25 — Wave 0 (phase 2): submission README, golden mandate, line endings

**What changed.** Three items the lanes could not action themselves, plus an audit written up as
[plans/2026-07-25-phase-2-hardening-and-extensions.md](../plans/2026-07-25-phase-2-hardening-and-extensions.md).

**Golden mandate now grants `aave`** (request #19). `permitted_data_sources` is
`["messari", "aave", "token_api"]`. Lane C could not make this change because
`packages/schema/fixtures/` is frozen to lanes, and it is a one-word edit with real consequences:
the decision feed goes from a single protocol to a genuine comparison — moonwell 12.74% APY on
$14.5M against aave-v3 3.41% on $174.9M. "Highest yield is not the deepest market" is the reasoning
a curator should visibly do, and the golden mandate's objective already says exactly that. Checked
first that nothing pins the list: the only test reading it asserts `granted <= registry.available()`,
which holds because Lane C registers `aave`. 414 tests green after.

That this is a *config* change and not a code change is also the argument the Graph composability
track asks us to make, so it is worth stating plainly rather than leaving implicit.

**Root README rewritten as a submission document.** It was still the two-line placeholder. Uniswap's
rules require the README to *"clearly point to the relevant contracts and lines of code"*, so every
sponsor integration now links to specific files and line numbers, verified — all 29 link targets
resolve. Also documents the Aqua zero-allowance finding, because a silently-unfillable position is
the kind of thing a judge reading the code would otherwise have to discover themselves.

**Line endings.** `.env` had CRLF, which made `scripts/anvil-fork.sh` emit `$'\r': command not
found` when sourcing it. Harmless while values happened to parse, baffling the moment one carried a
trailing `\r`. Converted to LF and verified clean under WSL bash.

Worth recording that `git add --renormalize .` found **zero** tracked files to fix — `.gitattributes`
landed early enough in Wave 0 that the committed tree never accumulated CRLF. The problem was
confined to the gitignored `.env`, which renormalize cannot reach by definition. Checking was still
the right move; the answer just happened to be "already clean".

**Audit findings** (detail in the phase 2 plan). Ran the suites rather than trusting the status
table: 76 Foundry tests including 7 against real Base state, 414 Python tests, 65 commits all
pushed. The finding that matters is that **every piece of the write path is independently green and
the chain has never been run end to end** — Lane A proved an agent approval in a Foundry test, Lane
D proved Aqua ship from a test relay, Lane B verified reads only, Lane E never signed a deposit, and
the one live tick returned `held`. 1inch asks to see on-chain token transfers in the demo, so that
gate is currently unmet.

Two environment gotchas that would have read as code failures under pressure: a stale `next dev`
holds `.next/trace` and makes `next build` die with `EPERM`, and `BASE_RPC_URL` is currently the
public `https://mainnet.base.org` rather than an archive endpoint — it works today and Lane D
verified state overrides against it, but it is rate-limited under five lanes' load.

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
