# Wave 2 — six lanes, and a curator that actually deploys capital

**Date:** 2026-07-25 · **Supersedes nothing** — extends
[Wave 1](2026-07-25-wave-1-curation-depth.md), which closed all nine of its phases.

Wave 1 was one instance owning the whole tree, because the work was a chain of dependencies.
Wave 2 is not: the feedback splits cleanly along the original lane boundaries, so it goes back to
parallel. **With one structural change: a sixth lane that owns the seam.**

---

## 1. Why a sixth lane

[Rule 7](../INSTRUCTIONS.md) gives every lane a directory and forbids crossing. That is what let five
instances converge instead of colliding. But it leaves three things ownerless, and each has already
cost us:

| Ownerless thing | What it cost |
|---|---|
| **`packages/schema/` is frozen with no owner.** | Five of Wave 2's items need a schema field. Under Rule 7 nobody may add one, so five lanes stall on a file nobody is allowed to touch. Wave 1 only moved because the operator suspended the rule by hand. |
| **The cross-lane seam** — `scripts/`, `tests/e2e/`, the running stack. | The e2e plan says it outright: *"the seam between all five belongs to no lane, so nobody built it."* |
| **Shared-file hygiene and the request queue.** | Requests #14/#21 — `git add -A` swept other lanes' work into the wrong commits, twice each way. Request #55 — I force-pushed against a decision recorded in a table I had not re-read. Both are coordination failures, not code failures. |

**Lane F is the integration lane.** It owns the schema, the seam, the running stack, and the request
queue. It writes no product feature. Its first job — a 30-minute schema delta — is what unblocks
four of the other five, so it is genuinely first, not merely parallel.

> **The one rule that makes six lanes work:** F is the *only* lane that may edit
> `packages/schema/`. Everyone else files a request. In exchange, F commits to a **30-minute
> turnaround** on schema requests during the wave, because a frozen schema with a slow owner is
> worse than a frozen schema with no owner — it looks unblocked and is not.

---

## 2. The six lanes at a glance

| Lane | Directory | Wave 2 headline |
|---|---|---|
| **A** | `contracts/` | Adversarial pass: front-running, donation/inflation, fuzz + invariants. No new features. |
| **B** | `agent/` | Idle capital gets deployed · personas · soft mandate band · risk-adjusted return as the standing objective |
| **C** | `data/` | Source notes that read like diagnoses · prediction-market odds · protocol breadth |
| **D** | `venues/` | Prediction-market venue (timeboxed) · Morpho · venue capability manifest |
| **E** | `web/` | Responsive · token logos · holdings donut · genesis presets and example buttons · disclaimer · docs drawer |
| **F** | `packages/schema/`, `scripts/`, `tests/e2e/`, `docs/`, root | **Schema delta first** · model bake-off · secrets audit · stack · request queue · rehearsal |

---

## 3. F ships first — the Wave 2 schema delta (target: 30 minutes)

Four lanes are blocked until this lands. It is small on purpose.

### 3.1 `MandateConstraints.tolerance_band_pct: float = 0.05`

*"Make the rules less rigid (for now) — violation allowed within a threshold of mandate ±5%."*

A decision that breaches a numeric constraint by **no more than the band** is **accepted with a
recorded warning** rather than rejected.

**The band does not apply uniformly, and getting that wrong turns "less rigid" into "no rules":**

