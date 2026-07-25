# Model bake-off

**Purpose.** Answer, by measurement rather than anecdote, which locally-runnable model can actually
drive this harness — and specifically whether one can author an Aqua ship, which is the claim
`act_000020` currently has to caveat.

## Usage

```bash
uv run python -m scripts.bakeoff --check                       # what can this machine run?
uv run python -m scripts.bakeoff --list                        # the scenarios, and why each exists
uv run python -m scripts.bakeoff --models qwen2.5:3b-instruct-q4_K_M --trials 3
uv run python -m scripts.bakeoff --models a,b --scenarios balanced-ship --json results.json
```

| Flag | Meaning |
|---|---|
| `--models` | Comma-separated ollama tags. Must already be pulled — this will not download gigabytes on your behalf. |
| `--scenarios` | Default all four. |
| `--trials` | Attempts per scenario, default 3 — matching the harness's own retry budget. |
| `--temperature` | Default `0.0`: a capability measurement should not pass by sampling luck. |
| `--json` | Every trial, including the model's own reasoning, for a human to sanity-check a suspiciously good score. |

## What it measures, and how

Everything is scored **structurally**. Nothing is graded by reading the model's prose, because the
harness does not read prose either — it validates, checks constraints, and submits calldata.

| Metric | Decided by |
|---|---|
| Valid on first attempt | Lane B's `validate_decision` — if it raises, the real harness would have retried |
| Mandate compliance | Lane B's `check_decision`, **conditioned on validity** so a model that emits nothing is not reported as proposing illegal trades |
| Right shape / **can it author a ship at all** | Does the decision carry the intent kind the scenario needs |
| Invented facts | `facts_used` against the snapshot's real ids |
| Latency | Wall clock on this hardware |

The prompt comes from `decision_messages`, the structured-output schema from `decision_schema`,
both Lane B's. **A bake-off that built its own prompt would be measuring the bake-off.**

## The scenarios

