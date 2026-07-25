# Security — `contracts/`

**Every claim here ends with the test that proves it.** Where something is genuinely unmitigated it
says so; a limitation a judge finds for themselves is worth less than one we wrote down.

Scope: `CuratedVault` and `VaultFactory`. Reproduce everything with:

```bash
cd contracts && forge test                      # 142 tests, no network
FOUNDRY_PROFILE=deep forge test --match-path "test/invariant/*"
```

**Deep run, measured for this document:** all **twelve** invariants green at 512 runs × 128 depth —
**65,536 calls each, 786,432 in total, zero failures**, in 279s on a CPU-only i5-8265U. The default
profile runs the same properties at 2,048 calls each so the normal suite stays under twelve seconds.

The campaign pauses and unpauses the vault at moments of its own choosing and keeps attempting
purchases throughout, so §12's rule is exercised across interleavings rather than in one scripted
sequence. That the paused state is actually *reached* — the failure a ghost counter cannot see in
itself — is pinned deterministically by `test_windDownRefusesPurchasesAndPermitsSalesUnderTheHandler`.

---

## The threat model in one paragraph

The vault is an ERC-4626 vault whose curator is an autonomous agent holding a private key. **The
agent is fully trusted with the assets by design** — that is the locked decision in
[initiate_plan.md](../plans/initiate_plan.md) §2, and it means "the agent could make a bad trade" is
not a vulnerability here, it is the product. What *is* in scope: anyone other than the agent moving
value, the agent reaching contracts it was never meant to reach, and any path that lets one depositor
take value from another.

Two consequences worth stating plainly, because both look alarming out of context:

- **There is no human override and no way for anyone to seize funds.** Nobody holds
  `DEFAULT_ADMIN_ROLE` and `grantRole`/`revokeRole`/`renounceRole` all revert, so the role graph is
  frozen at genesis. A compromised agent key still cannot be revoked — the vault would have to be
  wound down and exited. Accepted for a hackathon build; a production version needs the parked
  protocol-level controls.

  Since Wave 3 the guardian can `pause()`, and that is **narrower than it sounds and narrower than it
  was**: it stops the agent buying, never anyone withdrawing. §12 is the whole boundary, and the
  short version is that a guardian who flipped every target off had already halted trading before
  this existed. What is genuinely new is `redeemInKind`, an exit that needs no oracle, no venue and
  no liquidity — §10.
- **The allowlist bounds *which contracts* the agent may call, not what it may do there.** Within an
  allowlisted target the agent has full latitude. It is a blast-radius limiter, not a mandate
  enforcer — the mandate is soft and lives off-chain.
---

## 1 · Donation / first-depositor inflation — **mitigated, and the attack is executed**

**The attack.** Be the first depositor for 1 wei, donate a large balance directly to the vault to
inflate the price per share, and the next depositor's shares round to zero. The attacker then redeems
their single share and takes the victim's deposit.

**The defence.** `_decimalsOffset() = 12`, OpenZeppelin's virtual-shares mechanism. Shares are
18-decimal over a 6-decimal asset, and the offset makes a donation 10^12 times less effective.

**Why this section exists at all:** "we set the offset" is an assertion. The offset is a one-line
override and nothing about reading it tells you the attack fails. So the attack is run:

| Test | What it proves |
|---|---|
| `test_inflationAttackIsUnprofitableAndTheVictimIsWholeAgain` | Attacker seeds 1 wei, donates 10,000 USDC, victim deposits 1,000 USDC. **Both actually redeem.** Victim recovers their deposit (≥ `1_000e6 - 2`); attacker recovers ~5,000 of the ~10,000 they spent. |
| `test_donatingToALiveVaultIsAGiftNotALever` | A donation into a vault that already has holders is a gift to them — the donor cannot extract it back plus a profit. |
| `invariant_vaultIsSolvent` | Across 2,048 random calls including donations, the sum of what every holder could redeem never exceeds what the vault holds. |
| `invariant_entryAndExitNeverExtractValue` | No deposit or withdrawal ever lowers the price per share. |

**The stronger claim is the second one in that first test.** An attack that merely fails is one
somebody still tries; an attack that costs the attacker ~5,000 USDC is one nobody tries. The loss is
structural rather than incidental: the donation is shared pro-rata with every other holder, and a
1 wei seed buys almost none of the pool.

---

## 2 · Unauthorized value movement — **mitigated**