| Constraint | Band applies? | Why |
|---|---|---|
| `max_position_pct`, `min_cash_pct`, target-allocation drift | ✅ yes | These are *aims*. Landing at 61% against a 60% cap is a rounding artefact of a swap that priced a hair differently, not a breach of intent. |
| `max_slippage_bps` | ❌ **never** | A ceiling is a worst case that was already compared against a bound, not an estimate (#33). Banding it means paying 5% more than the mandate's stated maximum cost, silently. |
| `allowed_assets`, `permitted_venues`, `permitted_data_sources` | ❌ **never** | Not numeric. There is no "5% of an asset that isn't permitted". |
| `max_actions_per_tick`, `rebalance_cooldown_seconds` | ❌ no | Anti-churn limits. A band here is just a bigger limit. |

**Every banded acceptance must be visible in three places** — the `AgentAction`, the decision feed,
and the reflection — or the band becomes a way for the agent to drift without anyone noticing. That
visibility requirement is the whole reason this is a schema change and not a constant in B's code.

### 3.2 `Mandate.persona: Persona | None`

```python
class Persona(Frozen):
    name: str                      # "Scam Bankman-Fried"
    voice: str                     # how it writes its reasoning
    biases: list[str]              # "prefers the highest headline yield over the deepest market"
    conviction: Literal["low", "medium", "high"] = "medium"
```

**Invariant, pinned by a test in B:** a persona **skews preference inside the permitted set and can
never widen it.** An aggressive persona may prefer the riskier of two permitted assets; it may not
reach an asset the mandate did not allow, raise a cap, or shrink the cash floor. Persona is
*taste*; constraints are *law*. If those two ever merge, "aggressive" becomes an exploit.

### 3.3 `MandatePreset` — a new frozen fixture set

`packages/schema/presets/*.json`, one file per archetype, validated against the `Mandate` schema by
the existing conformance test so a preset can never be un-deployable.

Three to start, named after what they do rather than after a firm we do not speak for:

| Preset | Shape |
|---|---|
| **Conservative income** | USDC base, lending-only, high cash floor, tight slippage — the Spark/Gauntlet-style stable-yield book |
| **Balanced two-asset** | The current golden mandate: USDC/WETH 50/50, rebalance on drift |
| **Opportunistic** | Wider asset set, Aqua market-making permitted, higher position cap |

Both B (prompt) and E (buttons) read the same files, so the recommendation the model gives and the
button the user clicks cannot diverge.

### 3.4 `Mandate.permitted_venues` — widen only if D confirms

Currently `Literal["uniswap", "aqua", "aave"]`. Adds `"morpho"` and a prediction-market key **only
after D has verified bytecode on the fork.** The Literal is closed deliberately: a mandate naming a
venue with no adapter produces a vault whose agent proposes trades the harness can only reject.

### 3.5 Not changing

`MarketSnapshot.notes` / `SourceNote` already landed in Wave 1 P1 — C's diagnostic messages need no
schema change. Neither does the idle-capital rule: it is a derived fact plus a prompt rule, and
adding a field for it would put a policy in the frozen interface.

---

## 4. Lane A — `contracts/`

**Headline: an adversarial pass. No new features.** The contracts work; the question Wave 2 asks is
whether they survive someone trying.

### A1 · Front-running and value-extraction review — *write it down, then test it*

Produce `contracts/SECURITY.md` covering each vector with **the test that proves the claim**, not
prose. Known state: `ReentrancyGuardUpgradeable` ✅, `SafeERC20` ✅, `nonReentrant` on all six
mutating paths ✅, `_decimalsOffset() = 12` ✅.

| Vector | Current belief | What must exist |
|---|---|---|
| **Donation / first-depositor inflation** | Mitigated by the decimals offset | A test that actually runs it: attacker deposits 1 wei, donates a large balance, victim deposits, victim redeems ≥ their deposit minus rounding. *This is the classic 4626 theft and "we set the offset" is an assertion until it is a test.* |
| **Sandwiching the agent's rebalance** | Uniswap plan carries a `minOut` | **Verify the calldata actually sets it** and it is derived from the mandate's slippage bound — a `minOut` of 0 in a public-mempool tx is a free lunch for a searcher. If D owns that calldata, file a request; do not read `venues/`. |
| **Deposit/withdraw sandwich around a rebalance** | Unmitigated | Likely stays unmitigated — the fixes (entry fee, timelock) are out of scope for a hackathon. **Document it as a known limitation.** An honest limitation beats a silent one. |
| **Stale-price share pricing** | `priceMaxAge = 0` on the fork = staleness **off** | Already reverts on real networks (#28). State plainly in SECURITY.md that fork mode disables it and why, so a judge reading `0` does not conclude it ships that way. |
| **Allowlist bypass** | `execute`/`executeBatch` gated | Fuzz it (below). |

### A2 · Fuzz and invariant pass

`fuzz.runs = 256` is configured and there is no `test/invariant/`. Add one.

Invariants worth stating — each is a sentence a judge can check:
1. **Only `AGENT_ROLE` can move value.** Fuzz caller × function × calldata; no other address ever changes `totalAssets()`.
2. **`execute` cannot reach a non-allowlisted target**, for any calldata, including via `executeBatch` ordering.
3. **Share price is monotonic under deposit/withdraw alone** — only agent action or price movement may change it.
4. **`totalAssets()` equals the sum of the valued holdings**, across arbitrary deposit/withdraw/price sequences.
5. **Redeeming all shares returns all assets**, minus rounding of at most 1 wei per holding.

Raise `runs` for the invariant profile; keep the default at 256 so the normal suite stays fast.

**Definition of done:** `contracts/SECURITY.md` published, invariant suite green, and the
donation-attack test present and passing. Test count goes 92 → whatever; the number is not the point,
the named vectors are.

<details>
<summary><b>Continuation prompt — Lane A</b></summary>

```text
You are Lane A. You own `contracts/` and nothing else.

Read first, in order: CLAUDE.md, INSTRUCTIONS.md,
plans/2026-07-25-wave-2-six-lanes.md §4 (your section), docs/active-work.md.
Claim Lane A in docs/active-work.md before you write code. Run Foundry in
`wsl -d Ubuntu-24.04` — the default WSL distro has glibc too old and will waste an hour.

Wave 2 gives you an adversarial pass, not new features. Two deliverables:

1. `contracts/SECURITY.md` — one section per attack vector in the plan's table, each
   ending with the test that proves the claim. Where something is genuinely unmitigated
   (deposit/withdraw sandwiching around a rebalance is the likely one), say so plainly
   and explain why it is out of scope. A documented limitation is worth more than an
   omission a judge finds.

2. `contracts/test/invariant/` — the five invariants in §A2. Also add the
   donation/inflation attack as an explicit unit test: `_decimalsOffset() = 12` is
   currently an assertion, and this repo's standard is that an assertion is not evidence.

Two things you must NOT do:
- Do not read or edit `venues/`, `agent/`, `web/`, or `data/`. Lane D also writes Solidity,
  in its own Foundry project. If verifying the swap `minOut` needs Lane D's calldata,
  file a cross-lane request in docs/active-work.md and keep going.
- Do not change `packages/schema/`. Lane F owns it this wave. File a request; F has
  committed to a 30-minute turnaround.

Do not redeploy to the shared fork without announcing it in docs/active-work.md —
four lanes read `deployments/base-fork.json` and Lane B has live positions.

Commit and push after every meaningful change, staging explicit paths
(`git add contracts/ docs/build-log.md docs/active-work.md`) — never `-A`, never `-a`.
Requests #14 and #21 exist because that command swept three lanes' work into the
wrong commits. Add a `docs/build-log.md` entry for every non-trivial decision,
explaining the WHY.
```

</details>

---

## 5. Lane B — `agent/`

**Headline: the agent stops sitting on cash, gets a personality, and is graded on risk-adjusted
return.** This is the largest lane in Wave 2.

### B1 · Idle capital must be deployed *(the headline feedback item)*

> *"Ensure that the agents are deploying — liquidity needs to be deployed on Aqua (or other
> protocols — Morpho, Aave, lstETH) when idle within risk parameters of the vault."*

Today the agent swaps and then holds. Three changes, deliberately layered so none of them *forces*
a trade:

1. **Idle capital becomes a fact.** Compute `idle_pct` = base-asset holdings above `min_cash_pct`
   that carry no `committed_to_venue`, and inject it into the snapshot as a first-class fact the
   model can cite. Making it citable is what lets the decision feed show *"deployed because 68% of
   the book was idle"* rather than the agent asserting it.
2. **The prompt states the default.** Idle capital above the floor is a *position* — the position of
   earning nothing. Deploying is the default; **holding is a choice that needs a reason.** The
   reasoning must name it either way.
3. **The reflection prices the drag.** Wave 1's `agent/loop/reflection.py` already grades outcomes.
   Add *idle drag*: what the idle balance would have earned at the best permitted lending rate over
   the window it sat there. That closes the loop — the agent's own track record tells it that
   holding cost something, which is a stronger steer than a prompt line.

**Do not add a validation layer that rejects `hold`.** `hold` is a first-class answer and a harness
that punishes it churns the vault, which is the failure mode the whole six-layer design exists to
prevent. Pressure belongs in the prompt and the scoreboard, not in the gate.

⚠️ **Aqua approvals may never be optimised away** (#17, #25) — `ship()` succeeds with zero allowance
and yields a position that looks perfect and can never be filled. `agent/tests/test_aqua_approvals.py`
pins this. Deploying more capital into Aqua makes that trap more valuable, not less.

### B2 · Personas in the harness

Consume `Mandate.persona` (F ships it in §3.2). Compose it into the system prompt: voice, biases,
conviction. The persona shapes *how the agent argues and what it prefers*; constraints stay law.

**Pin the invariant with a test:** an aggressive persona cannot reach an asset outside
`allowed_assets`, cannot exceed `max_position_pct`, cannot go under `min_cash_pct`. Take a decision
that a persona would plausibly produce, run it through `check_decision`, assert it is still
rejected. If persona can widen constraints, "aggressive" is an exploit rather than a style.

### B3 · The soft mandate band

Consume `tolerance_band_pct`. A numeric breach within the band on a **banded** constraint (§3.1
table — allocation and exposure only, never slippage, never allowlists) becomes a warning carried on
the `AgentAction` rather than a rejection.

Two failure modes to design against, both worse than the rigidity being fixed:
- **Ratchet.** Accepting 5% over, tick after tick, walks the book away from the mandate without ever
  triggering a rejection. Measure drift against the **mandate**, not against last tick.
- **Invisible drift.** Every banded acceptance must reach the feed and the reflection.

### B4 · Risk-adjusted return as the standing objective

> *"The agent's goal should always be making the highest risk-adjusted return for the current given
> mandate."*

Wave 1 computes `risk_adjusted_return` and deliberately does not call it a Sharpe ratio. Wave 2
promotes it: it opens the prompt as the scoreboard, and the reflection frames every past decision
against it. When the figure is `None` — not enough history — say so; a fabricated zero would teach
the model that doing nothing scores fine.

### B5 · Genesis guidance

Read F's presets (§3.3) and offer them in the genesis conversation as named starting points with
their tradeoffs, then let the user amend. The asset and protocol universe is already available via
`offerable_assets()` and the now-correct `available_venues()`; surface both in the opening turn so
the user knows the menu before being asked to choose from it.

<details>
<summary><b>Continuation prompt — Lane B</b></summary>

```text
You are Lane B. You own `agent/` and nothing else.

Read first, in order: CLAUDE.md, INSTRUCTIONS.md,
plans/2026-07-25-wave-2-six-lanes.md §5 (your section), docs/active-work.md
(especially requests #17, #25, #40, #51b — the Aqua approval trap and why a
model-authored ship failed three times), agent/README.md.
Claim Lane B in docs/active-work.md before you write code.

Five deliverables, in this order:

1. IDLE CAPITAL — the headline item. The agent swaps and then sits on cash.
   (a) derive `idle_pct` and inject it as a citable fact in the snapshot;
   (b) state in the prompt that idle capital above `min_cash_pct` is the position of
       earning nothing — deploying is the default, holding needs a stated reason;
   (c) add idle drag to `agent/loop/reflection.py`: what the idle balance would have
       earned at the best permitted lending rate over the window it sat idle.
   DO NOT add a validation layer that rejects `hold`. `hold` is a first-class answer and
   a harness that punishes it churns the vault. Pressure goes in the prompt and the
   scoreboard, never in the gate.

2. PERSONAS — consume `Mandate.persona` (Lane F is shipping the field; if it is not there
   yet, build against the shape in §3.2 and wire it when it lands). Compose voice, biases
   and conviction into the system prompt. THEN PIN THE INVARIANT WITH A TEST: a persona
   skews preference inside the permitted set and can never widen it. If an aggressive
   persona can reach an unpermitted asset or exceed a cap, "aggressive" is an exploit.

3. SOFT MANDATE BAND — consume `tolerance_band_pct`. Read §3.1's table carefully: the band
   applies to allocation and exposure constraints ONLY. Never to `max_slippage_bps` (a
   ceiling was already compared against a bound, not an estimate), never to the asset,
   venue or source allowlists (not numeric). Guard against the ratchet: measure drift
   against the mandate, not against last tick. Every banded acceptance must be visible on
   the AgentAction so Lane E can render it.

4. RISK-ADJUSTED RETURN — promote the Wave 1 figure to the scoreboard the prompt opens
   with. When it is None for want of history, say None; a fabricated 0.0 teaches the model
   that doing nothing scores fine.

5. GENESIS GUIDANCE — read Lane F's presets from `packages/schema/presets/` and offer them
   as named starting points with their tradeoffs. Surface the asset and venue universe in
   the opening turn.

Boundaries: do not read or edit `venues/`, `data/`, `web/`, `contracts/`. Integrate through
their READMEs. Do not edit `packages/schema/` — file a request for Lane F, who has committed
to a 30-minute turnaround.

Known trap you must not undo: Aqua approvals can never be optimised away. `ship()` succeeds
with ZERO allowance and produces a position that looks healthy in every observable way and
is silently unfillable (#17). `agent/tests/test_aqua_approvals.py` pins it.

Commit and push after every meaningful change, staging explicit paths
(`git add agent/ docs/build-log.md docs/active-work.md`) — never `-A`. Build-log entry for
every non-trivial decision, explaining the WHY.
```

</details>

---

## 6. Lane C — `data/`

**Headline: source notes that read like a diagnosis, and enough breadth that the universe is real.**

### C1 · Diagnostic source notes — *exactly the shape the feedback asked for*

Wave 1 P1 fixed the framing (70 of 73 "errors" were not failures). Wave 2 makes each note *say what
happened and what the agent should do about it*. The feedback wrote the target verbatim:

```
messari — uniswap-v3: no response within 6s — skipped so it does not delay the other protocols
chainlink — USDC: price is 24.5h old — the agent should treat it as stale
```

Three parts to every note: **who** (source — subject), **what** (the observation, with the number),
**so what** (the consequence already taken, or the one the agent should draw). Populate the existing
`SourceNote` model — no schema change needed. Cover at minimum: timeout-and-skipped, stale-price,
partial-response, rate-limited, credential-absent.

### C2 · Prediction-market odds as facts

Feasible without any venue integration and useful on its own: an implied probability is a market
consensus about the future, which is exactly the kind of fact a curator should weigh against a
backward-looking APY. **Read-only, free, non-token-gated.** This ships regardless of whether D's
venue integration lands, and is the honest fallback if it does not.

### C3 · Protocol breadth

> *"The universe is too small — right now it's only like 2 assets and protocol diversity is lacking."*

Wave 1 P3 widened it. Wave 2 finishes the job: **Morpho** (Base's largest lending market by TVL and
the obvious gap next to Aave and Moonwell) and **LST/LRT yield** — the `lstETH` the feedback names.
Note wstETH was excluded in Wave 1 for a specific reason: **its Base Chainlink feed reports
`WSTETH / ETH` at 18 decimals, not USD.** Any LST work must handle that or repeat the mistake.

Every new source obeys the standing rules: free, no token gate, degrades into a `SourceNote` rather
than taking the snapshot down, and `GasSource`'s lesson — **catch `Exception`, not a tuple of the
two you thought of**, or one stray `RuntimeError` kills the whole source.

<details>
<summary><b>Continuation prompt — Lane C</b></summary>

```text
You are Lane C. You own `data/` and nothing else.

Read first, in order: CLAUDE.md, INSTRUCTIONS.md,
plans/2026-07-25-wave-2-six-lanes.md §6 (your section), docs/active-work.md
(requests #19, #22, #31, #43, #50 are all yours and carry hard-won API detail),
data/README.md, data/GRAPH-USAGE.md.
Claim Lane C in docs/active-work.md before you write code.

Three deliverables:

1. DIAGNOSTIC SOURCE NOTES. Wave 1 fixed the framing; now make each note a diagnosis.
   Three parts every time: who (source — subject), what (the observation WITH the number),
   so what (the consequence already taken, or the one the agent should draw). The feedback
   wrote the target verbatim:
     messari — uniswap-v3: no response within 6s — skipped so it does not delay the others
     chainlink — USDC: price is 24.5h old — the agent should treat it as stale
   Populate the existing `SourceNote` model. No schema change needed.
   Cover: timeout-and-skipped, stale-price, partial-response, rate-limited, credential-absent.

2. PREDICTION-MARKET ODDS as facts (read-only, free, no token gate). An implied probability
   is a forward-looking market consensus, which is worth weighing against a backward-looking
   APY. This ships independently of Lane D's venue work and is the honest fallback if that
   does not land.

3. PROTOCOL BREADTH — Morpho (the obvious gap next to Aave and Moonwell on Base) and LST
   yield. WARNING, learned the expensive way: wstETH was excluded in Wave 1 because its Base
   Chainlink feed reports WSTETH/ETH at 18 decimals, NOT USD. Handle that explicitly or you
   will reproduce a 10^x pricing error.

Every new source: free, no token gate, degrades into a SourceNote rather than taking the
snapshot down, and catches `Exception` — not a tuple of the two exception types you thought
of. A stray RuntimeError killed the whole gas source in Wave 1 for exactly that reason.

Boundaries: do not read or edit `agent/`, `venues/`, `web/`, `contracts/`. Do not edit
`packages/schema/` — file a request for Lane F.

You publish to PyPI. A published version is PERMANENT: bump the version before any republish,
and remember `uv sync --extra <one>` PRUNES the other lanes' packages from the shared venv —
always `--all-extras`.

Commit and push after every meaningful change, staging explicit paths
(`git add data/ docs/build-log.md docs/active-work.md`) — never `-A`. Build-log entry for
every non-trivial decision, explaining the WHY.
```

</details>

---

## 7. Lane D — `venues/`

**Headline: somewhere else for idle capital to go, and a venue list the UI can trust.**

### D1 · Venue capability manifest — *do this first, it is small and it unblocks E*

Every venue publishes what it can do: intents supported, tokens supported, whether it is
**custodial or virtual** (Aqua is virtual — tokens never leave, which is the Pattern 1 claim), and
whether it is currently reachable. `get_venue(key)` grew an introspection gap in Wave 1 that meant
Aave *could never be granted in a mandate* despite being fully built. F patched the symptom; a
manifest fixes the cause and gives E something real to render for
*"show available venues on UI."*

### D2 · Prediction-market venue — **timeboxed to 90 minutes, with a defined fallback**

Candidate on Base: **Limitless**. Treat that as a lead, not a fact — this repo's own standard
(#30) is *check third-party integrations against the deployed bytecode, not the docs*, which is how
the SwapVM version mismatch was caught in two minutes.

**The 90-minute gate:** contract verified on the fork, a callable read path, and a plausible write
path. If any is missing, **stop and write up what you found.** The fallback is already covered —
Lane C ships odds as read-only facts regardless — so the agent still *reasons about* prediction
markets even if it cannot trade them. Report the outcome to F immediately either way: F only widens
`permitted_venues` on your confirmation, and a venue key with no adapter produces a vault whose
agent proposes trades the harness can only reject.

### D3 · Morpho supply/withdraw

Same shape as the Aave venue Wave 1 built, and the highest-value place for idle capital to go after
Aave. Reuse the `SupplyIntent`/`WithdrawIntent` shapes; they were designed to be venue-agnostic.

⚠️ Aave's `_assert_valued()` guard exists for a real reason: **supplying into a receipt token absent
from the manifest allowlist collapses the vault's share price**, because the vault holds something
`totalAssets()` cannot value. Morpho needs the identical guard on day one, not as a follow-up.

### D4 · Verify the swap `minOut`

Lane A will ask (§A1). Confirm from your side that the Uniswap calldata carries a real `minOut`
derived from the mandate's slippage bound, and publish the answer as a cross-lane request. If it
does not, that is a live front-running hole in the demo path, and it is yours.

<details>
<summary><b>Continuation prompt — Lane D</b></summary>

```text
You are Lane D. You own `venues/` — including its own Foundry project at
`venues/aqua/solidity/`. You never open `contracts/`; that is Lane A's.

Read first, in order: CLAUDE.md, INSTRUCTIONS.md,
plans/2026-07-25-wave-2-six-lanes.md §7 (your section), docs/active-work.md
(requests #17, #29, #30, #46, #48 are yours and carry findings you will otherwise re-derive),
venues/README.md.
Claim Lane D in docs/active-work.md before you write code.

Four deliverables, in this order:

1. VENUE CAPABILITY MANIFEST — do this first, it is small and it unblocks Lane E.
   Every venue publishes: intents supported, tokens supported, custodial vs virtual
   (Aqua is virtual — tokens never leave the vault, which IS the Pattern 1 claim), and
   current reachability. In Wave 1 `get_venue(key)` had no introspection, so genesis
   offered a hardcoded pair and the fully-built Aave venue could never be granted in a
   mandate. The symptom is patched; this fixes the cause.

2. PREDICTION-MARKET VENUE — TIMEBOXED TO 90 MINUTES. Candidate on Base: Limitless.
   Treat that as a lead, not a fact. Your own request #30 is the standard here: check the
   deployed bytecode, not the docs. Gate: contract verified on the fork + a callable read
   path + a plausible write path. If any is missing, STOP and write up what you found —
   Lane C ships prediction-market odds as read-only facts regardless, so the agent still
   reasons about them. Report the outcome to Lane F immediately either way; F widens
   `permitted_venues` only on your confirmation.

3. MORPHO supply/withdraw — same shape as the Aave venue, reusing SupplyIntent/WithdrawIntent.
   ⚠️ Aave's `_assert_valued()` guard is not optional boilerplate: supplying into a receipt
   token that is absent from the manifest allowlist COLLAPSES the vault's share price,
   because the vault then holds something `totalAssets()` cannot value. Morpho needs the
   identical guard on day one.

4. VERIFY THE SWAP `minOut`. Lane A is asking whether the Uniswap calldata carries a real
   minOut derived from the mandate's slippage bound. A minOut of 0 in a public-mempool tx is
   a free lunch for a searcher. Answer it as a cross-lane request in docs/active-work.md.

Boundaries: do not read or edit `contracts/`, `agent/`, `data/`, `web/`. Do not edit
`packages/schema/` — file a request for Lane F, who turns them round in 30 minutes.

Two live warnings from your own lane: Uniswap will not price a tiny trade (1 USDC returns a
Cloudflare HTML 504 or a 404 — keep test trades at ~100 USDC or more), and the public Base RPC
degrades badly under `--fork-url` write load.

Commit and push after every meaningful change, staging explicit paths
(`git add venues/ docs/build-log.md docs/active-work.md`) — never `-A`. Build-log entry for
every non-trivial decision, explaining the WHY.
```

</details>

---

## 8. Lane E — `web/`

**Headline: it has to survive a phone, and it has to say what it is.** The largest count of
feedback items lands here.

### E1 · Fully responsive

Measured, not guessed: **20 breakpoint utilities across the whole app**, and **21 of 35 components
have none at all** — including every decision component, the whole genesis flow, both charts, and
`DepositWithdraw`. The vault page is a desktop layout that reflows by luck.

Judges browse on phones. Target: 375px (iPhone SE) through 1440px, with the three tables — holdings,
execution steps, the decision feed — as the known-hard cases. A table that scrolls inside its own
container beats one that makes the page scroll sideways.

### E2 · Token logos

No image handling exists anywhere in `web/src` today. **Bundle the handful we need locally rather
than hot-linking a CDN** — a demo that renders broken images because a remote list rate-limited is a
worse outcome than no logos, and this is a trad-fi-styled UI where a missing logo should degrade to
a clean monogram, not a broken-image glyph.

### E3 · Holdings → donut, and hide what the vault does not hold

> *"Assets not used by the vault, we do not show in the Holdings, change to a donut."*

`AllocationChart.tsx` already renders a 100% stacked bar — the donut is a sibling, not a rewrite.
Filter zero balances. **Keep `committed_to_venue` visible in whatever replaces the list**: it flags
*encumbrance, not location*, and a judge who reads "committed" as "sent away" concludes
`totalAssets()` is wrong when it is exactly right.

### E4 · Genesis: presets, example buttons, and the universe up front

Three parts of one screen:
- **Preset cards** from `packages/schema/presets/` (F ships them) — click to load a whole mandate, then amend by talking.
- **Example responses as buttons** — suggested replies under the chat input, so a user who does not know the vocabulary is never facing an empty box.
- **The asset and venue universe rendered before the first question.** `GET /genesis/sources` now reports every registered source *and* every registered venue.

### E5 · Venue availability strip

*"1inch, Uniswap, Aave (show available venues on UI)."* Read D's capability manifest (§D1); render
what each venue does and whether it is reachable. Never a hardcoded list — that is precisely the bug
that hid Aave for a whole wave.

### E6 · Disclaimer

> *"Proof of concept for ETH Lisbon, do not send money to this."*

Persistent, in the header or as a dismissible top bar — visible on every page including a
deep-linked vault, because that is the page someone lands on from a shared URL.

### E7 · Docs drawer — move the constitutional text out of the vault view

> *"The agent holds AGENT_ROLE and executes directly. There is no human override after genesis — the
> mandate below is the only thing constraining it, and only the agent may amend it."*
> — belongs in a docs section, not the primary vault area.

The docs drawer should also answer **where the mandate lives**, which nothing currently states:
**the mandate is stored off-chain** as one JSON file per vault under `AGENT_STATE_DIR`; **only its
keccak hash is on-chain**, bound at deploy time. That hash is the depositor's entire verification
handle — R6 asserts the hash shown at genesis equals the on-chain `mandateHash`. Say both halves:
what is on-chain, and what is not.

### E8 · Aqua positions must be visible *and* the model must use them

The rendering is proven and a real ship reached the feed (`act_000020`). The gap is upstream and is
Lane B's (§B1). E's job: make an open Aqua position legible on the vault page — what is shipped,
which curve, the maker fee, and that the tokens never left.

### E9 · Banded acceptances

When B's soft band (§3.1/B3) accepts a decision that breached a constraint by ≤ the band, the feed
must say so. A band that is invisible in the UI is indistinguishable from no rule at all.

### E10 · Lint rule: `'wagmi'` may never be imported

Charlotte's `4602a0b` — `PortfolioStrip` imported the React hook `useAccount` from `'wagmi'`, but
this app mounts no `WagmiProvider`, so it threw and **took down the entire homepage**. She noted a
lint rule would prevent the recurrence and nothing currently does. Add it.

<details>
<summary><b>Continuation prompt — Lane E</b></summary>

```text
You are Lane E. You own `web/` and nothing else.

Read first, in order: CLAUDE.md, INSTRUCTIONS.md,
plans/2026-07-25-wave-2-six-lanes.md §8 (your section), docs/active-work.md
(request #58 is the homepage outage you are about to guard against; #46 and #51 are yours),
web/README.md.
Claim Lane E in docs/active-work.md before you write code.

The UI carries the most Wave 2 feedback. In rough priority order:

1. FULLY RESPONSIVE. Measured, not guessed: 20 breakpoint utilities in the whole app, and
   21 of 35 components have NONE — every decision component, the whole genesis flow, both
   charts, DepositWithdraw. Target 375px through 1440px. The three tables (holdings,
   execution steps, decision feed) are the hard cases: a table that scrolls inside its own
   container beats one that makes the page scroll sideways. Judges browse on phones.

2. TOKEN LOGOS. No image handling exists in web/src today. Bundle the few we need locally
   rather than hot-linking a CDN — a rate-limited remote list renders broken images mid-demo.
   Missing logo degrades to a clean monogram, never a broken-image glyph. This is a
   trad-fi-styled UI: light, serif headings, no neon, no pills.

3. HOLDINGS → DONUT, and hide assets the vault does not hold. AllocationChart.tsx already
   renders a 100% stacked bar, so the donut is a sibling, not a rewrite. Filter zero balances.
   KEEP `committed_to_venue` visible: it means encumbered, NOT sent away — the tokens stay in
   the vault, and a reader who misreads it concludes totalAssets() is wrong when it is right.

4. GENESIS GUIDANCE — preset cards from `packages/schema/presets/` (Lane F ships them),
   example replies as buttons under the chat input so nobody faces an empty box, and the
   asset + venue universe rendered BEFORE the first question. `GET /genesis/sources` now
   returns every registered source and venue.

5. VENUE AVAILABILITY STRIP — read Lane D's capability manifest. NEVER a hardcoded list:
   that exact shortcut hid the fully-built Aave venue for an entire wave.

6. DISCLAIMER — "Proof of concept for ETH Lisbon, do not send money to this." Persistent,
   visible on every page including a deep-linked vault, because that is where a shared URL
   lands someone.

7. DOCS DRAWER — move the AGENT_ROLE / no-human-override text out of the primary vault area.
   Also answer a question nothing currently answers: the mandate is stored OFF-CHAIN, one
   JSON file per vault; only its keccak hash is on-chain, bound at deploy. That hash is the
   depositor's entire verification handle. State both halves.

8. AQUA POSITIONS legible on the vault page — what is shipped, which curve, the maker fee,
   and that the tokens never left.

9. BANDED ACCEPTANCES — Lane B is adding a ±5% tolerance band. When a decision is accepted
   despite a small breach, the feed MUST say so. An invisible band is the same as no rule.

10. LINT RULE: `'wagmi'` may never be imported in this app. Importing the React hook
    `useAccount` from 'wagmi' threw WagmiProviderNotFoundError and took down the whole
    homepage (#58) — this app drives the wallet through @wagmi/core imperatively and mounts
    no provider. Use `@/lib/chain/account`. Nothing currently prevents the recurrence.

Boundaries: do not read or edit `agent/`, `data/`, `venues/`, `contracts/`. Do not edit
`packages/schema/` — file a request for Lane F.

`pnpm typecheck` must be clean before every push. JS dependencies must be ~6 months old and
EXACTLY pinned — supply-chain policy, and there is an audit script that enforces it against
the whole lockfile. Kill any stale `next dev` before `next build` or it dies with EPERM on
.next/trace.

Commit and push after every meaningful change, staging explicit paths
(`git add web/ docs/build-log.md docs/active-work.md`) — never `-A`. Build-log entry for
every non-trivial decision, explaining the WHY.
```

</details>

---

## 9. Lane F — integration

**Owns:** `packages/schema/`, `scripts/`, `tests/e2e/`, `docs/`, root config, and the running stack.
**Builds no product feature.** Everything here is either an unblock for someone else or a check on
the whole.

### F1 · The schema delta — §3, first, target 30 minutes

Then **announce it in `docs/active-work.md`** with the exact field names and defaults, because four
lanes are building against a shape they cannot see until it lands.

### F2 · Model bake-off — *"which LLM to use (better LLM)"*

The only Wave 2 item that is a measurement rather than a build, and it has already cost us: the 3B
**failed three attempts** at authoring an Aqua ship even with the intent shape in the prompt, and on
the last one wrote *"the current allocation of 50.0% USDC and 50.0% WETH does not match the target
allocations of 50.0% USDC and 50.0% WETH"* and proposed liquidating the whole WETH leg. `act_000020`
is in the feed with an honest caveat that **the decision was scripted, not model-authored**. That
caveat is the single weakest sentence in the submission.

Build a reusable harness (Rule 6 — parameterised, not a throwaway) that replays a fixed set of
snapshots through N candidate models and scores:

| Metric | Why it is the one that matters |
|---|---|
| **Valid structured output, first attempt** | Retries are the whole cost of a small model |
| **Constraint compliance** | How often layers 3–6 reject it |
| **Can it author an Aqua ship at all** | The 3B cannot. This is the go/no-go. |
| **Does it cite facts it was actually given** | Hallucinated `facts_used` breaks the data → reasoning → tx chain that is the product |
| **Latency on this hardware** | A model that needs a GPU we do not have scores zero |

Candidates: current 3B (baseline) · a 7–8B instruct · a 14B if it fits in RAM. The machine is a
CPU-only i5-8265U — **measure, do not assume.** If nothing local can author a ship, the honest
outcome is a documented finding, not a bigger download.

### F3 · Secrets audit

> *"Anything deployed on a server, secrets do not get leaked (at real deployment)."*

We already have the case study — `env.txt` in `408072f` via `git add -A`, eight live credentials,
and the purge correctly declined because the blob survives on GitHub by SHA regardless. Deliver a
**reusable pre-push check** (Rule 6) that fails on high-entropy strings and known key shapes in
staged content, plus `docs/secrets.md` covering what is exposed, the rotation order
(**PyPI `UV_PUBLISH_TOKEN` first** — it can push malicious versions of three packages already live),
and the standing rule that rotation, not rewriting, is the remediation.

### F4 · The stack, the request queue, and the rehearsal

- **F alone runs the shared stack** — anvil, ollama, the `:8000` API, the web dev server — and is the
  only lane that restarts them. Wave 1 had lanes killing each other's uvicorns in good faith.
- **F sweeps `docs/active-work.md`** every hour: route open requests to owners, close stale ones,
  and keep the numbering from colliding (it already has, twice).
- **F extends `tests/e2e/`** with the Wave 2 narrative — idle capital gets deployed; a banded
  acceptance is recorded; a persona cannot widen a constraint.
- **F runs `scripts/preflight.sh`** and is the single source of truth on whether the stack is
  demo-ready. Note the macOS bash 3.2 trap Charlotte fixed in `6f6b5be`: a `$( )` containing escaped
  quotes nested inside another `$( )` loses those escapes, and **the file's other `rpc` calls survive
  only because none contain braces** — anyone adding a brace hits it again.
- **F owns the final rehearsal**, timed, which is also the take that gets recorded.

<details>
<summary><b>Continuation prompt — Lane F (integration)</b></summary>

```text
You are Lane F, the integration lane. You are new this wave.

You own: `packages/schema/`, `scripts/`, `tests/e2e/`, `docs/`, root config, and the running
stack (anvil, ollama, the :8000 API, the web dev server). You build NO product feature.
Everything you do is either an unblock for another lane or a check on the whole.

Read first, in order: CLAUDE.md, INSTRUCTIONS.md,
plans/2026-07-25-wave-2-six-lanes.md — the WHOLE file, not just §9, because you arbitrate
between the other five — docs/active-work.md, plans/2026-07-25-e2e-local-deployment.md.
Claim Lane F in docs/active-work.md before you write code.

You are the ONLY lane that may edit `packages/schema/`. In exchange you commit to a
30-MINUTE TURNAROUND on schema requests during this wave. A frozen schema with a slow owner
is worse than one with no owner: it looks unblocked and is not.

TASK 1 — DO THIS FIRST, TARGET 30 MINUTES. Ship the Wave 2 schema delta from §3:
  - `MandateConstraints.tolerance_band_pct: float = 0.05`
  - `Mandate.persona: Persona | None` (shape in §3.2)
  - `packages/schema/presets/*.json` — three archetypes, validated against the Mandate
    schema by the existing conformance test so a preset can never be un-deployable
  - do NOT widen `permitted_venues` until Lane D confirms bytecode on the fork
Remember the schema has THREE mirrors that must not drift: the JSON Schema (source of
truth), the pydantic models, and the zod mirrors. Then ANNOUNCE it in docs/active-work.md
with exact field names and defaults — four lanes are building against a shape they cannot
see until you land it.

TASK 2 — MODEL BAKE-OFF. The only Wave 2 item that is a measurement, and the most valuable
thing you will do. The 3B failed three attempts at authoring an Aqua ship even with the
intent shape in the prompt; on the last it wrote "the current allocation of 50.0% USDC and
50.0% WETH does not match the target allocations of 50.0% USDC and 50.0% WETH" and proposed
liquidating the whole WETH leg. `act_000020` is in the decision feed carrying an honest
caveat that the decision was SCRIPTED, not model-authored. That caveat is the weakest
sentence in the submission and this task is what removes it.
Build a REUSABLE parameterised harness (Rule 6 — not a throwaway script) that replays fixed
snapshots through N models and scores: valid structured output first attempt; constraint
compliance; CAN IT AUTHOR AN AQUA SHIP AT ALL (the go/no-go); does it cite facts it was
actually given; latency. The machine is a CPU-only i5-8265U — measure, do not assume. If no
local model can author a ship, a documented finding is the honest outcome, not a bigger
download.

TASK 3 — SECRETS AUDIT. We have the case study: `env.txt` committed in `408072f` via
`git add -A`, eight live credentials, purge correctly DECLINED because the blob stays
fetchable on GitHub by SHA regardless. Deliver a reusable pre-push check that fails on
high-entropy strings and known key shapes in staged content, plus `docs/secrets.md` with the
rotation order — PyPI `UV_PUBLISH_TOKEN` FIRST, because it can push malicious versions of
three packages that are already live — and the standing rule that rotation, not rewriting,
is the remediation.

TASK 4 — ONGOING, for the whole wave:
  - You alone restart the shared stack. Wave 1 had lanes killing each other's uvicorns in
    good faith.
  - Sweep docs/active-work.md hourly: route open requests to owners, close stale ones, stop
    the request numbering colliding (it already has, twice).
  - Extend tests/e2e/ with the Wave 2 narrative: idle capital gets deployed; a banded
    acceptance is recorded; a persona cannot widen a constraint.
  - Run scripts/preflight.sh; you are the single source of truth on demo-readiness. macOS
    trap: under bash 3.2 a $( ) containing escaped quotes nested in another $( ) loses those
    escapes — the file's other rpc calls survive only because none contain braces.
  - Own the final timed rehearsal, which is also the recorded take.

Boundaries: you own the seam, NOT the lanes. Do not edit `contracts/`, `agent/`, `data/`,
`venues/`, `web/`. When you find a bug in one, file it as a request with the diagnosis —
that is more useful than a patch and it keeps attribution intact.

NEVER force-push. In Wave 1 I rewrote three commits and pushed --force-with-lease AFTER the
decision to decline a purge had been recorded in docs/active-work.md, breaking four clones
to no benefit. Read the request table before any history operation.

Commit and push after every meaningful change, staging explicit paths — never `-A`, the
command that caused the leak. Build-log entry for every non-trivial decision, with the WHY.
```

</details>

---

## 10. Sequencing

```
T+0:00  F  schema delta  ──────┐  (four lanes blocked on this — it is genuinely first)
        A  security review     │  independent
        C  source notes        │  independent
        D  capability manifest │  independent
        E  responsive pass     │  independent
T+0:30  F  announce delta  ────┘
        B  starts (idle capital first, personas + band once the delta lands)
        E  presets + venue strip once F's presets and D's manifest exist
T+1:30  D  prediction-market gate — go / no-go, reported to F immediately
T+2:00  F  model bake-off (needs a quiet machine; the CPU is the bottleneck)
T+4:00  F  e2e for the Wave 2 narrative; request-queue sweep
T+6:00  F  full timed rehearsal
```

**Only two real dependencies:** everyone → F's schema delta (30 min), and E's venue strip → D's
manifest (small, first thing in D). Everything else runs concurrently. The prediction-market gate is
deliberately early so a "no" costs 90 minutes rather than a lane.

---

## 11. Definition of done

- [ ] **A tick deploys idle capital into a lending venue or Aqua, model-authored, in the feed** — with the reasoning citing the idle-capital fact. *This is the single most important box.*
- [ ] `act_0000NN` in the feed **without** the "the decision was scripted" caveat — or a documented finding that no locally-runnable model can author one
- [ ] Two vaults with visibly different personas making visibly different decisions **from the same snapshot**, with a test proving neither can widen a constraint
- [ ] A banded acceptance recorded on an `AgentAction` and rendered in the feed
- [ ] `contracts/SECURITY.md` published; invariant suite green; the donation attack tested rather than asserted
- [ ] A source note reading *"chainlink — USDC: price is 24.5h old — the agent should treat it as stale"*
- [ ] Genesis offers presets and example buttons; the universe is visible before the first question
- [ ] The app is usable at 375px, end to end
- [ ] Disclaimer on every page; the AGENT_ROLE text lives in a docs drawer that also says where the mandate is stored
- [ ] Prediction markets reachable as facts (C) — and as a venue (D) only if the gate passed
- [ ] Secrets pre-push check in place; `docs/secrets.md` published with the rotation order
- [ ] `preflight.sh` 6/6; e2e green; one timed rehearsal

---

## 12. Deferred — named so nobody quietly starts one

From the feedback, explicitly **not** in Wave 2:

- **Crystal Ball** — top-performing vaults across the ecosystem. Wave 1's peer source is the local
  version of this; the ecosystem-wide version needs an external API we have not evaluated.
- **Data-source selection and funding via x402** — letting the agent *buy* data with its own capital.
  Conceptually the best idea on the list and the most work: x402 is signature-verified against the
  live gateway already, so the remaining piece is the agent deciding a query is worth $0.01. Wave 3.
- **Agent in a multisig** — changes the custody model. Pattern 1 (vault as sole custodian) is load-
  bearing for the Aqua claim and for R5's proof; do not touch it during a hackathon.

**Still human-only, in this order:** rotate the eight leaked credentials (PyPI token first) → flip
the repo public → record the 2–4 minute video → submit the Uniswap Developer Feedback Form →
confirm the two Continuity tracks at the sponsor booth.
