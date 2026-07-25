# Lane A — Contracts Plan

**Owner:** Lane A instance · **Claimed:** 2026-07-25 01:35Z · **Directory:** `contracts/` (Foundry, `wsl -d Ubuntu-24.04`)

Implements [master build plan](2026-07-25-master-build-plan.md) §10 Lane A. Living document —
material changes get a `docs/build-log.md` entry.

---

## 1. What this lane is actually for

Three other lanes are stubbed until I publish. That ranks the work:

| Priority | Deliverable | Consumer | Deadline |
|---|---|---|---|
| 1 | ABIs (`contracts/abis/*.json`, `contracts/out/**`) | B (web3.py), E (viem) | **CP1 / T+4h** |
| 2 | `deployments/base-fork.json` with real addresses + confirmed allowlist | B, D, E | **CP1 / T+4h** |
| 3 | `contracts/README.md` — the integration surface | all | CP1 |
| 4 | A vault that actually works | the demo | CP2 |

So the build order is **shape-first**: get a compiling contract with the final external signatures,
export ABIs, publish, push — *then* fill in the bodies. A stubbed-but-correct ABI unblocks three
lanes; a perfect vault published at T+6h does not.

---

## 2. Design decisions

### 2.1 The `execute()` seam

```solidity
function execute(address target, uint256 value, bytes calldata data)
    external onlyRole(AGENT_ROLE) returns (bytes memory);
```

One generic surface. The vault never learns what a venue is; Lane D builds arbitrary calldata
off-chain and never opens `contracts/`. `target` must be on the vault's allowlist or it reverts.

`executeBatch(Call[] calls)` ships alongside it — an `ExecutionPlan` is a *sequence* (approve, then
swap) and per-step transactions on a fork triple the round-trips and let a plan land half-applied.
One atomic call per plan is both cheaper and safer. `execute()` stays because it is the documented
primitive and the simplest thing for Lane B to call first.

### 2.2 Who may change what — the role graph is frozen at genesis

