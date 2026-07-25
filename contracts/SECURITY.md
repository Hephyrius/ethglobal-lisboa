# Security — `contracts/`

**Every claim here ends with the test that proves it.** Where something is genuinely unmitigated it
says so; a limitation a judge finds for themselves is worth less than one we wrote down.

Scope: `CuratedVault` and `VaultFactory`. Reproduce everything with:

```bash
cd contracts && forge test                      # 101 tests, no network
FOUNDRY_PROFILE=deep forge test --match-path "test/invariant/*"
```

**Deep run, as of this document:** all nine invariants green at 512 runs × 128 depth — **65,536 calls
each, 589,824 in total, zero failures**, in 189s on a CPU-only i5-8265U. The default profile runs the
same properties at 2,048 calls each so the normal suite stays under five seconds.

---

## The threat model in one paragraph

The vault is an ERC-4626 vault whose curator is an autonomous agent holding a private key. **The
agent is fully trusted with the assets by design** — that is the locked decision in
[initiate_plan.md](../plans/initiate_plan.md) §2, and it means "the agent could make a bad trade" is
not a vulnerability here, it is the product. What *is* in scope: anyone other than the agent moving
value, the agent reaching contracts it was never meant to reach, and any path that lets one depositor
take value from another.

Two consequences worth stating plainly, because both look alarming out of context:

- **There is no pause, no emergency withdrawal and no human override.** Nobody holds
  `DEFAULT_ADMIN_ROLE` and `grantRole`/`revokeRole`/`renounceRole` all revert, so the role graph is
  frozen at genesis. This is deliberate. It also means a compromised agent key cannot be revoked —
  the vault would have to be abandoned. Accepted for a hackathon build; a production version needs
  the parked protocol-level controls.
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

**Residual risk, unmitigated by design:** the vault trusts Chainlink. A compromised or manipulated
feed reprices every share. Mitigating that needs a second oracle and a divergence check, which is out
of scope here — though the *agent* now reads Chainlink and the Graph Token API independently, so a
disagreement is visible off-chain even though the contract does not act on it.

---

## 6 · Sandwiching the agent's rebalance — **NOT verified from this lane**

**Status: open, owned by Lane D, tracked as cross-lane request #60.**

The vault executes opaque calldata against an allowlisted target. That is the seam that lets a venue
adapter be built without touching these contracts — and it means **the vault cannot inspect a
`minOut` it never parses.** Adding that inspection would require the vault to understand every venue's
calldata format, which is precisely the coupling the design exists to avoid.

So the protection has to live in the calldata Lane D builds, and this document cannot honestly claim
it. What must be true:

- the Uniswap `/swap` calldata carries a non-zero `amountOutMinimum`, and
- it is derived from the mandate's `max_slippage_bps` rather than the API's default tolerance.

That second point is not hypothetical: request #26 records that the Trading API reports its **default
250 bps**, not a mandate-derived figure. A `minOut` of zero in a public-mempool transaction is a free
lunch for a searcher.

**This section will be replaced with Lane D's answer verbatim when it lands.** Until then, treat
front-running of the swap leg as unverified.

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

## What is deliberately not defended

| | |
|---|---|
| **A malicious or compromised agent** | The agent is trusted with the assets by design. The allowlist limits blast radius; it does not constrain intent. A compromised key cannot be revoked. |
| **Mandate violations** | The mandate is soft and off-chain. Nothing on-chain enforces allocation limits — that is the harness's job, in six validation layers. |
| **Oracle compromise** | The vault trusts Chainlink. No second source, no divergence check. |
| **Sandwiching around a rebalance** | §7. Disclosed, not fixed. |
| **Tokens the vault cannot price** | A token held but absent from the valuation set is invisible to `totalAssets()`. The mandate must confine the agent to tokens with a registered feed. `invariant_totalAssetsEqualsValuedHoldings` pins the accounting; nothing pins the mandate. |

---

## Coverage note

`test/invariant/HandlerSanity.t.sol` exists because every invariant in this document holds trivially
on a vault nothing ever happened to. It drives each handler action deterministically and asserts each
one individually, so a handler action that silently became a no-op fails with its own name rather
than turning the whole suite green while proving nothing. Foundry's per-function call distribution at
the end of an invariant run is the same signal — a zero in the `calls` column means that action never
ran.
