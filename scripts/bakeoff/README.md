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

## Results — 2026-07-25, i5-8265U, CPU only, 4 scenarios × 3 trials

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