| Key | Book | Right answer | Why it is here |
|---|---|---|---|
| `idle-cash` | all USDC, lending-only mandate | `supply` | Nothing to rotate, nothing to rebalance — lending is the only action, so holding declines the mandate's stated purpose |
| `balanced-ship` | 50/50, exactly on target, Aqua permitted | `ship` | The exact situation the 3B failed three times (#51b) |
| `drifted` | 80/20 against a 60% cap | `swap` | Direction is unambiguous; a wrong-way trade has reached chain before (#27) |
| `already-deployed` | floor met, rest committed | `hold` | **The control.** Without it the harness rewards action, and a model that always trades scores well while churning |

## Results — 2026-07-25, Wave 3, both backends

```bash
uv run python -m scripts.bakeoff --backend grok --trials 3      # hosted; reads XAI_API_KEY
uv run python -m scripts.bakeoff --models qwen2.5:3b-instruct-q4_K_M --trials 3
```

| Model | Valid 1st attempt | Mandate-compliant | Right shape | **Authored a ship** | Invented facts | Median latency |
|---|---|---|---|---|---|---|
| `qwen2.5:3b-instruct-q4_K_M` | 67% | 100% | 42% | ❌ *(see below)* | 0 | 56s |
| `grok-4.20-0309-non-reasoning` | 58% | 100% | 58% | ❌ *(see below)* | 0 | **2s** |

**The ship column is a fact about this scenario, not about the model.** Both models have the
capability; the live journal has three 3B-authored ships that executed on chain. Read the next
section before quoting that ❌ anywhere.

> ⚠️ **The two rows are not a fair A/B and must not be quoted as one.** Lane B rewrote the decision
> prompt between them (Wave 3 added the `enter` action and the untrusted-text fencing), so the 3B's
> numbers were measured against a different prompt. **Latency and the ship column are comparable;
> the validity rate is not.** Re-run the 3B if a like-for-like number is ever needed — the harness
> is one command, which is why it is a harness.

### What this scenario measures, and what it does not

Neither model authored an Aqua ship here — nought for six, on a scenario built to invite one. Grok
returned `supply` on the idle leg 3/3, which is a defensible answer and is exactly why
`balanced-ship` accepts it, and is not a ship.

**Do not read that as "the model cannot author a ship." It is false, and the live journal disproves
it.** Checked against the running vault rather than inferred:

| Action | Backend | Retries | On-chain |
|---|---|---|---|
| `act_000036` | `qwen2.5:3b` | **0** | executed |
| `act_000046` | `qwen2.5:3b` | 2 | executed |
| `act_000049` | `qwen2.5:3b` | 1 | executed |
| `act_000020` | `scripted` | 0 | executed — **not model-authored**, and the one the audit rightly caveated |

**The 3B has authored three Aqua ships that executed on chain, one of them first try.** So the
Wave 2 sentence — *"the 3B cannot author a market-making decision"* — was wrong, and this harness
came within one commit of hardening it into a submission claim.

The difference is the harness, not the model. This bake-off measures **single-shot authoring at
temperature 0 on one synthetic book**; the live loop **retries**, and two of the three ships above
needed a retry. A scenario that disagrees with production is evidence about the scenario.

So the defensible statements are narrow ones:

- **`balanced-ship` does not reproduce whatever the live book supplies**, and should be treated as a
  scenario bug rather than as a capability finding until it does. Filed as such.
- The ship intent is **harder to author single-shot** than `swap` or `supply`, across two very
  different models. That is a real signal about the prompt, and it is the reason the retry budget
  exists.
- What the submission may say is what Lane D's on-chain work and this journal both support: **the
  vault ships and docks real Aqua positions in SwapVM/Aqua mode, and a model authored those ships.**

### ⚠️ This column was wrong until Wave 3, and the way it was wrong is worth knowing

`balanced-ship` declares `wanted_intents = ("ship", "supply")`. The column is labelled **"Authored a
ship"** and was computed with `can_author()`, which asks *did it author **any** wanted intent* — so a
model that only ever supplies scored ✅.

**The 3B never exposed it.** Its output on that scenario was invalid with empty intents, so the
column read ❌ for the right answer entirely by accident. Grok made it read ✅ while authoring zero
ships, and that tick was one line from going into the submission audit as evidence.

A metric that is only correct when the model fails is not a metric. `can_author_intent(scenario,
kind)` now asks for the kind by name. Re-scoring the stored 3B trials under the corrected metric
leaves its ❌ unchanged, which is the check that the fix did not simply invert the answer.

### Per scenario

| Scenario | `qwen2.5:3b` | `grok-4.20` |
|---|---|---|
| `idle-cash` | 2/3 supplied | 1/3 — two trials emitted `target_allocations` summing to 0.25 |
| `balanced-ship` | **0/3**, empty intents, rejected as *"nothing would happen"* | **3/3 `supply`, 0 ships** |
| `drifted` | 3/3 correctly-directed `swap` | 3/3, one pairing the swap with a `supply` |
| `already-deployed` *(control — `hold`)* | **0/3 held**, traded every time | **0/3 held**, and 2 of 3 were *blocked by the gate* |

**Neither model ever holds.** That was the strongest Wave 2 argument for the reflection scoreboard
and it survives contact with a much better model.

But the control scenario now says something sharper than it did. The 3B churned while remaining
100% mandate-compliant — churn breaks no numeric limit. **Grok did not: two of its three attempts
proposed taking WETH to 80% against a 60% single-position ceiling, and layer 5 rejected both** with
*"this trade would take WETH to 80.0%, above the 60% single-position ceiling. Buy less."* On a book
that needed no trade at all. That is the validation stack catching a frontier model proposing an
over-limit trade, on a scenario whose correct answer was to do nothing — and it is a better piece of
evidence for the gate than anything in the Wave 2 run.

**Zero invented facts across all 24 trials, both models.** The `facts_used` → snapshot chain the
dApp renders holds up even where the decisions do not.

### Cost and speed

Grok is **~28× faster** — 2s against 56s median — which is what makes §B1's generate-check-regenerate
loop practical at all. Under the 3B, one archetype click would have been three retries and a minute.

---

## Wave 2 results — 3B only, superseded by the table above

| Model | Valid 1st attempt | Mandate-compliant | Right shape | Authored a ship | Invented facts | Median latency |
|---|---|---|---|---|---|---|
| `qwen2.5:3b-instruct-q4_K_M` | 67% | 100% | 42% | ❌ | 0 | 56s |

Per scenario, and this is where the number stops being one number:

| Scenario | Result |
|---|---|
| `idle-cash` | **2 / 3 authored a `supply`.** The 3B *can* deploy idle capital into a lending venue, unaided. |
| `drifted` | **3 / 3 authored a correctly-directed `swap`.** |
| `balanced-ship` | **0 / 3.** Every attempt returned `rebalance` with an empty `venue_intents`, rejected by the harness with *"nothing would happen"*. |
| `already-deployed` | **0 / 3 held.** It proposed a swap every time, on a book that was already correctly deployed. |

### Three findings

**1. The Aqua ship is a real capability gap, now measured rather than recalled.** Three attempts in
Wave 1 was an anecdote; 0/3 against a scenario built specifically to invite the answer, with the
intent shape in the prompt, is a finding. The honest sentence for the submission is that the 3B
authors lending and rebalancing decisions but cannot author a market-making one.

**2. The 3B never holds — and that is not a constraint violation.** On the control scenario it
traded 3/3 times while remaining 100% mandate-compliant, because churn breaks no numeric limit.
Compliance is not judgment. This is the strongest available argument for the reflection scoreboard
and for `hold` being a first-class answer in the prompt rather than a rule in the gate: the gate
cannot see this, and did not.

**3. Zero invented facts across twelve trials.** The `facts_used` → snapshot chain that the dApp
draws holds up even where the decisions do not.

### Why no larger candidate was benchmarked here

Measured, not assumed: **1.1 GB free against 33.5 of 37.9 GB committed.** A 7B q4 needs ~5.5 GB
resident, so loading one would page — and the same memory is holding anvil's fork state and the
API that four lanes read. A latency number measured against the swap file is worse than no number,
and destabilising the shared stack to get one would cost more than the answer is worth.

`--check` reports this, and distinguishes a model already resident (free to benchmark) from one
that must be loaded. **On a machine with 8 GB free, `--models qwen2.5:7b-instruct-q4_K_M` is the
one command that settles it** — which is exactly why this is a harness and not a script that
answered one question once.
