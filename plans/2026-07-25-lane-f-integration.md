# Lane F — integration plan

**Date:** 2026-07-25 · **Working from:**
[Wave 2 §9](2026-07-25-wave-2-six-lanes.md) · **Owns:** `packages/schema/`, `scripts/`,
`tests/e2e/`, `docs/`, root config, and the running stack.

Lane F builds no product feature. Every item below is either an unblock for another lane or a
check on the whole. Where F finds a bug inside a lane, F files a request with the diagnosis
rather than a patch — that keeps attribution intact and keeps Rule 7 real for the other five.

---

## The one promise this lane makes

**F is the only lane that may edit `packages/schema/`, and in exchange schema requests turn
round in 30 minutes.** A frozen schema with a slow owner looks unblocked and is not. Requests
arrive as rows in [docs/active-work.md](../docs/active-work.md); F sweeps that table hourly.

The schema has **three mirrors that must not drift** — JSON Schema (source of truth),
`python/curator_schema/models.py`, `ts/src/index.ts` — plus the conformance test that catches
a mirror somebody forgot. Every delta touches all three in one commit or it is not done.

---

## F1 · The Wave 2 schema delta — first, target 30 minutes

Four lanes are blocked on this, so it ships before anything else and gets announced with exact
field names the moment it lands.

| Change | Shape | Consumed by |
|---|---|---|
| `MandateConstraints.tolerance_band_pct` | `float = 0.05`, range 0–0.5 | B (band logic), E (render) |
| `Mandate.persona` | `Persona \| None` — `name`, `voice`, `biases[]`, `conviction` | B (prompt), E (display) |
| `AgentAction.warnings` | `list[ConstraintWarning]` | B (populate), E (feed) |
| `packages/schema/presets/*.json` | three `Mandate`-valid archetypes | B (genesis), E (cards) |
| `permitted_venues` | **unchanged** until D confirms bytecode | — |

**Why `AgentAction.warnings` is in the delta even though §3.1 does not name a field for it.**
§3.1 requires every banded acceptance to be visible in three places — the `AgentAction`, the
decision feed, and the reflection — and says that visibility requirement is *the whole reason
this is a schema change and not a constant in B's code*. There is currently nowhere on
`AgentAction` for a warning to live: `error: str | None` is for the failure that stopped a
cycle, and overloading it would make a banded acceptance indistinguishable from a rejection in
the feed. A structured warning is also what lets E render *which* constraint was breached and
by how much, rather than a sentence B has to pre-format. Without this field the band is
invisible, and an invisible band is the same as no rule.

**Preset naming.** Named after what they do, not after a firm we do not speak for:
`conservative-income`, `balanced-two-asset`, `opportunistic`. Both B's prompt and E's buttons
read the same files, so the model's recommendation and the user's click cannot diverge.

**Presets are validated by the conformance test**, so a preset can never be un-deployable.
They live in `presets/`, not `fixtures/`, because `test_every_fixture_is_covered` asserts the
fixture directory matches its case table exactly — presets are a second, separately-validated
set with their own rule: every preset must satisfy `Mandate` *and* the cross-field invariants
that a hand-written mandate can get wrong (base asset in allowed assets, weights that leave
room for the cash floor, no venue without an adapter).

## F2 · Model bake-off

The only Wave 2 item that is a measurement rather than a build, and the one that removes the
weakest sentence in the submission: `act_000020` carries an honest caveat that *the decision
was scripted, not model-authored*, because the 3B failed three attempts at authoring an Aqua
ship even with the intent shape in the prompt (#51b).

Reusable and parameterised (Rule 6) — `scripts/bakeoff/`, driven by a config of candidate
models and a fixed snapshot set, not a script per run. Scores five things:

1. **Valid structured output, first attempt** — retries are the entire cost of a small model.
2. **Constraint compliance** — how often layers 3–6 would reject it.
3. **Can it author an Aqua ship at all** — the go/no-go. The 3B cannot.
4. **Does it cite facts it was given** — a hallucinated `facts_used` breaks the
   data → reasoning → tx chain that *is* the product.
5. **Latency on this hardware** — CPU-only i5-8265U. A model needing a GPU scores zero.

Candidates: the current 3B as baseline, a 7–8B instruct, a 14B if it fits in RAM. **Measure,
do not assume.** If nothing locally runnable can author a ship, the honest deliverable is a
documented finding, not a bigger download.

## F3 · Secrets audit

The case study is ours: `env.txt` committed in `408072f` via `git add -A`, eight live
credentials, and a history purge correctly **declined** because the blob stays fetchable on
GitHub by SHA regardless (#53, #55). Two deliverables:

- a **reusable pre-push check** that fails on known key shapes and high-entropy strings in
  staged content — installable as a hook, runnable by hand, and runnable over history;
- `docs/secrets.md` — what is exposed, the rotation order with **PyPI `UV_PUBLISH_TOKEN`
  first** (it can push malicious versions of three packages already live), and the standing
  rule that **rotation, not rewriting, is the remediation**.

## F4 · The seam, ongoing

- **F alone restarts the shared stack** — anvil, ollama, `:8000`, web dev. Wave 1 had lanes
  killing each other's uvicorns in good faith.
- **Hourly sweep of `docs/active-work.md`** — route open requests, close stale ones, keep the
  numbering from colliding (it has, twice). Next free request number: **60**.
- **`tests/e2e/` gains the Wave 2 narrative** — idle capital gets deployed; a banded
  acceptance is recorded; a persona cannot widen a constraint.
- **`scripts/preflight.sh`** is the single source of truth on demo-readiness. macOS trap from
  `6f6b5be`: under bash 3.2 a `$( )` containing escaped quotes nested inside another `$( )`
  loses those escapes. The file's other `rpc` calls survive **only because none contain
  braces** — anyone adding one hits it again.
- **The final timed rehearsal**, which is also the recorded take.

---

## Two rules F holds itself to

**Never force-push.** In Wave 1 an instance rewrote three commits and pushed
`--force-with-lease` *after* the decision to decline a purge was recorded in the request table
(#55). It broke four clones for no benefit. Read the table before any history operation.

**Stage explicit paths, never `-A`.** That command caused the leak in #53 and swept three
lanes' work into the wrong commits in both directions (#14, #21). F's staging is
`git add packages/schema/ scripts/ tests/ docs/ plans/` — the paths F owns, named.

---

## Order of work

```
F1  schema delta + announce      ← blocks four lanes, so it is genuinely first
F3  secrets check                ← independent, and needed before the repo goes public
F2  bake-off                     ← wants a quiet machine; runs while lanes build
F4  e2e narrative, sweeps, rehearsal
```