The locked trust model ([initiate_plan §2](initiate_plan.md)) is *no human override after genesis*.
Taken literally that means no `DEFAULT_ADMIN_ROLE` holder at all, which also freezes the target
allowlist — and the Uniswap router address is still unconfirmed (cross-lane request #1). An
immutable list missing one address kills the demo.

Resolution — two fixed roles, no admin:

| Role | Granted to | Can | Cannot |
|---|---|---|---|
| `AGENT_ROLE` | the curator agent, at init | `execute`, `executeBatch`, `approveVenue` | grant/revoke any role; change the allowlist |
| `GUARDIAN_ROLE` | platform deployer, at init | `setTargetAllowed(target, bool)` — **only** | touch funds, replace the agent, change valuation |
| `DEFAULT_ADMIN_ROLE` | **nobody** (`address(0)`) | — | exists; the role graph can never change |

Why this is not a backdoor: only `AGENT_ROLE` can move value, so widening the allowlist grants the
guardian nothing it could exploit alone — it only widens what the *agent* may already choose to call.
The residual risk is a guardian *narrowing* the list to grief a rebalance (liveness, not funds).
Documented as an accepted tradeoff in the README, not hidden.

**The valuation set is genuinely immutable**, because there a guardian *could* steal: adding a bogus
price feed inflates `totalAssets()` and mints/burns shares at the wrong price. No role can change it.

### 2.3 `totalAssets()`

`asset.balanceOf(vault)` + every registered non-base token valued through its Chainlink Base feed.
Pattern 1 means capital never leaves, so `balanceOf` is the whole picture — including tokens
committed to an Aqua strategy. Per master plan §14: **do not read Aqua virtual balances**, they'd
double-count.

Two traps, both handled explicitly:

- **Stale feeds on a pinned fork.** Anvil's `block.timestamp` advances while the forked feed's
  `updatedAt` is frozen at the fork block, so any staleness check fails within minutes of starting
  the fork. `priceMaxAge` is per-vault, set at init; `0` disables the check. Fork deploys use `0`,
  mainnet uses 3600s. Loud comment at the definition and a README note — this is the kind of thing
  that eats an hour at 4am otherwise.
- **Invalid price → revert, not zero.** Valuing a held token at 0 would let someone withdraw at a
  wrong share price. Reverting `totalAssets()` blocks deposits/withdrawals, which is the safer
  failure.

Approximation accepted at MVP: **1 base-asset unit = $1** (asset is USDC). Documented; a second feed
for the asset leg is stretch.

### 2.4 Shares: `_decimalsOffset() = 12`

Gives 18-decimal shares over a 6-decimal asset — OZ's virtual-shares defense against the
first-depositor inflation attack, and it matches the magnitudes in
`packages/schema/fixtures/vault-state.json` (`total_supply` ≈ 4.99e22 against `total_assets` 5e10).
Consequence Lane B/E must know: `convertToAssets(1e18)` returns a **6-decimal** number (≈`1002506`),
not `1e18`. Spelled out in the README.

### 2.5 Clones and the factory

`VaultFactory` (OZ `Ownable` + `Clones`) holds a **mutable default config** — allowlist, valuation
set, `priceMaxAge` — which each new vault **snapshots at init and then freezes**. Mutable where it is
harmless (the template), immutable where it matters (a live vault holding money). When Lane D
confirms the router address, it goes into the factory default and the next clone has it.

Clones force `Initializable` + `initialize()`, hence `openzeppelin-contracts-upgradeable` for the
ERC-4626/ERC-20/AccessControl base (namespaced ERC-7201 storage, no constructor). The vaults are
*not* upgradeable — no proxy admin, no `upgradeTo`. Only the initializer pattern is borrowed.

---

## 3. File layout

```
contracts/
  foundry.toml            solc pin, remappings, fs_permissions for ../deployments
  remappings.txt
  .gitignore              re-includes out/ — root .gitignore's `out/` (Next.js) shadows it
  src/
    CuratedVault.sol      ERC-4626 + roles + execute surface + totalAssets
    VaultFactory.sol      Clones, default config, VaultCreated
    interfaces/
      ICuratedVault.sol   the surface B/D/E code against
      IVaultFactory.sol
      IAggregatorV3.sol   minimal Chainlink feed interface (no chainlink dep for one struct)
    libraries/
      ChainlinkPriceLib.sol   read + validate + decimal-convert. Pure, unit-testable alone.
      VenueAllowlist.sol      allowlist storage/lookup, split out of the vault
  test/
    mocks/                MockERC20, MockAggregatorV3, CallTarget (execute() probe)
    unit/                 vault, roles, execute, valuation, factory
    fork/                 real Base state — SKIPS cleanly when BASE_RPC_URL is unset
  script/
    DeployFork.s.sol      deploys, then writes ../deployments/base-fork.json
    export-abis.sh        reusable: forge inspect → contracts/abis/*.json
  abis/                   flat ABI arrays — the stable path B and E import
  README.md
```

Every file has one job (Rule 3). The allowlist and the price math live outside the vault so they can
be tested without deploying one.

---

## 4. Order of work

1. ✅ `foundryup` in Ubuntu-24.04 — forge 1.7.1
2. Scaffold + OZ deps; interfaces with **final signatures**; contracts compiling with stub bodies
3. **Export ABIs + write `deployments/base-fork.json` + README → commit → push.** CP1 satisfied early
4. Real bodies: valuation lib → allowlist → vault → factory
5. Unit tests (mocks, no network)
6. `DeployFork.s.sol`; anvil fork; real deployment; regenerate `deployments/base-fork.json`
7. Fork tests against real USDC + real Chainlink ETH/USD
8. README final pass, build-log entries, release claim

## 5. Risks

| Risk | Mitigation |
|---|---|
| No `BASE_RPC_URL` in `.env` — fork tests and the fork deploy cannot run | Unit suite is 100% mock-based and needs no network; fork tests `vm.skip(true)` when the var is unset, so `forge test` is green on a fresh macOS clone. Fork deploy is a separate step. |
| Uniswap router target unconfirmed → every Lane D plan reverts | Guardian can widen the allowlist on a live vault (§2.2); factory default covers new clones. Flagged back to Lane D in `docs/active-work.md`. |
| Root `.gitignore` has a bare `out/` for Next.js, which also ignores `contracts/out/` | `contracts/.gitignore` with `!/out/` — a deeper ignore file overrides a shallower one. Fixed inside my lane; root config untouched. |
| OZ pulled as git submodules; macOS teammate clones without `--recursive` | `git submodule update --init --recursive` documented at the top of the README and flagged in `active-work.md`. |
| Chainlink staleness fails on a pinned fork | `priceMaxAge = 0` disables it; fork deploys use 0 (§2.3). |
| `out/` bloats the repo | `build_info = false`, minimal `extra_output`. |

## 6. Definition of done — ✅ MVP complete

- [x] `forge build` clean (zero warnings on a cold build); `forge test` green with **no network
      access** — 69 unit tests pass, 7 fork tests skip cleanly
- [x] Fork tests green against real Base state — **76/76** with an RPC
- [x] `contracts/abis/*.json` + `contracts/out/**` committed and pushed
- [x] `deployments/base-fork.json` written by the deploy script from a live fork run, with the
      confirmed 7-target `executeAllowlist`
- [x] `contracts/README.md` covers purpose, interface, data shapes, deps, example, invariants
- [x] Build-log entry covering the role-graph split, the valuation asymmetry, the decimals offset,
      the vendoring decision and the three test bugs found
- [x] Cross-lane requests #1, #2, #7, #8, #11 closed; #13 and #14 filed
- [x] **Fresh-clone check passed** — `git clone` → `forge build` → `forge test` green with no
      submodule init, no dependency install and no network
- [x] Claim released in `docs/active-work.md`

### What changed from the original plan

- **`VenueAllowlist.sol` was never written.** OpenZeppelin's `EnumerableSet.AddressSet` is exactly
  that data structure, already audited. One fewer file to own.
- **`executeBatch` was added** and is now the recommended path — an `ExecutionPlan` is ordered and
  must not land half-applied.
- **Dependencies were re-vendored into `lib/oz*` with unused trees pruned**, after Lane D found that
  the original paths broke `git clone` on Windows (request #11).
- **`holdings()` was added** so the harness can fill `VaultState.holdings` in one call rather than
  N+1 round-trips.

### Known gaps, deliberately left (Stretch, not MVP)

- One base-asset unit is treated as exactly $1; the asset leg is not priced through its own feed.
- No ENS subname minting, no pause, no richer accounting.
- `aqua_strategies[]` in `VaultState` is not tracked on-chain — the harness records it at ship time.
- The vault holds no native ETH (no `receive()`); native-ETH swap legs are unsupported, use WETH.

---

## 7. Wave 2 — the adversarial pass (2026-07-25, ~10:20Z)

Per [wave 2 §4](2026-07-25-wave-2-six-lanes.md). **No new features and no contract source changed** —
the question this wave asks is whether what exists survives someone trying.

### Delivered

- **`contracts/SECURITY.md`** — nine attack vectors, each ending with the test that proves the claim.
  All 33 cited test names verified to exist, because a security document whose references do not
  resolve is worse than none.
- **`test/invariant/`** — nine properties driven by a handler that attacks the vault rather than only
  using it. Green at the deep profile: **589,824 calls, zero failures.**
- **The donation/inflation attack executed end to end** rather than asserted: both attacker and victim
  actually redeem. Victim whole; attacker down ~5,000 USDC on a ~10,000 USDC attempt.
- **`test/invariant/HandlerSanity.t.sol`** — proves each handler action does something, because every
  invariant holds trivially on a vault nothing happened to.
- 85 → **101 tests**, zero-warning cold build.

### The finding worth carrying forward

**Four bugs surfaced, and all four were in the tests, not the vault** — each one me asserting
something stronger than the property I cared about. Share-price drift is about *direction* (entry may
round the price up, never down), not magnitude; `0` cannot mean both "undefined" and "collapsed"; a
per-sequence coverage hook fails on sequence composition rather than on the code; and a `redeem`
action that only fires when the fuzzer draws the same actor twice is a silent no-op that makes the
whole exit path untested. That last fix is what surfaced the first two at all.

An invariant suite's most dangerous failure mode is **passing**, and nothing inside the properties can
detect it. That is the entire reason `HandlerSanity.t.sol` exists.

### Deliberately not mitigated, and written down

- **Sandwiching the agent's swap** — cannot be verified from this lane. The vault executes opaque
  calldata by design, so it cannot inspect a `minOut` it never parses. Owned by Lane D, tracked as
  **#60**; SECURITY.md §6 will be replaced with their answer verbatim.
- **Deposit/withdraw sandwiching around a rebalance** — the fixes each change depositor experience
  materially and need their own testing. Disclosed in SECURITY.md §7 rather than half-fixed.
