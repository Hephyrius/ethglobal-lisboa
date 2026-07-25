# Venue-side bounty audit — Lane D

**Audited 2026-07-25, Wave 3, against this build.** Every ✅ below was re-run today; nothing is
inherited from an earlier wave's notes. Where the answer is "no" it says so in our own words, on the
principle that a limitation we state costs less than one a judge finds.

**Scope.** The sponsor integrations Lane D owns and can actually answer for: **1inch** (Aqua +
SwapVM) and **Uniswap** (Trading API, Permit2, UniversalRouter). The Graph tracks belong to Lane C
and are not assessed here. Aave and Morpho are venues, not sponsors — they appear only where they
change an answer.

The four criteria, and the question that actually tests each:

| # | Criterion | The real test |
|---|---|---|
| 1 | Done to spec | Quote the sponsor's wording; name the artefact that satisfies it |
| 2 | Used to full potential | Are we using one endpoint where the prize rewards depth? |
| 3 | **Not shoehorned** | **If this integration were removed, would the product still work?** |
| 4 | Actually working | Verified live, *this* build — not "it worked once" |

---

## 1inch — Build an Aqua App (Tracks 1 & 2, $5,000 + $2,000)

> *"Projects utilizing SwapVM receive higher scoring during final judging."*

### Criterion 1 — done to spec ✅

| Requirement (their words) | Evidence |
|---|---|
| "Official Aqua/SwapVM contracts must be used" | Aqua `0x4999…6d31`, SwapVM `0x8fDD…958f`, unmodified. Programs are compiled by 1inch's own Solidity `ProgramBuilder` read via `eth_call` — we never hand-encode their bytecode. |
| "Onchain execution of token transfers should be presented during the final demo (local forks are ok)" | **Now satisfied by Aqua itself**, not only by the Uniswap rotation — see criterion 2. |
| "Proper Git commit history (no single-commit entries on the final day)" | Continuous pushed history across all six lanes. |
| SwapVM used (scoring bonus) | Aqua mode, `useAquaInsteadOfSignature = true` — the mode a keyless contract maker requires. |

### Criterion 2 — full potential: **materially better than last wave, and still not maximal**

**What changed.** For two waves the honest claim was *"the vault ships and docks real Aqua
positions"* and explicitly **not** *"the vault market-makes"*, because `AquaTakerFillFork.t.sol` was
written and then skipped. That gap is closed. A third-party taker now fills the vault's position
against the real deployed contracts, **real ERC-20s move in both directions**, and the vault earns
its maker fee — five tests, green ([`test/AquaTakerFillFork.t.sol`](aqua/solidity/test/AquaTakerFillFork.t.sol)).

This matters for the transfer requirement specifically. `Aqua.ship()` deliberately moves **no
tokens** — that is the whole point of virtual balances and it is what makes Aqua compatible with our
custody model. So a ship alone never satisfied *"onchain execution of token transfers"*. The fill
does, and it is now Aqua's own evidence rather than Uniswap's.

**The honest "no", and it is a real one: we use 3 of the deployed VM's 17 instructions.**

We emit `Fee._flatFeeAmountInXD`, `XYCSwap._xycSwapXD`, `Controls._salt`. The deployed instruction
table — which we now know exactly, having read it off the chain — also offers `Decay`,
`XYCConcentrate` (two variants), `PeggedSwap`-style pricing, progressive and protocol fees, and a
set of `Controls` gates including `_deadline`, `_jumpIfTokenIn`/`Out` and taker-balance
preconditions. A constant-product curve with a flat fee is the simplest thing SwapVM can express.

Two of those are worth naming as specific, un-taken opportunities rather than a vague "we could do
more":

- **`Controls._deadline`** — our maker position has no expiry. It stays quotable until the agent
  docks it, so a stale curve can be filled at a price the agent no longer believes. This is a real
  (small) risk, not just an unused feature.
- **`XYCConcentrate`** — concentrating the range would make the same capital quote tighter, which is
  the actual reason a maker earns.

**Recommendation: do not add either before the demo.** Both change the program bytes, and the
program is inside the strategy hash that identifies a position — so both invalidate every live
position and every fixture two other lanes build against, on the last day, to improve a claim that
is already true. The right entry is the build log and this document, and the deadline gap belongs in
the security write-up as a known limitation.

### Criterion 3 — not shoehorned: **the removal test, answered honestly**

**Strictly applied, the removal test passes for Aqua but proves less than it looks.** Remove Aqua
and the vault still reads data, still decides, still rotates on Uniswap and still lends on
Aave/Morpho. The product works. But that is true of *every* venue individually — it is what a venue
port is for — so "removable" cannot be the whole test or it condemns good architecture.

The sharper question is whether Aqua does something **no other venue can**, that the product
actually needs. It does, and it is not a prize-shaped reason:

