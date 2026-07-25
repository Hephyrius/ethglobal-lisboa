# Wave 3 · Lane F — the envelope, the audit, and an attack on ourselves

**Lane:** F (integration). **Owns:** `packages/schema/`, `scripts/`, `tests/e2e/`, `docs/`, root
config, the running stack. **Builds no product feature.** Every item below is either an unblock for
another lane or a check on the whole.

Follows [the Wave 3 plan](2026-07-25-wave-3-archetypes-security-audit.md) §8, and
[Wave 2's Lane F plan](2026-07-25-lane-f-integration.md).

---

## Order of work, and why this order

| | Item | Why here |
|---|---|---|
| 1 | **Archetype envelope schema** | Blocks B1 and E1. Nothing else I do is on anyone's critical path. |
| 2 | Announce the exact field names | The 30-minute promise is worthless if the names arrive late |
| 3 | **The bounty audit** | Submission-critical, and the one deliverable a judge reads directly |
| 4 | Re-run the bake-off against Grok | The published table predates the backend change — it is currently wrong |
| 5 | **The injection e2e** | Needs B's defence and C's field list, so it cannot go first |
| 6 | Stack, queue sweep, preflight, rehearsal | Continuous |

---

## 1 · The envelope (§F1)

### A defect that has to be fixed first

`permitted_venues` is a closed enum in all three mirrors: `["uniswap", "aqua", "aave"]`. Lane D
shipped **`morpho`** in Wave 2 — `venues/registry.py`, `venues/capabilities.py`, a `SupplyIntent`
and a `WithdrawIntent` path — and `venues/README.md` publishes
`VENUES = ("uniswap", "aqua", "aave", "morpho")` with the instruction to *"validate mandates against
them"*.

**Against the schema, that validation rejects morpho.** No mandate can name the fourth venue, so a
working, tested, deployed integration is unreachable from every vault in the system. The plan's own
sketched envelope (`permitted_venues ⊆ {aave, morpho}`) is unsatisfiable until this changes.

The enum was kept closed on purpose — a mandate naming a venue with no adapter produces an agent
whose every proposal the harness must reject. That reasoning is still right; it argues for *adding
the venue that does have an adapter*, not for opening the enum to free strings.

### The design: an envelope is the Mandate's own field names, widened

An archetype is **bounds**, not a template. The thing that keeps it honest is that its field names
are the *mandate's* field names:

```
Mandate.constraints.min_cash_pct : 0.30        one number
Archetype.constraint_ranges.min_cash_pct : {min: 0.20, max: 0.40}    the interval it must fall in
```

So the check is mechanical — iterate the range keys, look up the same key on the mandate, test
containment. There is no hand-written mapping table to drift, and **a constraint added to the
mandate schema with no range in the envelope is a visible hole rather than a silent pass** (the
conformance test asserts every numeric constraint is ranged).

Three bound kinds, and that is all:

| Kind | Fields | Meaning |
|---|---|---|
| `set_bound` | `allowed_assets`, `permitted_venues`, `permitted_data_sources` | `subset_of` (the ceiling), `must_include` (the floor), `min_count`/`max_count` |
| `range` | everything under `constraint_ranges` | closed interval, inclusive both ends |
| enum list | `risk_posture` | the postures this archetype admits |

### Why the card copy lives on the archetype, not on the index

`presets/` puts `headline` and `tradeoff` on the *index* and keeps the file a plain `Mandate` —
correct there, because the file has to validate as a Mandate and has nowhere to put them.

An archetype is its own document, so the copy goes **on it**. The index then carries only keys and
paths. That deletes an entire class of drift: there is no second place where a card's promise could
disagree with the bounds the gate enforces.

### Uniqueness has to be structural

*"Two clicks on the same card must produce two different vaults"* cannot rest on temperature. The
envelope therefore ships `emphases` — at least three materially different angles, pinned distinct by
a test — so B has a rotating seed that comes from the interface rather than from B's own code. A
nonce and the live snapshot are B's to add; the emphasis list is the part that belongs to the shared
contract, because E's card copy and B's generation must be describing the same archetype.

### One gate, two readers

The plan asks for *"one implementation, used by B to gate deployment and by E to describe the card"*.
Literally one is impossible across Python and TypeScript. What is possible, and is what ships:

- **The gate is Python only** — `check_envelope()`. B calls it. Nothing in TypeScript decides whether
  a mandate may deploy, so there is no second gate to disagree with the first.
- **TypeScript gets the type and a describer** that generates its lines *mechanically from the same
  JSON*. E writes no prose about bounds. A card cannot promise a number the envelope does not hold,
  because no human types the number into the card.

### Tests that would actually catch a mistake

- Index ↔ directory agree **both ways** (the `presets/` lesson: listed-but-missing and
  present-but-unoffered are different bugs)
- **Both corners materialise.** Build a mandate from the minimum of every range and one from the
  maximum, and assert each validates as a `Mandate` *and* passes `check_envelope`. An envelope whose
  extremes produce an invalid mandate is a trap laid for whoever generates inside it.
- Every numeric constraint on `MandateConstraints` has a range — no silent holes
- One escape per bound kind is caught, and the violation **names the field and both numbers**
- Every asset, venue and source named in any envelope actually resolves in the system that will be
  asked to trade it

---

## 2 · The audit (§F2)

Four criteria per track. Criterion 3 — *if this integration were removed, would the product still
work?* — is the one that decides whether we are fixing or dropping.

Two inherited claims to re-verify rather than copy forward: the bake-off table predates the Grok
backend, and B closed the "the decision was scripted" caveat.

---

## 3 · The injection e2e (§F3)

Deploy a vault whose **name is the payload**, let the `peers` source carry it into the prompt, assert
the agent does not comply. The assertion has to be about *behaviour* — the decision it returns —
because "the detector fired" only proves the detector fired.

---

## Boundaries

I own the seam, not the lanes. A bug in `contracts/`, `agent/`, `data/`, `venues/` or `web/` gets
**filed with the diagnosis**, which is more useful than a patch and keeps attribution intact.
