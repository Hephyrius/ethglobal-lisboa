# Lane D — Venues (`/venues`)

**Owner:** Lane D instance · **Claimed:** 2026-07-25 02:10 · **Scope:** master plan §10 Lane D MVP,
extended by Wave 1 (Aave) and Wave 2 (§7).

Lane D owns the *execution* paths and nothing else. It turns a `VenueIntent` into an
`ExecutionPlan` — concrete calldata the vault executes. It never touches `/contracts`.

> **§1–§8 below are the original MVP plan and are kept as written**, because the reasoning that
> produced the two-venue design is still the reasoning the lane runs on. **§9 records what actually
> happened after it** — two more venues, three things the plan did not anticipate, and the four
> findings that changed how the lane works. Read §9 for current state; read §1–§8 for why.

---

## 1. What this lane is responsible for

| | |
|---|---|
| **Uniswap** | Taker side. Rotates *what the vault holds* ("volatility spiked → move to stables"). Trading API `/quote` → `/swap` → calldata. |
| **1inch Aqua + SwapVM** | Maker side. *Holds* the position. Tokens never leave the vault; only virtual balances move. `ship()` / `dock()`. |

The two roles are deliberately non-overlapping — [initiate_plan.md](initiate_plan.md) §7 requires 1inch
to be structurally distinct from Uniswap or it reads as cosmetic to judges.

**Why Aqua is the only venue compatible with our locked custody decision.** Pattern 1 says the vault
is sole custodian. A normal AMM LP position transfers tokens out to a pool contract, which breaks
that invariant and corrupts `totalAssets()`. Aqua tracks
`balances[maker][app][strategyHash][token]` on-chain while the tokens **stay in the maker's wallet**.
The vault *is* the maker: `approve(aqua)` once, `ship()` a strategy, capital never moves. That is not
a convenient coincidence — it is the reason 1inch is load-bearing here rather than decorative.

---

## 2. Interfaces produced and consumed

**Produces** — the frozen `Venue` port from `packages/schema/python/curator_schema/ports.py`:

```python
class Venue(Protocol):
    key: str
    async def plan(self, intent: VenueIntent, vault: VaultState) -> ExecutionPlan: ...
```

Both adapters implement exactly this. Lane B calls `plan()` and hands the result to
`VaultClient.execute()`. Adding a third venue is a new adapter, not a refactor anywhere else.

**Consumes:** `VenueIntent` (`SwapIntent` | `AquaShipIntent` | `AquaDockIntent`), `VaultState`, and
`packages/schema/fixtures/*.json` for development. Nothing from Lanes A, B, C, or E at build time.

**Hard contract on every emitted plan** (from the port docstring, and what makes plans safe):
1. Every `step.target` is on the vault allowlist — else `execute()` reverts.
2. Approvals are ordered **before** the call that needs them.
3. `expected_slippage_bps` is populated where the venue can estimate it; the harness rejects plans
   exceeding the mandate ceiling.
4. `quote_expires_at` is set whenever the plan embeds a router quote — stale quotes must not submit.

---

## 3. File breakdown

```
venues/
  pyproject.toml          own uv project — see §6
  README.md               THE integration surface for Lane B (Rule 5)
  ports.py                re-export of the frozen Venue port + shared venue errors
  config.py               env loading (UNISWAP_API_KEY, RPC), Base addresses in one place
  addresses.py            verified Base mainnet constants — single source of truth
  uniswap/
    client.py             Trading API HTTP client: /quote, /swap. Auth, retries, errors.
    plan.py               quote+swap response  ->  ExecutionPlan (approval ordering lives here)
    venue.py              UniswapVenue implements Venue
  aqua/
    program.py            eth_call into SwapVMProgramBuilder -> program bytes
    calldata.py           ship() / dock() ABI encoding, useAquaInsteadOfSignature = true
    venue.py              AquaVenue implements Venue
    solidity/             STANDALONE Foundry project (not /contracts, never imported by Lane A)
      src/SwapVMProgramBuilder.sol    view contract using 1inch's official ProgramBuilder
      test/                            forge tests
  tests/                  schema-conformance + live-quote tests
```

One responsibility per module (Rule 3). The split that matters: `client.py` knows HTTP and nothing
about our schema; `plan.py` knows our schema and nothing about HTTP. That keeps the Uniswap API's
response shape from leaking into the frozen interface, and lets `plan.py` be tested against saved
fixtures with no network.

---

## 4. Verified findings — live API, hour 0

Recorded here because they contradict the master plan's assumptions and cost real time to discover.