Only `AGENT_ROLE` may call `execute`, `executeBatch` or `approveVenue`.

The case worth calling out is the **guardian**, because it is the one address with a genuine power
over the vault: it can add and remove allowlist targets. If any path let it also spend, widening the
allowlist would become a route to the money rather than a safety control.

| Test | What it proves |
|---|---|
| `invariant_onlyTheAgentCanMoveValue` | Fuzzes caller × calldata over 2,048 calls; **including the guardian explicitly**. A counter increments if any non-agent call ever succeeds; the invariant asserts it stays zero. |
| `test_guardianMayNotExecute` · `test_guardianGainsNoSpendingPowerByWidening` | The guardian may add a target it controls and still cannot call `execute` against it. Not a wei moves. |
| `test_onlyAgentMayExecute` · `test_onlyAgentMayApprove` | The direct cases. |

---

## 3 · Allowlist bypass — **mitigated**

`execute` reverts with `TargetNotAllowed` for any target not on the vault's list. The subtle case is
**batch ordering**: a legitimate first step must not launder an illegitimate second one.

| Test | What it proves |
|---|---|
| `invariant_agentCannotReachANonAllowlistedTarget` | Fuzzed target × arbitrary calldata, tried both as a single `execute` **and** as the second step of an `executeBatch` whose first step is a valid approval. |
| `test_targetMustBeAllowlisted` · `test_batchIsAtomic` | The direct case, and that a reverting step rolls the whole batch back. |

Note the allowlist deliberately includes **token addresses** (USDC, WETH), because an
`ExecutionPlan`'s first step is typically `USDC.approve(Permit2, …)`. That is a real widening of what
the agent can reach and it is intentional — see the threat model above.

---

## 4 · Role-graph tampering and re-initialization — **mitigated**

| Test | What it proves |
|---|---|
| `invariant_roleGraphIsFrozen` | Over 2,048 calls, no grant, revoke or renounce ever succeeds; the agent and guardian are still the genesis addresses; nobody holds `DEFAULT_ADMIN_ROLE`. |
| `test_agentCannotRenounceAndBrickTheVault` | The one path AccessControl leaves open by default. The agent renouncing would strand the vault with no curator, so it is closed explicitly. |
| `test_implementationIsLocked` · `test_initializeCannotBeCalledTwice` | The clone cannot be re-initialized, and the shared implementation cannot be initialized at all. |
| `invariant_valuationSetIsImmutable` | The price-feed set, base asset and mandate hash never change. There is no setter for valuation, for anyone — a mutable feed is the one control that would let its holder reprice every share. |

---

## 5 · Stale or manipulated price feeds — **mitigated on real networks, off on the fork**

`totalAssets()` values non-base holdings through Chainlink. `ChainlinkPriceLib.readPrice` **reverts**
on a stale, zero, negative or incomplete answer rather than returning a wrong number. Reverting
blocks deposits and withdrawals, which is unpleasant and is the correct trade: valuing a held token
at zero would silently misprice shares and let a withdrawal drain value from everyone still in.

**Read this before concluding the deployment is unsafe:** `priceMaxAge` is **0 on the fork, which
disables the staleness check entirely.** That is not an oversight and not what ships to a real
network. A pinned anvil fork freezes the feed's `updatedAt` while `block.timestamp` keeps advancing,
so any real bound starts failing minutes into a dev session and takes the whole vault down with it.
`Deploy.s.sol` derives the value from `DEPLOY_NETWORK` — 0 for `base-fork`, 3600 everywhere else —
and **refuses to deploy to a non-fork network with it disabled** (`StalenessCheckDisabledOnRealNetwork`).

| Test | What it proves |
|---|---|
| `test_rejectsAStaleAnswer` · `test_rejectsAZeroAnswer` · `test_rejectsANegativeAnswer` · `test_rejectsAnIncompleteRound` | Each bad-answer mode reverts. |
| `test_staleFeedBlocksAccountingWhileTheTokenIsHeld` · `test_brokenFeedBlocksDepositsToo` | The revert genuinely propagates to `totalAssets()` and to `deposit`. |
| `test_zeroBalanceSkipsTheFeed` | A token with a zero balance is skipped **before** its feed is read, so a broken feed only blocks the vault while it actually holds that token. |
| `test_rejectsStalenessCheckingDisabled` | The deploy script refuses a real network with the check off. |

