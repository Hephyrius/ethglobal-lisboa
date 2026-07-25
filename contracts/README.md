# `contracts/` — Lane A · the vault, the factory, and the agent's authorization boundary

ERC-4626 vaults curated by an autonomous agent. This document is the integration surface: everything
another lane needs is here, and **nothing else in this directory should have to be read.**

- **Owner:** Lane A. Nobody else edits `contracts/`. Lane D's Solidity lives in `venues/aqua/solidity/`.
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
forge test                        # 69 tests, no network required
```

Fork deployment (from repo root, two terminals):

```bash
./scripts/anvil-fork.sh                                    # terminal 1 — needs BASE_RPC_URL
cd contracts && forge script script/Deploy.s.sol \
  --rpc-url http://127.0.0.1:8540 --broadcast              # terminal 2
```

The deploy writes [`deployments/base-fork.json`](../deployments/base-fork.json). **Read addresses
from that file. Never hardcode them.**

> **No `BASE_RPC_URL`?** `forge test` is unaffected — the unit suite is entirely mock-based and needs
> no network. Only `test/fork/` and the fork deploy need one, and the fork tests skip themselves
> cleanly when the variable is absent.

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
```

The guardian's only power. See [Invariants](#assumptions--invariants).

### Views

```solidity
function agent()          external view returns (address);
function guardian()       external view returns (address);
function mandateHash()    external view returns (bytes32);
function priceMaxAge()    external view returns (uint256);

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
                      address agent; address guardian; bytes32 mandateHash; }

event VaultCreated(address indexed vault, address indexed asset, address indexed agent, bytes32 mandateHash);
```

Owner-only: `setDefaultTarget`, `setDefaultValuation`, `setDefaultPriceMaxAge`.
Views: `implementation()`, `vaults()`, `vaultCount()`, `isVault()`, `defaultTargets()`,
`defaultValuations()`, `defaultPriceMaxAge()`.

### Events

| Event | Use |
|---|---|
| `VaultCreated(vault, asset, agent, mandateHash)` | index new vaults |
| `VaultInitialized(asset, agent, guardian, mandateHash)` | genesis record |
| `Executed(target indexed, selector indexed, value)` | decision feed — filter by call type without decoding calldata |
| `VenueApproved(token, spender, amount)` | approval trail |
| `TargetAllowed(target, allowed)` | allowlist changes |
| ERC-4626 `Deposit` / `Withdraw`, ERC-20 `Transfer` | TVL and share movements |

### Errors

`TargetNotAllowed(address)` · `SpenderNotAllowed(address)` · `EmptyBatch()` · `ZeroAddress()` ·
`DuplicateValuation(address)` · `RolesAreFrozen()` ·
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
| `paused` | always `false` — there is no pause at MVP |
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

**There is no human override, no pause, and no emergency withdrawal.** Deliberate
([initiate_plan.md](../plans/initiate_plan.md) §2). What *is* enforced on-chain is blast radius: the
agent may only reach allowlisted contracts.

**The allowlist bounds *which contracts* the agent may call, not what it may do there.** Within an
allowlisted target the agent has full latitude — consistent with a trust model that already grants it
the key. It is a blast-radius limiter, not a mandate enforcer.

**The guardian can only edit the allowlist.** It cannot move funds, replace the agent, or touch
valuation. Widening the list grants it nothing it could exploit alone, because only `AGENT_ROLE` can
call `execute`. Accepted residual risk, stated rather than hidden: a guardian *narrowing* the list can
grief a rebalance. That is liveness, not custody.

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
  unit/                       69 tests, no network
  fork/                       real Base state; skips when BASE_RPC_URL is unset
script/
  Deploy.s.sol                deploy + publish deployments/<network>.json
  install-deps.sh             vendor dependencies at pinned tags
  export-abis.sh              publish flat ABIs to abis/
```

## Verification

```bash
forge test                                    # 69 unit tests, no network
forge test --match-path "test/fork/*"         # real Base state, needs BASE_RPC_URL
```

Confirmed against a live Base mainnet fork, not mocks: 5,000 real USDC deposited → `5000e18` shares
and a share price of exactly `1000000`; the agent set a real USDC allowance to real Permit2 through
the vault; a non-agent `execute` reverted; `holdings()` returned both legs priced; redeeming half
returned 2,500 USDC.