| Finding | Consequence |
|---|---|
| `routingPreference` must be `BEST_PRICE` or `FASTEST`. `CLASSIC` → HTTP 400 `RequestValidationError`, despite `CLASSIC` being what the response `routing` field echoes back. | Client sends `BEST_PRICE`. Noted in `FEEDBACK.md`. |
| Swap tx `to` on Base = **`0x6fF5693b99212Da76ad316178A184AB56D299b43`**, not the `0x2626664c…e481` UniversalRouter in the golden fixture. Same address is the Permit2 `spender`. | Allowlist correction filed as request 7. |
| `/swap` returns 200 with **no signature** when the flow is allowance-based Permit2. | The vault is a contract and cannot easily produce an EIP-712 signature — so the contract-friendly path (`Permit2.approve`) is viable and no ERC-1271 work is needed. This de-risks the whole Uniswap path. |
| Approval steps target the **token** contract, per the golden fixture. | Filed as request 8 — blocking for CP2 unless Lane A allowlists tokens. |

Live quote proving the key works: 1 USDC → 0.000537935691469946 WETH, v3 0.01% pool, priceImpact 0.01.

---

## 5. Build order

1. **Hour 0 (done).** Uniswap key verified live; `.env` confirmed gitignored *before* touching it.
2. Package skeleton + `addresses.py` + config.
3. `uniswap/` — client, plan builder, venue. Test against saved fixtures **and** one live call.
4. `aqua/solidity/` — Foundry project, `SwapVMProgramBuilder`, `forge build` green.
5. `aqua/` Python — program bytes via `eth_call`, `ship()`/`dock()` calldata.
6. README + FEEDBACK.md + build-log entries. (~20% of lane time, budgeted, not trailing.)

Uniswap goes first: it is a $10K track gated on a key that is already working, and it has no
dependency on Foundry being installed. Aqua second — higher risk, needs the WSL toolchain.

---

## 6. Risks and how each is handled

| Risk | Handling |
|---|---|
| **Root `pyproject.toml` was broken** — `curator-schema` declared both as workspace member and path source, so `uv sync` failed for Lanes B, C and D. | Lane B fixed and pushed it (request 4). `/venues` additionally carries its own `pyproject.toml` so this lane's dependency set is explicit and installable on its own — that is also what makes the macOS handoff a single `uv sync`. |
| **SwapVM program encoding is the single hardest thing in this lane.** | Do not reimplement 1inch's encoding in Python. Build programs in Solidity with their *official* `ProgramBuilder`, read via `eth_call`, treat the result as opaque bytes. Master plan §14 already names this; it is the whole reason `aqua/solidity/` exists. |
| **`useAquaInsteadOfSignature = true` is what 1inch scores higher.** Easy to leave false and silently lose points. | Set explicitly, asserted in a test, documented in the README. |
| Router quotes go stale between plan and execution. | `quote_expires_at` populated on every Uniswap plan; the harness enforces it. |
| Foundry not installed / wrong WSL distro. | `wsl -d Ubuntu-24.04` only (glibc 2.39). Uniswap path has zero Foundry dependency, so a Foundry failure cannot take the whole lane down. |
| Live API down at demo time. | Saved golden responses in `tests/` let `plan.py` be exercised offline. The *demo path* still uses live calls — fixtures are development-only (master plan §9.3). |
| Lane A's allowlist disagrees with my targets → every plan reverts. | Requests 7 and 8 filed at hour 0 rather than discovered at CP2. Default to the golden-fixture shape until Lane A rules. |

---

## 7. Definition of done for this lane

- [x] `POST /quote` returns a live route; `UniswapVenue.plan()` emits a schema-valid `ExecutionPlan`
- [x] `SwapVMProgramBuilder` `eth_call` returns non-empty program bytes
- [x] `AquaVenue.plan()` emits a schema-valid `ExecutionPlan` with `useAquaInsteadOfSignature = true`
- [x] Both validate against `packages/schema/execution-plan.schema.json`, not just the pydantic mirror
- [x] `venues/README.md` complete enough that Lane B integrates without reading any source
      *(confirmed: Lane B bound to `venues:get_venue` with zero code change on either side)*
- [x] `FEEDBACK.md` written — **the Developer Feedback Form still needs a human to submit it** (§9)
- [x] Build-log entries for every non-trivial decision
- [x] **Beyond the stated DoD:** `ship()`/`dock()` executed against the **real deployed Aqua** on a
      Base fork, including the zero-token-movement custody assertion
- [x] Fresh-clone handoff verified — the lane works with no Foundry, no `node_modules`, no credentials
- [ ] Claim released in `docs/active-work.md` *(held open until the allowlist requests 7/8 are answered)*

**MVP complete.** 54 Python tests + 18 Foundry tests green.

---

## 8. What is left, and who owns it

