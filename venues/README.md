# `venues/` — execution adapters (Lane D)

Turns a `VenueIntent` into an `ExecutionPlan`: concrete calldata the vault
executes. Four venues, deliberately non-overlapping in what they do.

| Venue | Role | What it does |
|---|---|---|
| **`uniswap`** | taker | **Rotates what the vault holds.** "Volatility spiked → move to stables." |
| **`aqua`** | maker | **Holds a position.** Posts the vault's existing tokens as passive liquidity and earns fees. |
| **`aave`** | lender | **Earns interest** on what the vault already holds, via Aave v3. |
| **`morpho`** | lender | **Earns interest** via a curated MetaMorpho vault. Needs `ERC4626PriceFeed` registered. |

An Aqua maker is passive by construction — it cannot decide to change its
composition. That is why both venues exist and why neither is decorative.

> **This lane never touches `contracts/`.** It builds arbitrary calldata
> off-chain; the vault exposes one generic allowlisted
> `execute(target, value, data)` and never learns what a venue is.

---

## Public interface

Everything crosses the boundary through the frozen `Venue` protocol in
`packages/schema/python/curator_schema/ports.py`. **You do not need to import an
adapter class.** Resolve by the key named in `Mandate.permitted_venues`:

```python
from venues import get_venue

venue = get_venue("uniswap")          # or "aqua"
plan  = await venue.plan(intent, vault_state)   # -> ExecutionPlan
```

| Function | Signature | Notes |
|---|---|---|
| `get_venue` | `(key: str, *, cached: bool = True) -> Venue` | Raises `UnknownVenueError` for an unregistered key. Cached by default so one connection pool is reused across ticks. |
| `VENUES` | `tuple[str, ...]` | `("uniswap", "aqua", "aave", "morpho")`. Offer these in the genesis UI; validate mandates against them. |
| `Venue.plan` | `async (intent: VenueIntent, vault: VaultState) -> ExecutionPlan` | The only method the harness calls. |
| `Venue.key` | `str` | Registry key. |
| `Venue.aclose` | `async () -> None` | Closes the HTTP/RPC client. Call at shutdown. |

### What each venue can do — `manifest()`

**Never hardcode a venue list.** In Wave 1 genesis carried a literal pair, and the
fully-built Aave venue could not be granted in a mandate for an entire wave —
invisible because the only list of venues lived in someone else's file. A test
now fails if the registry and the manifest diverge.

```python
from venues import manifest

for row in manifest():          # plain JSON, safe on every render
    row["key"], row["role"], row["custody"], row["available"]
```

| Field | Meaning |
|---|---|
| `key` · `role` | `uniswap`/taker · `aqua`/maker · `aave`,`morpho`/lender |
| `summary` | One line for the UI |
| `intents` | The `VenueIntent` kinds it serves — a mandate naming it cannot produce trades the harness can only reject |
| `tokens` | Symbols, all resolvable by `resolve_token` |
| **`custody`** | **`virtual` · `claim` · `rotational` — see below** |
| `custody_note` | The sentence to render next to it |
| `requires` | Env vars needed |
| `available` · `unavailable_reason` | Actionable, never a status word |
| `contracts` | What must be on the vault's `execute()` allowlist |

**`custody` is the field that prevents a misreading**, and the three values are
not interchangeable:

- **`virtual`** (Aqua) — tokens *never leave the vault*. This **is** the Pattern 1
  claim.
- **`claim`** (Aave) — the underlying really does move; the vault holds a receipt
  token and must be able to value it.
- **`rotational`** (Uniswap) — no position is held at all.

Flatten those into "the vault has a position" and a reader concludes
`totalAssets()` is broken when it is exactly right.

**Unavailable venues are included, not filtered.** Rendering *"Aave is here but
this deployment cannot value the aToken"* beats silence — silence is how the
venue went missing in the first place.

`manifest()` and `capabilities()` **perform no network I/O** (asserted by a
test); they read configuration only, because genesis and the UI call them on
every render. `probe(key)` is the opt-in live form for preflight.