**The vault is a contract with no private key.** That constraint is the spine of this lane. Of the
four venues, Aqua is the only one where the vault earns while *retaining custody* — the capability
manifest records this as a first-class field, and the values are not decoration:

| Venue | custody | what happens to the tokens |
|---|---|---|
| uniswap | `rotational` | leave; different token comes back |
| aave / morpho | `claim` | leave; a receipt token comes back |
| **aqua** | **`virtual`** | **never leave the vault** |

Aqua's `useAquaInsteadOfSignature` is what lets a keyless contract be a maker at all, and virtual
balances are what let it quote without surrendering the assets. Pattern 1 custody was a **locked
architecture decision** taken before any sponsor mapping — Aqua is the venue that fits it, not a
venue bolted on to claim it. Pinned by
[`test_shippingThroughTheVaultStillMovesNoTokens`](aqua/solidity/test/VaultRelayFork.t.sol).

**Where the claim would become shoehorned, and the part I cannot certify.** If the agent ships into
Aqua once for the demo and never again, criterion 3 fails no matter how good the adapter is. Whether
idle capital routes through Aqua *as a standing strategy* is Lane B's decision loop, not mine. What
I can certify: the venue is complete, available, and exercised end to end. What I would not assert
on Lane B's behalf: how often it gets chosen. **Lane F should confirm that against a real run before
the submission leans on it** — filed as a request rather than assumed here.

### Criterion 4 — actually working ✅

**44 Foundry tests, green against the real deployed contracts on a Base fork, today** — including
the 5 that were skipped for two waves. Ship, fill, dock, fee earned, custody preserved, plus a
4-test guard that re-reads the deployed opcode table off the chain.

The reason that guard exists is itself criterion-4 evidence, so it is worth stating plainly: our
programs were built against swap-vm v1.0.1 on the belief that it was the deployed version. **It is
not, and no published tag is.** The deployed table carries an instruction v1.0.1 lacks, so `salt`
and the flat fee each sat one opcode low — we were asking the VM to run **Decay where we meant
Salt**. `ship()` never executes the program, so nothing failed at ship time, nothing failed at hash
time, and the position looked healthy in every observable way. Only a fill could reveal it.

**A skipped test is not a weaker assertion, it is no assertion.** A Python test *did* pin the wrong
opcodes and passed throughout, because it was a `live` test skipping for want of a local RPC. That
is the strongest argument in this document for criterion 4 being a real criterion.

---

## Uniswap — Best API Integration (Track 1, $7,000)

### Criterion 1 — done to spec ✅

| Requirement | Evidence |
|---|---|
| "Integrate the Uniswap API with a valid API key from the Uniswap Developer Platform" | `POST /quote` → `POST /swap` with `x-api-key`. Re-verified live today: a 500 USDC → WETH quote on Base returned a routed quote and a complete unsigned transaction to UniversalRouter `0x6fF5…9b43`. |
| "a FEEDBACK.md file" | [`FEEDBACK.md`](../FEEDBACK.md) — six items, each reproducible. |
| "README clearly points to the relevant contracts and lines of code" | Line-anchored links in [`README.md`](README.md). ⚠️ **Re-check the anchors immediately before submitting** — two drifted by one line during an unrelated refactor in an earlier wave. A submission requirement can be broken by a change two files away. |
| Public repo, demo video, feedback form | ⬜ **human** — not Lane D's to do. |

### Criterion 2 — full potential: **partial, and stated as such**

We use **two endpoints**, `/quote` and `/swap`. We do not use indicative quotes, the swappable-token
list, or approval-check helpers. For a track judged on API integration this is the thin part of the
claim, and the mitigation is depth rather than breadth: what we do with those two endpoints is
handle the cases their happy path does not — see below.

### Criterion 3 — not shoehorned ✅ **this is our strongest removal-test answer**

**Remove Uniswap and the product stops working**, not degrades. Uniswap is the only venue that
*changes what the vault holds*. Aqua quotes the vault's existing inventory; Aave and Morpho lend an
asset and return a claim on the same asset. None of them can turn USDC into WETH. An LLM curator
whose entire job is choosing an allocation, with no way to move between assets, has nothing to
execute — it could only ever lend or make markets in what it already happens to hold.

That is the removal test passing on its own terms, not on a technicality.

### Criterion 4 — actually working ✅

9 live tests against the real API, green today, plus a full plan built end to end this session:
ERC-20 approve (`0x095ea7b3`) → Permit2 approve (`0x87517c45`) → UniversalRouter execute
(`0x3593564c`), 250 bps slippage bound carried into the calldata.