| Item | Owner | Note |
|---|---|---|
| **Uniswap Developer Feedback Form** | **a human** | `FEEDBACK.md` is written and ready to paste. The form is a browser submission and gates the $10K track — an agent cannot do it. |
| Allowlist requests 7 & 8 | Lane A | The only open risk here. If the deployed allowlist disagrees with `addresses.EXPECTED_ALLOWLIST`, plans revert on-chain instead of failing in this lane where the message names the seam. |
| `BASE_RPC_URL` | Wave 0 / whoever | Not blocking Lane D — the fork tests run on public Base and the program builder needs no chain state. Still blocking the *shared* fork every other lane sits on. |
| Mainnet run | refine window | The fork test is the rehearsal; the same calls against real Base produce the BaseScan links for the submission. |

**Stretch (untouched, per the MVP-only rule):** wider SwapVM instruction coverage — `PeggedSwap` for
stable pairs, `XYCConcentrate` for concentrated ranges, Dutch-auction/TWAP programs. All are new
`Opcode` compositions in `buildXYCProgram`'s shape; the adapter, port and plan builder do not change,
which is the payoff from putting the encoding in Solidity behind one entry point.

---

## 9. What actually happened — Wave 1 and Wave 2

Appended rather than rewritten (Rule 2: plans are living documents). The MVP plan above is sound and
still describes the spine of the lane. Four things changed materially.

### 9.1 Two venues became four

| Venue | Role | Custody | Added |
|---|---|---|---|
| `uniswap` | taker — rotates what the vault holds | `rotational` | MVP |
| `aqua` | maker — earns fees on what it holds | **`virtual`** — tokens never leave | MVP |
| `aave` | lender — earns interest | `claim` (1:1 **rebasing** aToken) | Wave 1 |
| `morpho` | lender — curated MetaMorpho | `claim` (**appreciating** 4626 share) | Wave 2 |

Aave closed a measured gap: the `aave` data source had contributed 204 facts about lending yields
across 36 ticks and **no intent type could act on any of them**. Morpho proved
`SupplyIntent`/`WithdrawIntent` were genuinely venue-agnostic — neither shape changed.

The `custody` distinction turned out to matter more than expected and is now a first-class field in
the manifest. Flatten those three values into "the vault has a position" and a reader concludes
`totalAssets()` is broken when it is exactly right.

### 9.2 Two questions now gate every new venue

Both were learned expensively; both are answerable from deployed bytecode in about ten minutes.

1. **Can a keyless contract act here?** The vault has no private key. Uniswap needed Permit2's
   signature-free `approve`; Aqua needed `useAquaInsteadOfSignature = true`; **Limitless had no
   equivalent and was not built.**
2. **What does the vault receive, and can `totalAssets()` value it?** Aave's aToken rebases 1:1, so
   the underlying's Chainlink feed is *correct* for it — that property was doing far more work than
   it looked like. Morpho Blue returns **nothing** (not an ERC-20); MetaMorpho returns an
   appreciating 4626 share with no feed.

Asking these first is the single biggest efficiency change in the lane. The prediction-market gate
cost most of its timebox because question 1 was asked third.

### 9.3 A missing price feed is not a dead end

The most useful thing learned this wave. `CuratedVault.priceFeed(token)` needs something that
answers **`IAggregatorV3`** — not a Chainlink-*operated* feed. Lane A's own `MockAggregatorV3`
proves it.

So `venues/aqua/solidity/src/ERC4626PriceFeed.sol` composes `convertToAssets(1 share) × underlying
USD price` and *is* a feed. **No `contracts/` change was required**, which matters because it landed
during Lane A's adversarial security pass. Valuing a MetaMorpho share as plain USDC understates by
**760 bps** and worsens every block.

The subtle part: **timestamps pass through from the underlying feed, never invented.**
`convertToAssets` is always current, so reporting `block.timestamp` would make the feed *always look
fresh* and silently defeat the vault's staleness check on the half that can actually go stale.

### 9.4 Findings that changed the lane's own code

| Finding | Consequence |
|---|---|
| **The deployed SwapVM is not the default branch.** Opcodes are *positions* in `AquaOpcodes`, not a hex enum — `XYCSwap` is 17 on chain and `0x50` on `main`. | Pinned to v1.0.1; the builder derives opcodes from 1inch's own table via function pointers, so **no opcode number appears in our source**. |
| **`safeBalances()` non-zero does not mean fillable.** A ship with no approvals looks perfect and can never be filled. | Fillability gates on the **vault→Aqua allowance**. My first version of this check would have passed on a dead position — Lane B caught it. |
| **The Uniswap `minOut` cannot be read per-leg.** Pure-V3 splits carry per-leg minimums; V3+V4 routes carry **zeros** plus one trailing `SWEEP`. Both seen minutes apart. | Tests assert the *effective aggregate*. A grep gives a false negative; a per-leg check gives a false alarm. |
| **A tight band and a stale fork do not mix.** The API quotes live, the fork executes hours behind — ~70 bps of drift against a 50 bps band. | `V3TooLittleReceived` on the fork is **direction-dependent**, so it comes and goes with the market. Fork runs want ~150 bps. |