### Adding a fourth venue — ask these two questions first

Both were learned expensively, and both are answerable from deployed bytecode in
about ten minutes. Answer them **before** writing an adapter.

**1. Can a keyless contract act here?** The vault holds no private key and
cannot produce an EIP-712 signature. This has decided three venues:

| Venue | What it wanted | Resolution |
|---|---|---|
| Uniswap | an EIP-712 `PermitSingle` | Permit2's signature-**free** `approve` |
| Aqua | a signed maker order | `useAquaInsteadOfSignature = true` |
| Limitless (prediction markets) | an EIP-712 CLOB order | **none** — ERC-1271 is the only door and `CuratedVault` does not implement it. Not built. |

**2. What does the vault receive, and can `totalAssets()` value it?** The vault
values tokens through `priceFeed(address)` — one Chainlink feed per token. So a
venue must hand back either the base asset or a token with a feed.

| Venue | Receives | Valuable? |
|---|---|---|
| Aave | `aBasUSDC` / `aBasWETH` | ✅ a 1:1 **rebasing** claim, so the *underlying's* feed is correct for it |
| Morpho Blue | **nothing** — not an ERC-20, positions live in `position(bytes32,address)` | ❌ `totalAssets()` would fall by the amount supplied. Not usable. |
| MetaMorpho | ERC-4626 shares | ✅ **via `ERC4626PriceFeed`** — see below |

Aave's 1:1 rebasing property was doing far more work than it appeared to.

**A missing feed is not a dead end.** `priceFeed(token)` needs something that
answers `IAggregatorV3` — not necessarily a Chainlink-operated feed. So
`aqua/solidity/src/ERC4626PriceFeed.sol` composes
`convertToAssets(1 share) × underlying USD price` and *is* a feed, with no change
to `contracts/`. Registered with `VaultFactory.setDefaultValuation`, it makes any
ERC-4626 yield token valuable.

Two things it gets right that a reimplementation would likely not:

- **Timestamps pass through from the underlying feed.** `convertToAssets` is
  always current, so reporting `block.timestamp` would make the feed *always
  look fresh* and silently defeat the vault's staleness check — on the half that
  can actually go stale, the USD price.
- **It cannot detect a mismatched asset feed** (ETH/USD and USDC/USD are both
  8-decimal aggregators). `expand-universe.sh` validating `description()` is the
  check that catches that, which is why `description()` is implemented properly.

Measured on Base: valuing a MetaMorpho share as plain USDC understates the
position by **760 bps**, and worsens every block.

### Prediction markets — surveyed, none usable

Recorded so the search is not repeated. Three exist on Base and the blocker
differs:

| Platform | Model | Why not |
|---|---|---|
| **Limitless** | CLOB, EIP-712 orders | Real liquidity (454 markets), but the vault cannot sign. Accepts ERC-1271 — `CuratedVault` does not implement it. |
| **Azuro** | virtual AMM | Not deployed on Base. |
| **PredictBase** | LMSR **AMM** | Contract-callable, so it *passes* question 1 — but market volumes run $0–$110. The vault would be the market. |

The venue with liquidity cannot be signed for; the venue that can be called has
no liquidity. Prediction-market **odds** are still consumed as read-only facts
by the data layer, which needs none of this.

### Verifying an Aqua position — `assert_position_fillable`

**Neither a successful `ship()` nor a non-zero `safeBalances()` proves a
position can be filled.** A ship with no approvals produces perfect balances, a
valid hash, no error and a successful transaction — and every fill against it
reverts. Checking balances alone therefore *passes on a dead position*, which is
worse than no check (cross-lane requests 17 and 39).

The observable that decides it is the **ERC-20 allowance from the vault to
Aqua**, because Aqua pulls against that allowance when a taker fills.

```python
from venues.aqua import assert_position_fillable
from venues.rpc import RpcClient

async with RpcClient(rpc_url) as rpc:
    health = await assert_position_fillable(       # raises with a diagnosis
        rpc, maker=vault_address, strategy_hash=hash_from_ship_receipt,
        token_a="WETH", token_b="USDC",
    )
    print(health.describe())
    # "3000000000000000000/10000000000 shipped, … approved (fillable)"
```