⚠️ **One live warning worth carrying into the demo.** The fork runs behind live Base, and the API
quotes live. When the price has drifted the wrong way the swap reverts with
`V3TooLittleReceived()` — measured at 72 bps of drift against a 50 bps band. It passes today only
because the drift happens to point the friendly way. Widening `UNISWAP_SLIPPAGE_BPS` to 150 for fork
runs makes the demo robust, at the cost that the run stops being evidence the slippage gate works.
That trade is Lane F's to make; it is recorded here so it is made deliberately.

---

## Uniswap — Best Stack Contribution (Track 2, $3,000)

> *"Build on or extend the Uniswap open-source ecosystem using **any part of the Uniswap stack**."*

**This is our weakest track, and the plan asked for the argument to be made properly or the track
dropped. My recommendation: claim it, with the framing below, and never imply more.**

### The honest core

**Track 2 is not a second integration. It is a second reading of the first one.** Everything it
would cite is the same code Track 1 cites. That should be said plainly rather than dressed up,
because a judge comparing the two submissions will notice immediately, and a shoehorned integration
discredits the rest of the entry.

### What genuinely supports the claim

We build directly on two parts of the Uniswap stack — **Permit2** and **UniversalRouter** — and we
drive Permit2 in a mode the Trading API's documented path does not produce.

The vault is a contract with no private key. `/quote` returns a `permitData` block to be signed as
an EIP-712 `PermitSingle`; **our swapper cannot sign anything, ever.** The documented path is
unavailable to an entire class of integrator. The path that works is Permit2's other entry point —
an ordinary on-chain `approve(token, spender, amount, expiration)` — which yields the same allowance
with no signature, after which `/swap` builds the calldata regardless.

**Measured live today, and this sharpens the finding considerably:**

```
isTokenApprovalApplicable : true
permitData                : { types: [PermitSingle, PermitDetails], … }
permitTransaction         : null
```

The response carries **both** a signature request and a slot for the on-chain alternative — and
populates only the one a contract cannot use. We had assumed the signature-free path was
undocumented. It is not: it is *modelled in their own response schema* and left null. That is a
finished-looking API with an unfinished branch, and it is a much easier fix than new surface. Now
written up as [`FEEDBACK.md`](../FEEDBACK.md) §4 with the preferred fix (populate
`permitTransaction`).

The pattern is pinned as behaviour, not prose:
[`TestAKeylessContractCanExecuteEveryStep`](tests/test_uniswap_plan.py) asserts that no step calls
Permit2's signature entry point, that an `ExecutionPlan` step has nowhere for signature material to
live, and — deliberately — that the API *still* sends the `permitData` we ignore, so that if Uniswap
ever fixes this, a test fails and someone re-reads the reason instead of carrying a workaround
nobody remembers the cause of.

### The four criteria, applied without flattery

| # | Verdict |
|---|---|
| 1 · to spec | 🟡 Satisfies "**build on** … any part of the Uniswap stack" literally — Permit2 and UniversalRouter are the Uniswap stack. Does **not** satisfy "extend" in the sense of code contributed to a Uniswap repository. |
| 2 · full potential | ❌ **No.** We contributed no code upstream and opened no PR or issue. The contribution is a documented, tested integration pattern plus evidenced API feedback. That is real, and it is not a stack contribution in the strongest sense of the phrase. |
| 3 · not shoehorned | 🟡 The *integration* is load-bearing (see Track 1). The *second track claim* is a framing of it. |
| 4 · working | ✅ Verified live today. |

### Recommendation

**Submit, with the claim worded as "an integration pattern for keyless contract swappers, documented
and tested, plus the API feedback that came out of it."** Do not write "we extended the Uniswap
stack".

The requirement says "build on **or** extend", and building on Permit2 and UniversalRouter is
exactly what we do — so this is a legitimate entry, not a stretch. But it is the one track where our
answer to criterion 2 is a flat no, and the submission is stronger for saying so than for hoping
nobody checks. If Lane F would rather submit three confident tracks than four with one amber, this
is the one to drop; that call is theirs, and either choice is defensible.

---

## Summary

| Track | 1 · spec | 2 · potential | 3 · not shoehorned | 4 · working |
|---|---|---|---|---|
| 1inch — Aqua/SwapVM | ✅ | 🟡 3 of 17 instructions, named | ✅ only venue that earns without moving tokens¹ | ✅ 44 tests, fill included |
| Uniswap — API integration | ✅ | 🟡 two endpoints, depth not breadth | ✅ **removing it stops the product** | ✅ 9 live tests + live plan |
| Uniswap — Stack contribution | 🟡 | ❌ **no upstream contribution** | 🟡 a framing of Track 1 | ✅ |

¹ Conditional on the agent actually choosing Aqua in normal operation — Lane B's loop, not mine.
Confirm before the submission leans on it.

**Nothing in this table is inherited.** Every ✅ was re-run on 2026-07-25 against this build.