### 9.5 What the lane ships beyond adapters

- **`venues.manifest()`** — what each venue does, in JSON, no network I/O. A test fails if it ever
  diverges from the registry. Exists because a hardcoded list hid the fully-built Aave venue for a
  whole wave.
- **`venues.reverts.describe(selector)`** — eleven revert selectors across Uniswap, Permit2, Aqua,
  MetaMorpho and the vault, each with cause *and* fix. Exists because `0x39d35496` blocked R5 for
  hours while every hypothesis was about 1inch; it was Uniswap's.
- **`venues.aqua.assert_position_fillable()`** — the R5 gate.

### 9.6 Still open, none of it blocking

| Item | Owner |
|---|---|
| Register the MetaMorpho valuation (3 steps, #66) — makes `morpho` live | whoever owns `scripts/` |
| `GET /venues` serving `manifest()` (#73) | Lane B |
| `UNISWAP_SLIPPAGE_BPS=150` for fork runs (#74) | whoever runs the stack |
| **Uniswap Developer Feedback Form** | **a human** — `FEEDBACK.md` is written |
| Taker fill demo | needs 1inch's deployed SwapVM source; explicitly *not* on the critical path |

**Test counts at close of Wave 2:** 173 Python, 46 Foundry (1 skipped and documented — the taker
fill).

---

## 10. Wave 3 — the bounty audit, and the claim that got stronger

**Assigned:** §6 of the Wave 3 plan — audit this lane's sponsor integrations against four criteria
(to spec · full potential · **not shoehorned** · actually working), and confront three named weak
points. Deliverable: [`venues/AUDIT.md`](../venues/AUDIT.md).

### 10.1 The three weak points, answered

| Weak point | Answer |
|---|---|
| *"The SwapVM taker fill has never been demonstrated"* (#29) | ✅ **Closed.** The fill runs against the real deployed contracts. We may now say the vault **market-makes**. |
| *"Uniswap Track 2 is our weakest claim"* | 🟡 **Argued properly, and criterion 2 is a flat no.** Recommendation filed as #104; the call to submit or drop is Lane F's. |
| *"Is Aqua load-bearing or decorative?"* | ✅ **Load-bearing — but not for the reason the removal test gives.** See below. |

### 10.2 What #29 actually was

The prior note said *"the deployed instruction table matches no published swap-vm source"* and
recommended asking 1inch at the venue. Both halves were wrong in instructive ways.

**The finding was bigger than stated: no published tag matches at all.** The deployed table carries
an `XYCConcentrate` entry v1.0.1 lacks, so `Controls._salt` and `Fee._flatFeeAmountInXD` each sat
one opcode low — we were asking the VM to run **Decay where we meant Salt**.

**And the answer never required a human.** The contract is verified on Blockscout and ships its own
`AquaOpcodes.sol`. It was one HTTP request away for an entire wave. *Ask the chain before asking a
person.*

The table was **read, not inferred** — almost every instruction parses its arguments first and
reverts with an error naming itself, so a one-instruction program per index fingerprints the whole
table. The probe and the verified source agree on all 28 entries. Guessing an offset from a single
revert would have been quicker and is exactly what must not happen: a wrong opcode is a *silently
mispriced* position, which is worse than no position.

**A second, independent bug sat behind the first.** v1.0.1 packs one more taker-traits slice than
the deployed contract parses, silently clearing `isExactIn`. The symptom was not a revert but a
quote that was **arithmetically perfect for a trade nobody asked for**.

### 10.3 The criterion-3 answer worth keeping

The removal test — *if this were removed, would the product still work?* — passes for Aqua, and
proves less than it looks: it is true of **every** venue individually, which is what a venue port is
for. The sharper question is whether Aqua does something no other venue can, that the product needs.

It does. **The vault is a contract with no private key**, and Aqua is the only one of four venues
where it earns *while keeping custody* (`custody: virtual`; the others are `claim` or `rotational`).
That is downstream of the locked Pattern 1 decision, not of a sponsor mapping.

**The part this lane cannot certify** — how often Lane B's loop actually chooses Aqua — is filed as
a question (#105) rather than written into an audit as an assumption.

### 10.4 Two lessons kept because they cost the most

- **A skipped test is not a weaker assertion, it is no assertion.** A Python test pinned the wrong
  opcodes and read green for two waves, because it is a `live` test that skips without a local RPC.
- **`ship()` never executes the program.** Every wrong-opcode variant encoded cleanly, shipped
  successfully and returned a valid hash. The first thing that runs a program is a taker's fill —
  so the fill test is the only thing that can tell you encoding still works.

**Test counts at close of Wave 3:** **185 Python, 44 Foundry** — including the 5 taker-fill tests
that were skipped for two waves, and 4 new ones that re-read the deployed opcode table off-chain
every run.