| | |
|---|---|
| `assert_position_fillable(...) -> PositionHealth` | **The R5 gate.** Raises unless a taker could actually be served. |
| `read_health(...) -> PositionHealth \| None` | Non-raising form: balances **and** allowances. |
| `read_position(...) -> PositionBalances \| None` | Balances only — *liveness*, not fillability. `None` means docked or never shipped; Aqua **reverts** rather than returning zeros, and that revert is an answer, not an error. |
| `read_allowance(...) -> int` | The vault→Aqua allowance for one token. |
| `assert_position_live(...)` | Deprecated alias — now performs the full check, so old callers are strengthened rather than broken. |

Four states that look alike from outside and are not:

| State | `read_position` | `fillable` | `dead` | Cause |
|---|---|---|---|---|
| never shipped / docked | `None` | — | — | wrong hash, or `dock()` already called |
| shipped, empty | `live is False` | ✗ | ✗ | shipped with zero amounts |
| **shipped, unapproved** | **looks perfect** | ✗ | **✓** | **approval steps dropped or reordered** |
| shipped, approved | ✓ | ✓ | ✗ | correct |

The third row is the dangerous one: it is indistinguishable from success on
every observable except the allowance.

Adapters are constructed lazily, so a mandate that never names Uniswap does not
require `UNISWAP_API_KEY` to be present.

### Intent → venue routing

| Intent | Venue | Result |
|---|---|---|
| `SwapIntent` | `uniswap` | 3 steps: ERC-20 approve → Permit2 approve → router execute |
| `AquaShipIntent` | `aqua` | 3 steps: approve token A → approve token B → `Aqua.ship()` |
| `AquaDockIntent` | `aqua` | 1 step: `Aqua.dock()` |
| `SupplyIntent` | `morpho` | 2 steps: approve vault → `deposit(assets, vault)` into MetaMorpho |
| `WithdrawIntent` | `morpho` | 1 step: `withdraw(assets,…)`, or `redeem(shares,…)` for a full exit |
| `SupplyIntent` | `aave` | 2 steps: ERC-20 approve pool → `Pool.supply(asset, amount, vault, 0)` |
| `WithdrawIntent` | `aave` | 1 step: `Pool.withdraw(asset, amount, vault)` |

Routing an intent to the wrong adapter raises `UnsupportedIntentError` rather
than returning an empty plan — a wiring bug should be loud.

### The three venues do genuinely different jobs

**Uniswap rotates what the vault holds. Aqua earns fees on what it already
holds. Aave earns interest on what it already holds.** Only the first changes
the vault's exposure, which is why the harness's target-closing rule applies to
swaps and to nothing else — a supply that leaves every weight untouched is not a
failed rebalance.

Aave was added in Wave 1 to close a measured gap: the `aave` data source
contributed **204 facts about lending yields** across the first 36 ticks, and no
intent type could act on any of them. The agent read *"Aave pays 3.5% on USDC"*
and its only possible response was a Uniswap swap.

### Two things about lending that will bite if you skip them

**`onBehalfOf` is always the vault.** Aave credits the aToken to that address.
Anything else hands the position to a party that is not the custodian, on a call
that succeeds — no revert, no log, nothing to notice.

**A vault that cannot value the aToken must not supply.** `totalAssets()` counts
the base asset plus *registered* valued tokens, so supplying into a vault that
does not know `aBasUSDC` makes its reported worth fall by exactly the amount
supplied. Every depositor's share price drops and nothing errors.

`AaveVenue` refuses at plan time when the aToken is absent from the deployment
manifest's allowlist. Per-vault valuations are **immutable after `initialize`**,
so this is a property of when a vault was created:

```sh
./scripts/expand-universe.sh   # registers aBasUSDC → USDC/USD, aBasWETH → ETH/USD
                               # then create a NEW vault; existing ones cannot lend
```

