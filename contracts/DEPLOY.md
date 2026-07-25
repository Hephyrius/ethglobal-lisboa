# Going live on Base mainnet

The ordered runbook for deploying `CuratedVault` + `VaultFactory` to real Base with real money in
front of it. For the local fork, [README.md](README.md#quick-start) is enough — this file is about
the run you cannot take back.

> **Read this first.** Almost everything the deploy sets is **immutable at genesis**. The role graph
> is frozen — `grantRole`, `revokeRole` and `renounceRole` all revert — and there is no valuation
> setter for anybody. A vault deployed with the wrong agent key, or a feed it cannot read, cannot be
> repaired. It can only be abandoned and redeployed, and any deposits made in between are stuck with
> whatever was wrong. The guards in `Deploy.s.sol` exist because of that, and they **revert rather
> than warn** for the same reason: a warning scrolls past in a broadcast log.

---

## 0 · What you need before you start

| | |
|---|---|
| **An archive-capable Base RPC** | `BASE_RPC_URL`. The public `mainnet.base.org` is rate-limited and will make the dry run crawl. Not fatal for a deploy, fatal for a fork. |
| **A funded deployer** | `DEPLOYER_PRIVATE_KEY`, holding ETH on Base. The deploy costs ~7.7M gas — pennies at Base gas prices — and the script refuses to start below 0.001 ETH. |
| **An agent key** | `AGENT_ADDRESS`. **This key moves the money and can never be revoked.** It should be a fresh key that has never touched anything else. |
| **A guardian address** | `GUARDIAN_ADDRESS`, and it **must not equal the agent** — the script refuses. Ideally not the deployer either. |
| **The mandate hash** | `MANDATE_HASH`, the keccak of the canonical mandate JSON the vault will be created with. Defaults to a demo value; set it deliberately. |

Anvil accounts are refused for all three roles. Their private keys are in Foundry's own
documentation, so a mainnet vault whose `AGENT_ROLE` is anvil #1 can be drained by anyone who has
read them — and because the role graph is frozen, could not be rescued.

---

## 1 · Prove the source before you deploy it

```bash
cd contracts
forge build                                  # must be warning-free
forge test                                   # 153 tests, no network
FOUNDRY_PROFILE=deep forge test --match-path "test/invariant/*"
```

The deep invariant campaign takes ~5 minutes and is the last chance to find a property failure with
nobody's money at stake. Skip it on a fork; do not skip it here.

---

## 2 · Dry run — the same command without `--broadcast`

```bash
DEPLOY_NETWORK=base-mainnet \
DEPLOYER_PRIVATE_KEY=0x…  AGENT_ADDRESS=0x…  GUARDIAN_ADDRESS=0x…  MANDATE_HASH=0x… \
forge script script/Deploy.s.sol --rpc-url "$BASE_RPC_URL"
```

`forge script` simulates the whole script against live state, so **every guard fires here first** and
nothing is sent. This is not a formality — it is where a wrong key, a wrong chain or a dead feed
shows up, and it costs nothing.

Read the logged `VaultFactory` / `Implementation` / `Demo vault` addresses and the `agent`,
`guardian` and `priceMaxAge` lines. Confirm they are what you meant. `priceMaxAge` must be **3600**;
if it says 0 you are not on the network you think you are.

> ⚠️ **A dry run still writes `deployments/base-mainnet.json`.** Publishing happens outside the
> broadcast block, so the file describes contracts that do not exist yet. Do not commit it or hand it
> to anyone until step 3 has actually succeeded.

### What the guards will stop

| Revert | What it saved you from |
|---|---|
| `UnsafeAnvilKeyOnRealNetwork` | A vault anyone can drain, permanently. |
| `AgentAndGuardianAreTheSameAccount` | One key that can both trade and halt trading — neither role, and unfixable. |
| `StalenessCheckDisabledOnRealNetwork` | Shares pricing off a frozen feed during exactly the volatility that stalls feeds. |
| `WrongChainForNetwork` | One wrong `--rpc-url`. Every address in the script is Base mainnet. |
| `AllowlistedTargetHasNoCode` / `PriceFeedHasNoCode` | An address that is not a contract here. |
| `StalePrice` / `InvalidPrice` / `IncompleteRound` | A vault whose `totalAssets()` reverts on its first call — no deposits, no withdrawals, no share price. The feed is read through the **same library call the vault will make**, with the **same bound it is about to freeze**. |
| `DeployerCannotPayGas` | A half-finished deploy and a published file pointing at nothing. |

---

## 3 · Deploy

```bash
# identical to step 2, plus --broadcast
… forge script script/Deploy.s.sol --rpc-url "$BASE_RPC_URL" --broadcast
```

---

## 4 · Prove what landed — both checks, they answer different questions

```bash
DEPLOY_NETWORK=base-mainnet forge script script/VerifyDeployment.s.sol --rpc-url "$BASE_RPC_URL"
./script/check-deployment.sh base-mainnet "$BASE_RPC_URL"
```

**`check-deployment.sh` asks whether the deployed bytecode is this repo's source.** A question about
compilation. It is what makes "audited against this code" mean anything.

**`VerifyDeployment.s.sol` asks whether the live contract is configured the way the published file
claims, and whether it can actually function.** A question about state. A vault can pass the first
and fail the second in every way that matters: right code and the wrong agent; right code and an
allowlist missing the router every plan targets; right code and a feed that has stopped answering, so
`totalAssets()` reverts and nobody can deposit or withdraw.

It checks, and reverts by name on any of: the published chain id, factory/implementation/vault all
holding code, the vault registered with its factory, asset + agent + guardian + mandate hash +
`priceMaxAge` matching the file, **the role graph frozen on chain** (nobody holds admin; all three
mutators revert), the allowlist matching the published set exactly, every registered feed readable
through `readPrice` at the vault's own bound, `totalAssets()` and `holdings()` returning, and the
pause/`redeemInKind`/attribution surface being present and the vault not already paused.

It never broadcasts — there is no `startBroadcast` in the file — so it is safe to run against mainnet
whenever you want reassurance.

---

## 5 · Verify the source publicly

```bash
./script/verify.sh base-mainnet
```

Blockscout, not Etherscan: there is no free Etherscan path for Base — V2 rejects the chain and
basescan V1 is deprecated. No API key needed.

> `verify.sh` is written and its error paths are tested, but it has **not** yet been run against a
> live Blockscout instance. Budget time for it to need a nudge.

---

## 6 · Publish

Commit `deployments/base-mainnet.json` and tell the other lanes, because **every lane reads addresses
from that file rather than hardcoding them.** A deploy that is not published is a deploy that
silently breaks four lanes.

---

## Afterwards — what is and is not still changeable

| Changeable | By whom | How |
|---|---|---|
| The vault's target allowlist | `GUARDIAN_ROLE` | `setTargetAllowed(target, allowed)` |
| Wind-down on/off | `GUARDIAN_ROLE` | `pause()` / `unpause()` |
| Defaults handed to **future** vaults | factory owner | `setDefaultTarget`, `setDefaultValuation`, `setDefaultPriceMaxAge` — these never reach a vault that already exists |

| Frozen forever | Why it is frozen |
|---|---|
| The agent and guardian keys | Nobody can replace the agent or award themselves its powers. A compromised agent key cannot be revoked — the vault would have to be wound down and exited. |
| The valuation set and its feeds | This is where a mutable setting would be genuinely exploitable: registering a bogus feed reprices every share. So there is no setter at all. |
| `priceMaxAge` | Same reason, at genesis. |
| The base asset and mandate hash | Identity. |

**If the agent key is compromised**, the play is `pause()` → the agent can then only sell, never buy
→ depositors exit through `redeem` as the book converges to cash, or immediately through
`redeemInKind`, which needs no oracle, no venue and no liquidity. That is the whole reason
[SECURITY.md](SECURITY.md) §12 exists. There is no rescue path that recovers the vault itself.

---

## Reproducibility, and a claim this repo got wrong

A CREATE address is `keccak(deployer, nonce)`. On mainnet your deployer is a fresh key, so its nonce
starts at 0 and the addresses are yours to predict.

**On a fork that is not true**, and an earlier version of the README said it was. The fork deployer is
anvil account #0 — a published test key that strangers transact from on real Base constantly — so a
fork **inherits its real mainnet nonce**, which was 3,393,100 at block 49,077,772 and 3,393,112 at
49,166,831. Restart the fork at a newer head and every deployed address moves. Pin
**`FORK_BLOCK_NUMBER`** if you need a fork deploy to reproduce; nonce 0 was never what made it work.