**Residual risk, unmitigated by design:** the vault trusts its registered feeds. A compromised or
manipulated feed reprices every share. Mitigating that needs a second oracle and a divergence check,
which is out of scope here — though the *agent* now reads Chainlink and the Graph Token API
independently, so a disagreement is visible off-chain even though the contract does not act on it.

### 5.1 · Registered feeds need not be Chainlink — and that is a security surface

`priceFeed(token)` accepts **any contract answering `IAggregatorV3`**, not only a Chainlink-operated
aggregator. That is deliberate and load-bearing: Lane D prices a MetaMorpho share as
`convertToAssets(1 share) × the underlying's USD price`, for which no Chainlink feed exists
(cross-lane #66). Without it, supplying into a 4626 yield-bearing token would collapse the share
price, because the vault would hold something `totalAssets()` cannot value.

The cost is that **the vault cannot tell a derived feed from a native one**, so its staleness
protection is only as good as each feed's honesty about its own age. Requirements on anything
registered into a valuation set:

| Requirement | Why |
|---|---|
| **`updatedAt` must propagate the oldest input**, never `block.timestamp` | A wrapper is recomputed on every call, so stamping "now" feels correct and is trivially defensible in review. It makes the feed permanently self-certify as fresh, silently disabling `priceMaxAge` for that token while every other token in the same vault stays protected. |
| **`decimals()` must match the answer's scale** | The conversion maths trusts it. ETH/USD and USDC/USD are both 8-decimal aggregators, so a wrong-asset feed cannot be caught by decimals alone — `description()` is the real guard. |
| **A non-positive answer must be a revert or a non-positive answer**, never a fabricated fallback | `readPrice` rejects `<= 0`; a feed substituting a stale-but-positive value defeats that. |

| Test | What it proves |
|---|---|
| `test_aNonChainlinkFeedIsAcceptedAndPricesCorrectly` | The capability itself: a derived feed is accepted and prices a holding correctly. |
| `test_aDerivedFeedThatPropagatesItsUpstreamStaysProtected` | A wrapper that propagates its upstream's `updatedAt` inherits its staleness, so the bound still bites. |
| `test_aDerivedFeedThatStampsNowDefeatsStalenessEntirely` | **The failure mode, demonstrated:** a wrapper stamping `block.timestamp` prices a **ten-year-old** upstream answer without reverting and without looking wrong. |

This is not a vault defect — the vault cannot inspect what it is given, by the same design that lets a
new venue ship without touching these contracts. It is a **requirement on the registrar**, and it is
written here because it is invisible from the contract side.

**Lane D's `ERC4626PriceFeed` satisfies it**, confirmed from their published usage doc rather than
assumed. [`venues/README.md`](../venues/README.md):

> **Timestamps pass through from the underlying feed.** `convertToAssets` is always current, so
> reporting `block.timestamp` would make the feed *always look fresh* and silently defeat the vault's
> staleness check — on the half that can actually go stale, the USD price.

They reached that independently, which is the outcome worth having: two lanes deriving the same
requirement from opposite sides is stronger evidence than either one asserting it. The tests above
remain, because the requirement binds **every future registration**, not just this one.

---

## 6 · Sandwiching the agent's rebalance — **mitigated, verified by Lane D**

**Answered by cross-lane request #60, corrected by #64. Verified by decoding real calldata, not by
reading documentation.**

The vault executes opaque calldata against an allowlisted target. That is the seam that lets a venue
adapter be built without touching these contracts — and it means **the vault cannot inspect a
`minOut` it never parses.** Adding that inspection would require the vault to understand every venue's
calldata format, which is precisely the coupling the design exists to avoid. So the protection lives
in the calldata Lane D builds, and only Lane D can attest to it. They have:

> The swap transaction guarantees a minimum output equal to the quoted minimum, derived from the
> mandate's `max_slippage_bps`; depending on route shape this is enforced either as per-leg
> `amountOutMin` values or as a single `SWEEP` minimum on the total.

Measured on the demo path (1,000 USDC → WETH): the effective guarantee is a haircut of **exactly
0.5000%** against the expected output — the **50 bps** in the golden mandate's `max_slippage_bps`.
Shown to be causal rather than coincidental by requesting 10 bps and 200 bps and observing the floor
move correspondingly. Request #26's concern (the API reporting its *default* 250 bps) is closed by
#32: `UNISWAP_SLIPPAGE_BPS=50` is now sent as `slippageTolerance`.

### Reviewer's note — this property has produced a false reading in **both** directions

Worth stating because checking it naively fails twice over:

- **Grepping the calldata for the quoted minimum finds nothing**, which looks like no protection at
  all. The value is not present as a word — it is split across route legs. You have to decode the
  `UniversalRouter.execute(bytes commands, bytes[] inputs, uint256 deadline)` command stream.
- **Decoding the legs and finding zeros looks like a free lunch.** On V3-only split routes each leg
  carries its own non-zero `amountOutMin`. On **mixed V3+V4 routes every leg's `amountOutMin` is 0**,
  and a single trailing `SWEEP` (`0x04`) enforces `amountMin` on the accumulated total instead.
  Verified: `SWEEP.amountMin` exactly equals the quoted minimum.

**Only the aggregate is meaningful** — `max(sum of leg minimums, SWEEP minimum)`. Do not assert
"every leg has a non-zero minOut"; it is false on V4-mixed routes, and a reviewer checking a single
leg would believe they had found a hole.

Pinned by 5 live tests in Lane D's `venues/tests/test_uniswap_minout.py`, computed shape-agnostically.

**Residual risk, and it is real:** the slippage bound is applied **per process**
(`UNISWAP_SLIPPAGE_BPS`), not per mandate. A second vault whose mandate specifies a *tighter* ceiling,
running in the same harness process, would be protected only at the process-wide bound rather than at
its own. Tracked in #33; the fix is a per-intent field, which is a frozen-schema change. With one
vault on the demo path this is latent rather than active, but it is exactly the kind of thing that
becomes wrong the moment a second vault exists.

---

## 7 · Deposit/withdraw sandwiching around a rebalance — **UNMITIGATED, accepted**

An observer who sees a profitable rebalance coming can deposit immediately before it and withdraw
immediately after, capturing a share of the gain without carrying any of the risk. The vault has no
entry fee, no withdrawal fee, no timelock and no share-price cooldown, so nothing prevents this.

**It is not mitigated and will not be in this build.** The standard fixes — an entry/exit fee, a
minimum holding period, or committing to a rebalance behind a delay — each change the depositor
experience materially and need their own testing to avoid introducing worse problems. Adding one
hastily to a hackathon vault would trade a known, bounded, disclosed issue for an unknown one.

What *is* true and does limit it: the reentrancy guard means the sandwich cannot happen atomically
within the rebalance transaction (§8), so an attacker is exposed to at least one block of price risk
rather than none.

Stated here rather than omitted, because an honest limitation is worth more than a silent one.

---

## 8 · Reentrancy — **mitigated**

`nonReentrant` on every mutating path: `execute`, `executeBatch`, `approveVenue`, and the internal
`_deposit`/`_withdraw` that all four ERC-4626 entry points funnel through.

The attack it exists for is specific: a venue call re-entering `deposit` **mid-rebalance** — after the
vault has spent USDC but before it has received the WETH it bought — and minting shares against an
understated `totalAssets()`.

| Test | What it proves |
|---|---|
| `test_venueCannotReenterDeposit` | The real case. `deposit` is permissionless, so the guard is what stops it. |
| `test_venueCannotReenterExecute` | Blocked by the **role check**, not the guard — on re-entry `msg.sender` is the venue, not the agent. Two independent barriers; asserted as the one that actually fires. |

---

## 9 · Deployment-time footguns — **mitigated**

Not a contract vulnerability, but the mistake with the largest blast radius, because everything it
affects is immutable after genesis: a vault deployed wrong can only be abandoned.

| Test | What it proves |
|---|---|
| `test_rejectsAnAnvilAgent` · `test_rejectsAnAnvilDeployer` · `test_rejectsAnAnvilGuardian` | Deploying to a real network with an anvil account in any privileged role reverts. **Anvil's private keys are published in Foundry's own documentation**, and `AGENT_ROLE` can never be revoked — such a vault is drainable by anyone who has read the docs. The fork run defaults to those keys, so this was one forgotten environment variable away. |
| `test_aTypoIsTreatedAsARealNetwork` | An unrecognised `DEPLOY_NETWORK` gets the strict configuration, so a typo fails safe. |
| `test_rejectsADeployerThatCannotPayGas` | An unfunded deployer is rejected *before* anything is published. `forge script` simulates the whole script before broadcasting, so without this the deploy wrote `deployments/base-fork.json` and *then* failed — leaving four lanes reading a factory address with no bytecode. Observed, not hypothesised. |

`script/check-deployment.sh` closes the loop: it verifies the deployed bytecode is byte-for-byte the
committed source, so "verified against the deployed vault" cannot quietly become a claim about
different code.

---

## 10 · Solvency is not liquidity — **inherent to `redeem`, and now escapable**

Found while asserting that everyone redeeming empties the vault. It does not, once the agent has
rebalanced.

**Withdrawals are limited by the vault's *base-asset* balance, not by `totalAssets()`.** ERC-4626 pays
out in one asset; the curator may hold several. Once the agent rotates USDC into WETH, a depositor
whose shares are worth more than the remaining USDC **cannot redeem them** — and the revert surfaces
from the token, not from anything the vault says, so it reads as a broken vault rather than an
illiquid one. `totalAssets()` is correct and unchanged throughout. The value is there; it is not in
the form the exit pays in.

`maxWithdraw`/`previewRedeem` report the **claim**, not what is currently payable. A caller treating
either as "available to withdraw right now" will be wrong whenever the vault holds anything but its
base asset. Lane E's deposit panel and anything else surfacing a withdrawal limit should read
`asset.balanceOf(vault)` alongside them.

### The exit that closes it — `redeemInKind`

**The hole above is unchanged and still real: `redeem` reverts on that book, today, and the test that
says so still passes.** What Wave 3 added is a second door that cannot hit it.

`redeemInKind(shares, receiver, owner)` burns the shares and pays a pro-rata slice of **every**
registered token — the USDC *and* the WETH. It reads no oracle, calls no venue, and needs no
liquidity, because it hands over a fraction of what is already sitting there. It is therefore
**unconditionally payable**, which the base-asset path provably is not. The depositor gets a worse
user experience and a strictly better guarantee, and for an emergency exit that is the right trade.

Four properties, each pinned:

1. **It is never the more generous door.** Payouts use the same virtual-share denominator as
   `previewRedeem`, so the basket is worth at most what the front door quoted — the emergency exit
   cannot be arbitraged against the normal one.
2. **It is not gated on the pause.** Making it paused-only would have handed the guardian a say in
   when depositors may leave, which is exactly the power §12 forbids.
3. **Its residue is the virtual-share offset, not a leak.** When every holder leaves, what stays
   behind is ~10⁻¹⁰ of the book — worth well under a thousandth of a cent.
4. **It is oracle-free, and therefore not oracle-exact.** Flooring a raw balance and flooring its
   valuation do not commute, so a redeemer can leave with up to one unit of the base asset
   (0.000001 USDC, per valued token) more than their exact quote. Closing that would mean pricing the
   payout, which would reintroduce the oracle dependency that makes the exit unconditional in the
   first place. Stated, bounded, and asserted rather than hidden.

| Test | What it proves |
|---|---|
| `test_withdrawalIsLimitedByBaseAssetLiquidityNotTotalAssets` | The hole. 15,000 in `totalAssets()`, 9,000 liquid, a 10,000 redemption reverts while a 9,000 withdrawal succeeds. |
| `test_everyoneRedeemingEmptiesTheVault` | The complement: absent a rotation, every holder redeeming does drain the vault — no value is structurally trapped. |
| `test_redeemInKindClosesTheBookSection10CouldNotPay` | **The same book, both halves in one test.** `redeem` still reverts on it; `redeemInKind` pays the full 10,000 claim as USDC plus the WETH leg. |
| `test_everyHolderCanLeaveAndTheVaultEmpties` | Nobody is trapped: both holders exit in kind, supply reaches zero, residue is worth ≤ 5 units. |
| `test_redeemInKindIsNeverMoreGenerousThanRedeem` | Property 1 — value removed ≤ `previewRedeem`'s quote. |
| `test_redeemInKindPaysProRataOfEveryHolding` | Two thirds of the cash, two thirds of the WETH, and an empty holding still reported. |
| `invariant_theInKindExitIsNeverRefused` | Across every book, price and pause state the campaign reaches, a holder redeeming their own shares is always paid. |
| `invariant_theInKindExitNeverTakesMoreThanItsQuote` | Property 1 again, fuzzed, with property 4's one unit as the stated tolerance. |

**What is still not fixed, and will not be.** `redeem` itself remains liquidity-bound; honouring it
against non-base holdings would need a venue-aware liquidation path inside the vault, which is
exactly the coupling the opaque-calldata seam exists to avoid. `maxWithdraw`/`previewRedeem` still
report the **claim**, not what is payable right now. What keeps the ordinary path liquid is the
mandate's `min_cash_pct` — a **soft, off-chain guarantee enforced by the harness, not the contract.**
The difference Wave 3 makes is that a depositor who hits the limit is no longer stuck waiting for the
harness to behave; they have a door of their own.

---

## 11 · Deployer attribution is a claim, not a signature — **disclosed, and load-bearing**

`VaultFactory` records who a vault was created for: `CreateParams.deployer`, the `deployer` topic on
`VaultCreated`, and the `vaultsOf` / `deployerOf` views. The dashboard needs it because a vault
someone deployed and never deposited into is invisible to any ownership check based on `balanceOf` —
which is exactly the one-click archetype case.

**It is asserted by whoever submits the transaction. There is no signature behind it.** At genesis
the *agent* submits `createVault`, so what the chain records is the agent's assertion about who asked.
Anyone may call `createVault` with any `deployer` and attribute a vault to a stranger.

That is tolerable for precisely one reason: **it confers nothing.** No code path reads it, the vault
never learns it, and it is stored on the factory rather than on the vault specifically so it cannot
quietly become a permission later. It is safe for "show me the vaults I deployed" and unsafe for
anything that decides who may do what.

| Test | What it proves |
|---|---|
| `test_deployerIsAClaimAndGrantsNoPowers` | Bob attributes a vault to Alice unilaterally; Alice then cannot `execute`, cannot `pause`, cannot `setTargetAllowed`, and holds no shares. |
| `test_deployerIsIndexedOnTheEvent` | The topic carries the deployer, with `msg.sender` deliberately a different address so the two cannot collapse. |
| `test_deployerDefaultsToTheSubmitter` | `address(0)` records `msg.sender`, so the mapping is never null. |
| `test_deployerIsRecordedAndQueryable` | `vaultsOf` agrees with the event, and finds a vault whose deployer holds zero shares. |

---

## 12 · The guardian's pause — **what it can and cannot do**

The header used to say there was no pause. That was already not quite true: `setTargetAllowed` is
`onlyRole(GUARDIAN_ROLE)`, so **a guardian who flipped every target off had already stopped all
trading** — one transaction at a time, with no event a dashboard could explain and no way for the
agent to unwind afterwards. `pause()` makes that atomic, legible, and *narrower*.

**The boundary, exactly:**

| Paused | Never pausable |
|---|---|
| Buying anything (`execute`/`executeBatch` are checked, not blocked) | `withdraw`, `redeem`, `redeemInKind` |
| — | `deposit`, `mint` |

**A pause that blocked withdrawals would be a rug vector, not a safety feature** — a guardian able to
freeze depositor exits holds strictly more power than the agent it exists to contain. That boundary is
a test, not a promise.

**The wind-down rule.** While paused the agent may still trade, but the contract reads the balances
afterwards: the base-asset balance must not have fallen, and no registered non-base balance may have
risen. Measured once at the *end* of the call, so a multi-hop route holding an intermediate token is
fine. Two things follow, and both matter more than the headline:

- **It constrains direction, not price.** A batch that dumps WETH for one wei of USDC satisfies it.
  What bounds execution quality is `minOut` in the calldata and the harness's slippage gate, exactly
  as when unpaused. Anything stronger would be an overclaim.
- **It is compositional.** Each paused call individually leaves cash non-decreasing and every holding
  non-increasing, so *any sequence* of them does. The book can only converge on cash.

**Why "must not fall" rather than the stricter "must strictly increase".** Aqua's `dock()` moves no
tokens at all under Pattern 1 — it releases an encumbrance against balances that never left the vault
— and it is the **first step of every Aqua unwind**. A strict-increase rule rejects it, and would
have made the pause unable to start the unwind it exists to enable.

**What the guardian still cannot do.** Name a trade, choose a route or a size, or pick the moment a
position is sold. It flips a flag; the *agent* trades, under the same allowlist and the same
off-chain plan. A guardian able to force a liquidation at a moment of its choosing could trade ahead
of it — a worse power than the one the pause contains.

**Residual, stated rather than hidden.** `approveVenue` is deliberately *not* subject to the
direction rule, because selling through a router requires approving it first and a wind-down that
cannot approve cannot unwind. So a compromised agent in wind-down can still grant an allowance to an
allowlisted venue and have it pulled in a later transaction, which the direction rule never sees.
**That exposure is identical paused or not** — it is bounded by the allowlist, which is §3 — but it
is the reason the claim here is "can only convert the book to cash" rather than "can do nothing".

| Test | What it proves |
|---|---|
| `test_withdrawalSucceedsWhilePaused` | **The boundary.** A paused vault still pays a withdrawal. |
| `test_redeemSucceedsWhilePaused`, `test_redeemInKindWorksWhilePaused` | Both other exits, likewise. |
| `test_depositSucceedsWhilePaused` | Deposits are allowed on purpose; pinned so changing it is deliberate. |
| `test_onlyGuardianMayPause`, `test_onlyGuardianMayUnpause` | Agent, platform owner and a stranger are all refused. |
| `test_guardianStillCannotNameATrade` | The guardian calling `execute` on a paused vault is refused for want of `AGENT_ROLE`. |
| `test_windDownRefusesToIncreaseAHolding` | A gift that raises WETH and spends no cash still reverts — direction alone fails it. |
| `test_windDownRefusesToSpendTheBaseAsset` | The purchase leg. |
| `test_windDownPermitsASale` | The unwind path actually works. |
| `test_windDownMeasuresTheBatchNotEachStep` | The *same two calls* are rejected individually and accepted as one batch. |
| `test_windDownPermitsAValueNeutralCall` | The `dock()` shape — the reason the rule is not "strictly increase". |
| `test_windDownConstrainsDirectionNotPrice` | 6,000 USDC of WETH sold for one wei, and the contract permits it. |
| `test_windDownRuleLiftsWhenUnpaused` | The rule binds only while paused. |
| `test_pausedVaultPricesExactlyAsBefore` | `totalAssets`, share price and the quoted claim are untouched by a pause. |
| `test_bothTransitionsEmitAndAreReadableOnChain` | `paused()` backs `VaultState.paused`; both transitions emit. |
| `invariant_windDownOnlyMovesTowardCash` | Across every interleaving the fuzzer reaches — pausing and unpausing at moments of its own choosing while continuing to attempt purchases — no paused call ever moved the book away from cash. |

---

## What is deliberately not defended

| | |
|---|---|
| **A malicious or compromised agent** | The agent is trusted with the assets by design. The allowlist limits blast radius; it does not constrain intent. A compromised key cannot be revoked — but §12 means a guardian can reduce it to *selling only*, at whatever price it likes, while every depositor's exit stays open. |
| **Mandate violations** | The mandate is soft and off-chain. Nothing on-chain enforces allocation limits — that is the harness's job, in six validation layers. |
| **Oracle compromise** | The vault trusts Chainlink. No second source, no divergence check. |
| **Sandwiching around a rebalance** | §7. Disclosed, not fixed. |
| **Tokens the vault cannot price** | A token held but absent from the valuation set is invisible to `totalAssets()`. The mandate must confine the agent to tokens with a registered feed. `invariant_totalAssetsEqualsValuedHoldings` pins the accounting; nothing pins the mandate. |
| **Withdrawal liquidity on `redeem`** | §10. The vault can be solvent and still unable to pay a *base-asset* redemption; held off by the mandate's `min_cash_pct`, not by the contract. What is no longer undefended is being **trapped** — `redeemInKind` always pays. |
| **Execution price during a wind-down** | §12. The paused-mode rule reads balances, so it forbids buying and permits selling at any price. Quality is `minOut`'s job, paused or not. |
| **Attribution of a vault to its deployer** | §11. `deployer` is asserted by the transaction's submitter, not signed. Safe for display, never for authorization. |
| **A dishonest registered price feed** | §5.1. The vault cannot distinguish a derived feed from a native one, so a feed that misreports its own age silently disables staleness checking for that token. A requirement on the registrar, demonstrated by test, not enforceable here. |

---

## Coverage note

`test/invariant/HandlerSanity.t.sol` exists because every invariant in this document holds trivially
on a vault nothing ever happened to. It drives each handler action deterministically and asserts each
one individually, so a handler action that silently became a no-op fails with its own name rather
than turning the whole suite green while proving nothing. Foundry's per-function call distribution at
the end of an invariant run is the same signal — a zero in the `calls` column means that action never
ran.