An aToken is a 1:1 rebasing claim, so it is correctly valued by the
**underlying's** Chainlink feed — no new contract and no pegged-oracle shim.
Both aToken addresses were confirmed two ways on the fork:
`UNDERLYING_ASSET_ADDRESS()` and `Pool.getReserveData(asset)[8]`.

Downstream, `Holding.represents` carries the fold: `aBasUSDC` represents `USDC`,
so allocation weights, mandate targets and the allocation chart all treat a
supplied balance as the underlying exposure it is. Without it a mandate allowing
`["USDC","WETH"]` sees a vault holding 50% of an asset it never permitted.

---

## Data shapes

**Input.** `VenueIntent` and `VaultState` exactly as defined in
`packages/schema`. Two things this lane relies on you for:

- **`SwapIntent.pct_of_holdings` is resolved against `vault.holdings`**, never
  against a model-supplied balance. Populate `holdings` or percentage-based
  swaps raise `VenueError`. (`amount_in` is used verbatim when set and wins over
  the percentage.)
- **`AquaDockIntent` needs `vault.aqua_strategies[].tokens`.** `dock()` takes a
  token list that the intent does not carry, so the harness must record the
  tokens at `ship()` time. Without it, docking raises rather than guessing.

Tokens may be given as **symbols** (`"USDC"`, `"WETH"`, `"ETH"`) or as
`0x` addresses. Symbols are what a model reliably produces; an unresolvable one
raises `UnknownTokenError` rather than silently routing to the wrong token.

**Output.** `ExecutionPlan`, schema-valid against
`packages/schema/execution-plan.schema.json` (asserted in the test suite, not
just against the pydantic mirror):

```python
ExecutionPlan(
  venue="uniswap",
  steps=[ExecutionStep(target="0x…", value="0", calldata="0x…", why="…"), …],
  expected_effect="swap 1,000 USDC for ~0.31 WETH",
  expected_slippage_bps=250,
  quote_expires_at=datetime(...),   # Uniswap only
)
```

Guarantees you can rely on:

1. **Steps are ordered, and the order is not optional.** Approvals always
   precede the call that needs them. Execute in order — `executeBatch` is ideal
   since it applies the plan atomically. For Uniswap a missing approval reverts.
   **For Aqua it does not revert — it silently produces a dead position** (see
   Assumptions below); do not "optimise" approval steps away.
2. **Every `target` is checked against the agreed allowlist** before the plan is
   returned (`PlanValidationError` otherwise), so an unknown target fails here
   with a message naming the seam rather than as an opaque on-chain revert.
3. **`value` is always a decimal string** (`"0"`), never hex — the Uniswap API
   returns `"0x00"` and it is normalised at this boundary.
4. **`expected_slippage_bps` is in basis points.** The Uniswap API speaks
   percent (`2.5` = 2.5%); converted here. `None` means "unknown" — never `0`,
   because zero would wrongly pass a strict mandate ceiling. Aqua reports `0`
   legitimately: a maker posts liquidity, it does not cross a spread.
5. **`quote_expires_at` is set whenever the plan embeds a router quote.** Do not
   submit past it. Uniswap returns no expiry, so a conservative 45s TTL is
   imposed locally (Base has 2s blocks; a minute-old route is ~30 blocks stale).

---

## Errors

All inherit `VenueError`. Catch that to record a failed `AgentAction` and keep
the decision loop alive.

| Exception | Meaning |
|---|---|
| `NoRouteError` | No route for this trade. **An ordinary market condition, not a bug** — record and move on. |
| `VenueAPIError` | Upstream HTTP failure. Carries `.status`, `.code`, `.detail`. |
| `UnsupportedIntentError` | Wrong adapter for this intent kind. A wiring bug. |
| `PlanValidationError` | The plan would revert (target off-allowlist, missing swap data). |
| `ProgramBuilderUnavailableError` | SwapVM builder unreachable and no deployed address configured. |
| `UnknownTokenError` | A symbol no adapter can resolve. |
| `RpcError` | JSON-RPC failure. |

