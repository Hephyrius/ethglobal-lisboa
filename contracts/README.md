# `contracts/` — Lane A · the vault, the factory, and the agent's authorization boundary

ERC-4626 vaults curated by an autonomous agent. This document is the integration surface: everything
another lane needs is here, and **nothing else in this directory should have to be read.**

- **Owner:** Lane A. Nobody else edits `contracts/`. Lane D's Solidity lives in `venues/aqua/solidity/`.
- **Security:** [SECURITY.md](SECURITY.md) — every attack vector, each with the test that proves the
  claim, and the two that are deliberately *not* mitigated.
- **Plan:** [plans/2026-07-25-lane-a-contracts.md](../plans/2026-07-25-lane-a-contracts.md)
- **Toolchain:** Foundry, run inside `wsl -d Ubuntu-24.04` (the default 20.04 distro has glibc 2.31,
  too old for Foundry's binaries). Native on macOS.

---

## Purpose

A `CuratedVault` takes deposits in a base asset (USDC on Base), issues ERC-4626 shares, and hands
every allocation decision to an off-chain LLM agent that holds a key and executes directly. The vault
is the **sole custodian** of all capital at all times — Pattern 1, the locked decision in
[initiate_plan.md](../plans/initiate_plan.md) §2. Capital never leaves it, not even while an Aqua
strategy is open, because Aqua tracks *virtual* balances against tokens that stay in the maker's
wallet. So `balanceOf(vault)` is the complete position picture and `totalAssets()` is honest without
reading any venue's state.

`VaultFactory` clones one vault per strategy and holds the default configuration new vaults inherit.

---

## Quick start

```bash
cd contracts
./script/install-deps.sh          # vendored, pinned — only needed to change a version
forge build
forge test                        # 153 tests, no network required (+9 fork tests skip)
```

Fork deployment (from repo root, two terminals):

```bash
./scripts/anvil-fork.sh                                    # terminal 1 — needs BASE_RPC_URL
cd contracts && forge script script/Deploy.s.sol \
  --rpc-url http://127.0.0.1:8540 --broadcast              # terminal 2
```

The deploy writes [`deployments/base-fork.json`](../deployments/base-fork.json). **Read addresses
from that file. Never hardcode them.**

> ⚠️ **Redeploying overwrites that file, and Lanes B, D and E read the vault address from it.** Only
> redeploy if anvil has been restarted, and tell the other lanes when you do.
>
> **The addresses will change, and an earlier version of this file claimed otherwise.** The claim was
> that a cold deploy at nonce 0 reproduces the same addresses. It does not, and cannot: a CREATE
> address is `keccak(deployer, nonce)`, and the fork deployer is **anvil account #0 — a key whose
> private key is published in Foundry's docs and which strangers therefore transact from on real Base
> constantly.** Forking inherits its real nonce, which was 3,393,100 at block 49,077,772 and
> 3,393,112 at 49,166,831. Fork at a newer head, get a different nonce, get different addresses.
>
> Deploys *are* reproducible if you pin **`FORK_BLOCK_NUMBER`**, because then the inherited nonce is
> fixed too. That is the only thing that makes a replay non-disruptive; nonce 0 never had anything to
> do with it. Set it in `.env` before a demo you might need to reproduce.

**A fork deploy deliberately ignores `DEPLOYER_PRIVATE_KEY`.** That variable is the funded *mainnet*
wallet, so it has no balance on a fresh fork — reading it here meant merely sourcing `.env` turned a
working deploy into a failing one. Fork deploys sign with anvil account #0; set
`FORK_DEPLOYER_PRIVATE_KEY` if you need a different one.

> **No `BASE_RPC_URL`?** `forge test` is unaffected — the unit suite is entirely mock-based and needs
> no network. Only `test/fork/` and the fork deploy need one, and the fork tests skip themselves
> cleanly when the variable is absent.

### Deploying to a real network

**Follow [DEPLOY.md](DEPLOY.md).** It is the go-live runbook — the ordered steps, what to have ready,
and what to check after. The short form:

```bash
DEPLOY_NETWORK=base-mainnet \
DEPLOYER_PRIVATE_KEY=0x…  AGENT_ADDRESS=0x…  GUARDIAN_ADDRESS=0x… \
forge script script/Deploy.s.sol --rpc-url "$BASE_RPC_URL"            # dry run first, no --broadcast
                                                              # then again with --broadcast

DEPLOY_NETWORK=base-mainnet forge script script/VerifyDeployment.s.sol --rpc-url "$BASE_RPC_URL"
./script/check-deployment.sh base-mainnet "$BASE_RPC_URL"
./script/verify.sh base-mainnet    # Blockscout — no API key
```

`priceMaxAge` is derived from the network: `0` on `base-fork`, **3600 everywhere else**. You do not
need to remember to set it.

The script **refuses** these rather than warning, because every one of them is immutable after
genesis and would mean abandoning the vault:

| Revert | Cause |
|---|---|
| `UnsafeAnvilKeyOnRealNetwork(what, account)` | deployer, agent or guardian is an anvil account. Their keys are published in Foundry's docs, and `AGENT_ROLE` can never be revoked |
| `StalenessCheckDisabledOnRealNetwork(network)` | `priceMaxAge == 0`, so `totalAssets()` would trust a Chainlink answer of any age |
| `AgentAndGuardianAreTheSameAccount(account)` | one key holding both roles is neither. The guardian may halt trading but never name a trade; the agent may trade but never halt itself |
| `WrongChainForNetwork(network, expected, actual)` | one wrong `--rpc-url`. Every address in the script is Base mainnet; elsewhere they are empty accounts |
| `AllowlistedTargetHasNoCode(target)` / `PriceFeedHasNoCode(feed)` | an address in the script is not a contract on this chain |
| `StalePrice` / `InvalidPrice` / `IncompleteRound` | **the feed is read through the same `ChainlinkPriceLib.readPrice` `totalAssets()` will call**, with the bound this vault is about to freeze — so the deploy cannot create a vault whose accounting reverts on first use |

An unrecognised `DEPLOY_NETWORK` counts as real, so a typo gets the strict settings.

> Verification goes through **Blockscout, not Etherscan** — there is no free Etherscan path for Base
> (V2 rejects the chain, basescan V1 is deprecated). `script/verify.sh` is written and its error paths
> are tested, but it has **not** been run against a live Blockscout instance yet.

---

## What to import

| You want | Take it from |
|---|---|
| ABIs | `contracts/abis/CuratedVault.json`, `contracts/abis/VaultFactory.json` — **flat ABI arrays**, hand straight to `web3.py` or `viem` |
| Addresses | `deployments/base-fork.json` |
| Raw Foundry artifacts | `contracts/out/**` — same ABI, nested under `.abi`, alongside bytecode |

```python
# Lane B — web3.py
import json, pathlib
root = pathlib.Path(__file__).parents[2]
abi = json.loads((root / "contracts/abis/CuratedVault.json").read_text())
dep = json.loads((root / "deployments/base-fork.json").read_text())
vault = w3.eth.contract(address=dep["demoVault"]["address"], abi=abi)
```

```ts
// Lane E — viem
import abi from "../../contracts/abis/CuratedVault.json";
import deployments from "../../deployments/base-fork.json";
```

Re-run `./script/export-abis.sh` after any signature change and commit the result.

---

## Public interface

### Agent surface — `AGENT_ROLE` only

```solidity
function execute(address target, uint256 value, bytes calldata data) external returns (bytes memory);
function executeBatch(Call[] calldata calls) external returns (bytes[] memory);
function approveVenue(address token, address spender, uint256 amount) external;

struct Call { address target; uint256 value; bytes data; }
```

`execute` is the whole seam. `target` must be on the allowlist; `data` is opaque and never inspected,
so a venue adapter builds any calldata off-chain and a new venue is a new adapter, never a contract
change. Return data comes back to the caller, and a failed call bubbles the callee's own revert data
so a broken venue call is diagnosable from the trace.

**Prefer `executeBatch` for anything with more than one step.** An `ExecutionPlan` is ordered —
approve, then swap — and `executeBatch` applies it atomically, so a plan can never land half-applied.
The steps map one-to-one onto `ExecutionPlan.steps[]`.

`approveVenue` is a narrower alternative to `execute(token, 0, approve(...))`: `spender` is checked
against the allowlist and no arbitrary calldata reaches the token. It uses `forceApprove`, so
re-approving a non-zero allowance works on USDT-family tokens. Either form is fine — **token
addresses are allowlisted targets**, so the golden fixture's `USDC.approve(Permit2, …)` step works
unchanged.

### Guardian surface — `GUARDIAN_ROLE` only

```solidity
function setTargetAllowed(address target, bool allowed) external;
function pause() external;
function unpause() external;
```

The guardian's two powers, and they are narrower than they look.

`pause()` puts the vault in **wind-down**. It does *not* stop the agent trading; it changes what
trading is allowed to accomplish. While paused the contract reads the balances at the end of every
`execute`/`executeBatch` and reverts unless the base-asset balance did not fall and no registered
non-base balance rose. **Selling is permitted, buying is not**, so the book can only converge on
cash. Intermediate state within a batch is unconstrained, so a multi-hop route holding a third token
mid-way is fine — only the net effect is judged.

**Withdrawals are never affected.** `withdraw`, `redeem` and `redeemInKind` work identically paused
or not, and nothing any role can do changes that. If you are surfacing this state in a UI, say
*"trading is halted, withdrawals are not"* — a depositor who reads "paused" alone assumes their money
is stuck, which is the exact opposite of the truth.

`approveVenue` also keeps working while paused, because selling through a router means approving it
first. Full boundary, including the residual that implies: [SECURITY.md §12](SECURITY.md).

### Exits — permissionless, never pausable

```solidity
function redeemInKind(uint256 shares, address receiver, address owner)
    external returns (InKindPayout[] memory payouts);

struct InKindPayout { address token; uint256 amount; }
```

Burns `shares` and pays a pro-rata slice of **every** registered token — index 0 is the base asset,
matching `holdings()`. No oracle read, no venue call, no liquidity requirement.

**Use it when `redeem` reverts.** `redeem` pays in one asset, so once the agent has rotated into
WETH a holder whose claim exceeds the vault's USDC balance cannot exit through it — the revert comes
from the ERC-20, so it reads as a broken vault rather than an illiquid one ([SECURITY.md §10]
(SECURITY.md)). `redeemInKind` cannot hit that: it hands over a fraction of what is already there.
The receiver gets WETH alongside USDC, which is a worse experience and a strictly better guarantee.

Priced with the same virtual-share denominator as `previewRedeem`, so it is never the more generous
of the two exits. Callable whether or not the vault is paused.

### Views

```solidity
function agent()          external view returns (address);
function guardian()       external view returns (address);
function mandateHash()    external view returns (bytes32);
function priceMaxAge()    external view returns (uint256);
function paused()         external view returns (bool);

function isAllowedTarget(address target) external view returns (bool);
function allowedTargets() external view returns (address[] memory);
function valuedTokens()   external view returns (address[] memory);
function priceFeed(address token) external view returns (address);

function holdings() external view returns (Holding[] memory);
struct Holding { address token; uint8 decimals; uint256 balance; uint256 valueInAsset; }
```

Plus the full ERC-4626 and ERC-20 surface: `deposit`, `mint`, `withdraw`, `redeem`, `totalAssets`,
`convertToAssets`, `convertToShares`, `previewDeposit`, `balanceOf`, `transfer`, …

### Factory

```solidity
function createVault(CreateParams calldata params) external returns (address vault);
struct CreateParams { address asset; string name; string symbol;
                      address agent; address guardian; bytes32 mandateHash;
                      address deployer; }

event VaultCreated(address indexed vault, address indexed asset, address agent,
                   bytes32 mandateHash, address indexed deployer);

function vaultsOf(address who) external view returns (address[] memory);
function deployerOf(address vault) external view returns (address);
```

**`deployer` is who *asked* for the vault, and it is a label rather than a permission.** The agent
submits `createVault`, so `msg.sender` records the agent and nothing else on-chain links a human to a
vault they requested — which makes a vault someone deployed and never deposited into invisible to any
ownership check based on `balanceOf`. Passing `address(0)` records `msg.sender`, so the answer is
never null.

It is **asserted by the submitter, not proven by a signature**: anyone may call `createVault` with
any `deployer`. Safe for "show me my vaults"; never gate anything on it. Nothing in the contracts
reads it, and it lives on the factory rather than the vault so it cannot quietly become a permission.
[SECURITY.md §11](SECURITY.md).

`vaultsOf` answers "my vaults" in one `eth_call` with no block range and no topic filter. The event
stays the source of truth for indexers; the view is a cache of it written in the same statement, so
they cannot disagree.

Owner-only: `setDefaultTarget`, `setDefaultValuation`, `setDefaultPriceMaxAge`.
Views: `implementation()`, `vaults()`, `vaultCount()`, `isVault()`, `defaultTargets()`,
`defaultValuations()`, `defaultPriceMaxAge()`.

### Events

| Event | Use |
|---|---|
| `VaultCreated(vault indexed, asset indexed, agent, mandateHash, deployer indexed)` | index new vaults, and "my vaults" by `deployer` topic. **`agent` is no longer indexed** — an event has three topic slots and at genesis every vault shares one agent key, so it was an index that indexed nothing |
| `VaultInitialized(asset, agent, guardian, mandateHash)` | genesis record |
| `Executed(target indexed, selector indexed, value)` | decision feed — filter by call type without decoding calldata |
| `VenueApproved(token, spender, amount)` | approval trail |
| `TargetAllowed(target, allowed)` | allowlist changes |
| `TradingPaused(guardian indexed)` / `TradingUnpaused(guardian indexed)` | wind-down begins and ends. **Named for what they do**: a log reading `Paused` invites "my money is stuck", which is false |
| `RedeemedInKind(caller indexed, receiver indexed, owner indexed, shares, payouts[])` | an in-kind exit and exactly what it paid |
| ERC-4626 `Deposit` / `Withdraw`, ERC-20 `Transfer` | TVL and share movements |

### Errors

`TargetNotAllowed(address)` · `SpenderNotAllowed(address)` · `EmptyBatch()` · `ZeroAddress()` ·
`DuplicateValuation(address)` · `RolesAreFrozen()` · `AlreadyPaused()` · `NotPaused()` ·
`WindDownWouldSpendBaseAsset(before, after)` · `WindDownWouldIncreaseHolding(token, before, after)` ·
`StalePrice(feed, updatedAt, maxAge)` · `InvalidPrice(feed, answer)` · `IncompleteRound(feed)` ·
plus OpenZeppelin's `AccessControlUnauthorizedAccount(account, role)` and
`OwnableUnauthorizedAccount(account)`.

---

## Data shapes — read this before wiring up

### Shares are 18-decimal over a 6-decimal asset

`_decimalsOffset()` is **12**, so `decimals()` returns 18 while the asset has 6. Two reasons: it is
OpenZeppelin's virtual-shares defence against the first-depositor inflation attack, and 18-decimal
shares are what wallets and charting libraries expect.

**The consequence that will bite you:** `convertToAssets(1e18)` — the value of one whole share — is
denominated in the **base asset**, so it returns a 6-decimal number.

```
1_000_000        -> 1.00 USDC per share
1_002_506        -> 1.0025 USDC per share
```

It does **not** return `1e18`. Verified on the fork: 5,000 USDC deposited into an empty vault gives
`5000e18` shares and `convertToAssets(1e18) == 1000000`.

> `packages/schema/fixtures/vault-state.json` carries a `share_price` that is 10^12 too large for its
> own `total_assets` / `total_supply`. The fixture is fine to develop against — just don't derive the
> formula from it.

### Filling `VaultState`

| Schema field | Where it comes from |
|---|---|
| `address` | the vault |
| `asset`, `asset_decimals` | `asset()`, 6 for USDC |
| `total_assets`, `total_supply` | `totalAssets()`, `totalSupply()` |
| `share_price` | `convertToAssets(1e18)` — 6-decimal, see above |
| `holdings[]` | **`holdings()` in one call.** Index 0 is always the base asset. `symbol` is not returned — read it from the token, or hardcode for USDC/WETH |
| `agent`, `mandate_hash` | `agent()`, `mandateHash()` |
| `paused` | **`paused()` — real since Wave 3.** `true` means *the agent may only sell*; it does **not** mean withdrawals are suspended, and nothing can make it mean that |
| `aqua_strategies[]` | **not on-chain here.** The vault does not track Aqua positions; the harness records them when it ships one |

### `ExecutionPlan` → chain

`ExecutionPlan.steps[]` maps directly onto `Call[]`. Validate every `step.target` against
`allowedTargets()` *before* submitting — a non-allowlisted target reverts the whole batch.

---

## Dependencies

- **OpenZeppelin v5.1.0** (`contracts` + `contracts-upgradeable`) and **forge-std v1.9.4**, vendored
  into `lib/oz`, `lib/oz-upgradeable`, `lib/forge-std` at pinned tags and committed.

  Vendored rather than installed as git submodules for two reasons: `.gitmodules` is a
  repository-root file Lane D also writes for its own Foundry project, and two agents editing it
  concurrently is the collision Rule 7 exists to prevent; and a plain `git clone` has to compile on
  macOS at handoff without `--recursive` or a half-empty `lib/`. Unused trees (mocks, governance,
  finance, metatx, crosschain, account, vendor) are pruned — nothing here compiles them, and their
  path lengths were breaking `git clone` on Windows against the 260-character `MAX_PATH` limit.

  `./script/install-deps.sh` regenerates the whole tree; `--force` re-fetches.

- **Chainlink price feeds** on Base, read live. Only `IAggregatorV3` is declared locally.
- **No dependency on any other lane.**

---

## Assumptions & invariants

Things a caller may rely on, and things a caller must guarantee.

**The vault is sole custodian.** Assets never leave. `holdings()` is the complete position picture
even while Aqua strategies are open. `totalAssets()` deliberately does **not** read Aqua virtual
balances — the tokens are still here, so `balanceOf` already counts them and adding the virtual
balance would double-count.

**The role graph is frozen at genesis.** `DEFAULT_ADMIN_ROLE` is granted to nobody, and `grantRole`,
`revokeRole` and `renounceRole` all revert. No human can replace the agent, award themselves its
powers, or brick the vault by renouncing. This is the locked trust model stated in code.

**There is no human override and no way for anyone to seize funds.** Deliberate
([initiate_plan.md](../plans/initiate_plan.md) §2). What *is* enforced on-chain is blast radius: the
agent may only reach allowlisted contracts.

**The allowlist bounds *which contracts* the agent may call, not what it may do there.** Within an
allowlisted target the agent has full latitude — consistent with a trust model that already grants it
the key. It is a blast-radius limiter, not a mandate enforcer.

**The guardian can edit the allowlist and start a wind-down. That is all.** It cannot move funds,
name a trade, choose when a position is sold, replace the agent, or touch valuation. Widening the
list grants it nothing it could exploit alone, because only `AGENT_ROLE` can call `execute`. Accepted
residual risk, stated rather than hidden: a guardian *narrowing* the list, or pausing, can grief a
rebalance. That is liveness, not custody.

**No state of this vault can trap a depositor.** `withdraw`, `redeem` and `redeemInKind` are
permissionless and unpausable in every state the contract can be in, and `redeemInKind` needs no
oracle, venue or liquidity to pay. A guardian able to freeze exits would hold strictly more power
than the agent it exists to contain, so that boundary is a test rather than a promise —
`test_withdrawalSucceedsWhilePaused` and `invariant_theInKindExitIsNeverRefused`.

**While paused, the agent can only move the book toward cash.** The contract checks the balances at
the end of every agent call: base non-decreasing, every registered holding non-increasing. It
constrains **direction, not price** — a sale at a terrible price satisfies it, and `minOut` is what
bounds execution quality, paused or not.

**Valuation is immutable, for everyone.** This is where a mutable setting would be genuinely
exploitable — registering a bogus feed reprices every share — so there is no setter at all.

**A token the vault holds but was never registered is invisible to `totalAssets()`.** The sharpest
edge in the design. *The mandate must confine the agent to tokens the vault can price.* Registered
tokens are `valuedTokens()`; on the fork deployment that is WETH only.

**`totalAssets()` reverts rather than returning a wrong number.** A stale, zero, negative or
incomplete Chainlink answer reverts, which blocks deposits and withdrawals. Valuing a held token at
zero instead would silently misprice shares and let a withdrawal drain value from everyone else. A
token with a **zero balance is skipped before its feed is read**, so a broken feed only blocks the
vault while it actually holds that token.

**`priceMaxAge = 0` disables the staleness check, and the fork deployment uses 0.** Required: on a
pinned anvil fork the forked feed's `updatedAt` is frozen at the fork block while `block.timestamp`
keeps advancing, so any non-zero bound starts failing minutes into a session. The mainnet run passes
3600.

**One base-asset unit is treated as exactly $1.** True enough for USDC, and the one approximation in
the share-price path. Pricing the asset leg through its own feed is a stretch item.

**The vault holds no native ETH.** There is no `receive()`, so it cannot accrue any. `execute`'s
`value` parameter exists because the frozen `ExecutionPlan` shape has one; in practice it is always
`"0"`. Native-ETH swap legs are not supported — use WETH.

**Rounding always favours the vault.** A deposit-then-redeem round trip returns at most what went in,
losing at most one base unit. Asserted by fuzz test.

---

## Layout

```
src/
  CuratedVault.sol            ERC-4626 + roles + execute surface + totalAssets
  VaultFactory.sol            clones, mutable defaults, VaultCreated
  interfaces/                 ICuratedVault, IVaultFactory, IAggregatorV3
  libraries/ChainlinkPriceLib read + validate + decimal-convert
test/
  mocks/                      MockERC20, MockAggregatorV3, CallTarget
  unit/                       unit tests, no network
  invariant/                  9 properties x 2,048 calls + handler sanity
  fork/                       real Base state; skips when BASE_RPC_URL is unset
script/
  Deploy.s.sol                deploy + publish deployments/<network>.json
  install-deps.sh             vendor dependencies at pinned tags
  export-abis.sh              publish flat ABIs to abis/
  verify.sh                   verify on Blockscout (no API key)
  check-deployment.sh         does the deployed code match this source?
```

## Verification

```bash
forge test                                    # 153 tests, no network
forge test --match-path "test/fork/*"         # real Base state, needs an RPC
./script/check-deployment.sh                  # deployed code == this source?
```

**Run `check-deployment.sh` before the demo and before submitting.** Source can be edited after a
deploy, and every downstream "verified against the deployed vault" claim then quietly becomes a claim
about different code — three lanes assert against this deployment and the submission points judges at
this source. It exits non-zero on a mismatch, so it works as a gate. Currently passing: the deployed
implementation's bytecode is byte-for-byte identical to the committed source, and the factory differs
only in the 40 bytes of its immutable `implementation` address.

Confirmed against a live Base mainnet fork, not mocks: 5,000 real USDC deposited → `5000e18` shares
and a share price of exactly `1000000`; the agent set a real USDC allowance to real Permit2 through
the vault; a non-agent `execute` reverted; `holdings()` returned both legs priced; redeeming half
returned 2,500 USDC.

**Proven by a real agent write, end to end through the harness** — fork tx
`0x789066d43ed0f54be903312dbc732a5c1b03ffb14dcdac0a5cd1e6f8ffa28a4b`. One atomic `executeBatch`
emitting three `Executed` events: `USDC.approve` (a *token* as target), `Permit2.approve`, then
`UniversalRouter.execute`. The vault now holds 1,750 USDC + 0.4034 WETH, and recomputing the WETH leg
independently from the live Chainlink answer gives `749880448` — exactly what `holdings()` reports, so
`totalAssets()` is `2499880448`. Agent, contract and UI agree on the portfolio's value.