---

## Dependencies

| | |
|---|---|
| **`UNISWAP_API_KEY`** | Required for the `uniswap` venue only. `uniswap_key` also accepted (the pre-Wave-0 name). |
| **`ANVIL_RPC_URL` / `BASE_RPC_URL`** | Required for the `aqua` venue. Needs `eth_call` **state-override** support. **Verified: the public `https://mainnet.base.org` supports it**, as do anvil and Alchemy — so this venue needs no archive endpoint and no deployment. |
| `DEPLOYMENTS_FILE` | Optional. Points the allowlist reader at a manifest other than `deployments/base-fork.json`. |
| **`UNISWAP_SLIPPAGE_BPS`** | **Set this to the mandate's `max_slippage_bps`** (50 for the golden mandate). See below — without it every Uniswap plan is rejected. |

### `UNISWAP_SLIPPAGE_BPS` — set it, or the agent never trades

Unset, the Uniswap API applies its own default tolerance of **250 bps**, which
this lane faithfully reports as `expected_slippage_bps`. The harness then
rejects the plan for exceeding a tighter mandate ceiling. The symptom is an
agent that reasons perfectly over live data and then refuses every trade — which
reads as a model problem and is actually one environment variable.

Set it and the API returns a quote at *that* tolerance, so the number the
harness checks equals the bound the mandate imposes, by construction:

```sh
UNISWAP_SLIPPAGE_BPS=50      # matches the golden mandate
```

Requesting the bound is also the honest form: it is baked into the swap
calldata's `minimumAmount`, so the agent tells Uniswap the constraint it is
actually under rather than accepting a looser one and checking afterwards.

**Tolerance is not impact.** `expected_slippage_bps` is the *bound* — the most
the trade can lose. `expected_effect` additionally reports the API's estimated
**price impact**, which is typically far smaller (5 bps against a 50 bps bound
on a 1,000 USDC trade). The harness checks the bound, because a ceiling must be
compared against a worst case; the feed shows both.
| `AQUA_PROGRAM_BUILDER_ADDRESS` | Optional. Set it to use a deployed builder instead of the state-override path — needed only on endpoints without override support. |
| Python | `eth-abi`, `eth-utils`, `httpx`, `pydantic` (root `venues` extra: `uv sync --all-extras`) |
| Foundry | **Not required to use this lane.** Only to regenerate `aqua/program_builder.json`. |

This lane depends on **no other lane's code** — only on `packages/schema`.

---

## Usage example

```python
import asyncio
from curator_schema.models import SwapIntent, AquaShipIntent, VaultState, Holding
from venues import get_venue

vault = VaultState(
    address="0xYourVault…", asset=USDC, asset_decimals=6,
    total_assets="10000000000", total_supply="10000000000",
    holdings=[Holding(token=USDC, symbol="USDC", balance="10000000000", decimals=6)],
)

async def main():
    # Taker: rotate 30% of USDC holdings into WETH.
    uniswap = get_venue("uniswap")
    swap_plan = await uniswap.plan(
        SwapIntent(token_in="USDC", token_out="WETH", pct_of_holdings=0.30), vault
    )

    # Maker: post what the vault holds as a 0.30% constant-product position.
    aqua = get_venue("aqua")
    ship_plan = await aqua.plan(
        AquaShipIntent(tokens=["USDC", "WETH"],
                       amounts=["1000000000", "300000000000000000"]), vault
    )

    for step in swap_plan.steps:      # execute in order via the vault
        print(step.why, step.target, step.calldata[:12])

asyncio.run(main())
```

---

## Assumptions & invariants

**The vault is sole custodian, and it cannot sign anything.** These two facts
shaped every design decision here.

- **The vault is a contract with no private key.** It therefore cannot produce
  the EIP-712 signatures both venues nominally expect. Uniswap plans use
  Permit2's signature-free `approve(token, spender, amount, expiration)`; Aqua
  strategies set `useAquaInsteadOfSignature = true`, which makes the vault's
  Aqua balances stand in for a signature. In Aqua's case that is also the mode
  1inch scores higher — the constraint and the incentive point the same way.
- **Capital never leaves the vault.** Aqua is a *registry*: it tracks
  `balances[maker][app][strategyHash][token]` while tokens stay in the maker's
  wallet. The vault is the maker, so shipping and docking move no capital,
  `totalAssets()` keeps working off plain `balanceOf`, and Pattern 1 holds. A
  conventional AMM LP position could not do this — which is exactly why Aqua is
  load-bearing rather than cosmetic.
- **Approvals are re-emitted on every plan** rather than checked first. A
  redundant approve costs gas and always succeeds.
- **An Aqua ship with no approvals does not fail — it produces a dead
  position.** Verified on a fork against the real contract: `ship()` records
  full virtual balances and returns a valid strategy hash even with zero
  allowance, because shipping moves nothing and the allowance is only consumed
  when a taker fills. The position then looks healthy in every observable way
  and is never fillable. This is the one place in this lane where dropping a
  step causes silent failure rather than a revert, so the approval steps are
  load-bearing and must not be optimised away.
- **Aqua approvals are for the exact shipped amount**, not `type(uint256).max`
  (which 1inch's own tests use). A vault holds other people's money.
- **The Aqua strategy salt is deterministic**, derived from vault state. A
  random salt would make a retried tick open a *second* position instead of
  rebuilding the same one.
- **The strategy sorts its own tokens** (`MakerTraitsLib` requires
  `tokenA < tokenB`; on Base **WETH `0x4200…` sorts below USDC `0x8335…`**,
  which reads backwards). The adapter re-pairs amounts to the strategy's order,
  so callers never need to know the rule.

---

## Vault allowlist — read, never hardcoded

`execute()` reverts unless the target is allowlisted, so every plan is checked
against the allowlist *before* it is returned.

**The list is read from `deployments/base-fork.json` → `executeAllowlist.targets`**
(Lane A's published manifest), not compiled into this lane — at their request,
and because the vault's `allowedTargets()` is **mutable**: a guardian can widen
or narrow it after deploy. A constant here would drift, and the symptom would be
an on-chain revert instead of a clear failure with a message naming the seam.

- Point at a different manifest with `DEPLOYMENTS_FILE=/path/to/manifest.json`
  (e.g. a mainnet deployment).
- Falls back to a static list when no manifest exists, so a fresh clone still
  works. A test reconciles the two and fails if this lane could emit a target
  the deployed vault would reject.

Lane A's deployed list — confirmed identical to our fallback:

| Address | What | Why |
|---|---|---|
| `0x6fF5693b99212Da76ad316178A184AB56D299b43` | **Uniswap router (Base)** | What `POST /swap` actually returns as `to`. **Not** the `0x2626664c…e481` in the golden fixture — allowlisting only that address reverts every swap. |
| `0x000000000022D473030F116dDEE9F6B43aC78BA3` | Permit2 | Step 2 of every swap. |
| `0x499943E74FB0cE105688beeE8Ef2ABec5D936d31` | Aqua | `ship()` / `dock()`. |
| `0x8fDD04Dbf6111437B44bbca99C28882434e0958f` | SwapVM | Named as the Aqua `app`; not called directly. |
| `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913` | USDC | **Token approvals target the token contract.** |
| `0x4200000000000000000000000000000000000006` | WETH | Same. |

The last two matter: the golden fixture's step 1 is `USDC.approve(Permit2, …)`,
targeting a *token*, not a venue. Filed as cross-lane requests 7 and 8. If Lane
A prefers approvals through `approveVenue(token, spender, amount)` instead, say
so — it is a one-line change in `uniswap/plan.py` and `aqua/calldata.py`.

---

## Layout

```
venues/
  registry.py        get_venue() — resolve a mandate's venue key
  addresses.py       verified Base addresses + the expected allowlist
  config.py          env loading
  abi.py             calldata encoding (selector + args)
  rpc.py             eth_call, incl. state overrides
  errors.py          the exception surface above
  uniswap/
    client.py        HTTP only — knows nothing about our schema
    plan.py          responses -> ExecutionPlan — no network, fully testable offline
    venue.py         UniswapVenue
  aqua/
    program.py       eth_call into the Solidity builder
    calldata.py      ship() / dock() encoding
    venue.py         AquaVenue
    program_builder.json   committed artifact — no Foundry needed to consume
    solidity/        standalone Foundry project (NOT contracts/)
      src/SwapVMProgramBuilder.sol
      build.sh       recompile + republish the artifact
  tests/             37 tests; fixtures/ holds recorded API responses
```

**Why the SwapVM program is built in Solidity.** Programs are packed bytecode
(`opcode ‖ argLength ‖ args`). Reimplementing that in Python would mean a second,
unverified copy of 1inch's instruction format, and any drift yields a program
that encodes cleanly and behaves wrongly with real money behind it. The builder
inherits 1inch's `AquaOpcodes` and passes **function pointers** to their
`ProgramBuilder`, which resolves each to its index in their own instruction
table at compile time — so no opcode number appears in our source at all.

> ### ⚠️ Verification status of the Aqua program
>
> **Verified against the real deployed contracts on a Base fork:** `ship()`,
> `dock()`, virtual balances, the zero-token-movement custody invariant, and
> contract-maker support (`useAquaInsteadOfSignature`). These are solid.
>
> **Not yet verified: that the strategy prices correctly when executed.**
> `Aqua.ship()` stores the strategy as opaque bytes and never runs it — the
> first execution is a taker fill. The deployed SwapVM's instruction table does
> not match any published swap-vm source we can find: it reads index 20 as
> `Decay` where v1.0.1 puts `Salt`, and no probed index produced a real
> constant-product quote. Details, evidence and the next step are in the header
> of `aqua/solidity/test/AquaTakerFillFork.t.sol`, which is committed but
> skipped rather than passing on a claim we cannot support.
>
> `@1inch/swap-vm` is **pinned to v1.0.1** because the default branch encodes
> instructions completely differently (`XYCSwap` = `0x50` there, `17` in the
> deployed positional scheme). Do not unpin without re-checking the deployment.

---

## Running the tests

```sh
uv sync --all-extras
uv run pytest venues/tests            # offline; green with no creds
uv run pytest venues/tests -m live    # real Uniswap API + a local node
```

Live tests skip themselves when the credential or node is absent, so a fresh
clone is always green. For the Aqua live tests, any bare anvil works — the
builder is pure, so no fork and no archive node is needed:

```sh
wsl -d Ubuntu-24.04 -- anvil --host 0.0.0.0 --port 8547
```

Solidity tests (needs Foundry, in `wsl -d Ubuntu-24.04`):

```sh
cd venues/aqua/solidity
forge test                                   # 13 encoding tests, offline
forge test --fork-url $BASE_RPC_URL          # + 5 against REAL deployed Aqua
sh build.sh                                  # recompile + republish the artifact
```

**The fork suite is the one that matters for the 1inch track.** It executes our
`ship()` and `dock()` against Aqua at its real Base address, and asserts:

- the strategy is accepted by the live registry, and the `strategyHash` it
  returns equals the one we compute off-chain (so a later `dock()` targets the
  right position);
- **`ship()` moves zero tokens** — the Pattern 1 custody invariant, verified
  against the actual contract rather than against our description of it;
- virtual balances match the shipped amounts, so the position is genuinely
  fillable;
- `dock()` is equally capital-neutral.

It skips itself without a fork URL, so the default suite stays green offline.
The public `https://mainnet.base.org` is sufficient here — no archive node
needed for a handful of calls.

> `pnpm install` here **must** use `--ignore-workspace`. Without it pnpm walks
> up, finds the repo-root workspace, and installs the web app's dependencies
> into this directory while ignoring its `package.json`. There is no `.npmrc`
> key for this. `build.sh` already passes the flag.
