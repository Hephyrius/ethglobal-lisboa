# Build Instructions for Claude Code

Operating rules for how to build in this repository. These are **not** suggestions —
follow them on every task. If a rule and a user request conflict, stop and ask.

The guiding intent behind all of these: we are building many components in parallel
and wiring them together later. Everything below exists to make that integration
painless — so decisions are traceable, code is modular, structure is legible, and
every component tells its neighbors exactly how to use it.

---

## Rule 1 — Keep a build log

Maintain a running decision log so we can always reconstruct **what** changed and
**why**.

- **Location:** `/docs/build-log.md` (append-only; newest entries at the top).
- **When:** add an entry whenever you make a non-trivial change — adding a dependency,
  choosing a library or pattern, structuring a component, making a design tradeoff, or
  deviating from the plan.
- **Each entry must include:**
  - **Date / task** — what you were doing.
  - **What changed** — the concrete change, in a sentence or two.
  - **Why** — the reasoning. *This is the important part.* Especially: why this
    library over alternatives, why this pattern, what tradeoff you accepted.
  - **Alternatives considered** — briefly, if you rejected an obvious option, say why.

Do not silently pick a library or architectural approach. If you chose it, the log
explains why.

---

## Rule 2 — All plans live in the repo

Any plan you produce — implementation plans, refactor plans, design sketches — gets
written to the repository, not just left in chat.

- **Location:** `/plans/`
- **Format:** one Markdown file per plan, dated and clearly named
  (e.g. `/plans/2026-07-25-vault-contracts.md`).
- Plans are living documents: if the approach changes materially during
  implementation, update the plan (and note the change in the build log).

---

## Rule 3 — Modular code, never monolithic

No single file does everything. No thousand-line files.

- **One responsibility per module.** A file should have a single, nameable job. If you
  can't summarize what a file does in one sentence without "and," split it.
- **Soft size ceiling:** if a file grows past a few hundred lines, treat that as a
  signal to break it apart — not a hard limit, but a prompt to reconsider.
- **Favor small, composable units** — functions and modules that do one thing and can
  be tested and reused independently.
- **No dumping ground files.** Avoid catch-all `utils.js` / `helpers.py` that
  accumulate unrelated logic. Group by purpose.
- Prefer clear interfaces between modules over tight coupling, so pieces can be built
  and changed in isolation.

---

## Rule 4 — Organize the folder structure by component

Structure the repository by component and concern, not as a flat pile of files.

- **Group by component / domain**, each in its own directory (e.g. contracts, the
  agent harness, the model layer, data-source adapters, the strategy builder — each
  gets its own home).
- **Do not** put every script in one folder, or scatter related code across unrelated
  places.
- Within a component, subdivide sensibly (e.g. separate interfaces, implementation,
  and tests) rather than flattening everything into one directory.
- Names should make location obvious: someone should be able to guess where a piece of
  code lives from what it does.
- When you introduce a new top-level component, note its purpose in the build log.

---

## Rule 5 — Every component has a usage document

This is the rule that keeps parallel development from breaking at integration time.

Each component maintains **one** document describing how to use it — its contract with
the rest of the system.

- **Location:** a `README.md` (or `USAGE.md`) at the root of each component's directory.
- **One per component. Keep it current** — update it in the same change that alters the
  component's interface.
- **Each usage doc must cover:**
  - **Purpose** — what this component is responsible for, in a few sentences.
  - **Public interface** — the functions / methods / endpoints / contract calls other
    components use, with inputs and outputs. This is the part other components depend
    on; be precise.
  - **Inputs & outputs / data shapes** — the exact shapes crossing the boundary
    (schemas, types, event/return formats).
  - **Dependencies** — what this component needs from other components or external
    services.
  - **Usage example** — a minimal example of calling it correctly.
  - **Assumptions & invariants** — anything a caller must guarantee or can rely on
    (e.g. "vault is always custodian," "outputs are validated before this point").

Treat these docs as the integration surface. When two components wire together, their
usage docs — not the source code — should be enough to connect them correctly.

---

## Rule 6 — No throwaway scripts

Do not litter the repository with single-use, one-off scripts. A repo should not
accumulate hundreds of scripts each doing one narrow job once.

- **Prefer reusable, parameterized tooling.** If a task might recur, write it once as a
  proper tool with arguments/config — not a new hardcoded script each time. One
  parameterized script beats ten near-duplicates.
- **Before writing a new script, check for an existing one** that does the job or can
  be extended. Extend or generalize it rather than creating a parallel near-copy.
- **One-off exploration stays ephemeral.** For genuine one-time needs — a quick check,
  a data peek, debugging — run it inline (REPL, shell one-liner, scratch buffer). Do
  **not** commit it to the repo. If you must write a scratch file, keep it out of the
  committed tree (e.g. a git-ignored `scratch/` area) and clean it up.
- **If a script earns a permanent place, it must earn it properly** — reusable, placed
  in the correct component folder (Rule 4), and documented. If it doesn't meet that
  bar, it shouldn't be committed.
- **Migrations / one-time operational scripts** are the exception: if one is genuinely
  needed, put it in a clearly named location (e.g. `scripts/migrations/`), note it in
  the build log, and mark whether it's safe to remove after use.

The test: *would this file still be useful next week, to someone else?* If no, it
shouldn't be committed as a permanent script.

---

## Rule 7 — Parallel agents: stay in your lane

Multiple agents may be working on this repository at the same time. Components are
built in parallel, so **strict separation between components is mandatory.** If one
agent is working on the smart contracts, another agent must not touch the contracts —
and the same goes for every component. Crossing these boundaries is the single most
likely way to create conflicts and corrupt each other's work. Do not do it.

**Claim before you build.**
- Before starting work on a component, register it in `/docs/active-work.md` — record
  the component, what you're doing, and a timestamp.
- **Before touching any component, read that file first.** If another agent has an
  active claim on it, **do not touch it.** Work on something else or wait.
- Release the claim (mark it done/removed) when you finish.

**Stay inside your claimed component.**
- Only edit files within the component you have claimed. Do **not** reach into another
  component's directory to make changes — not even a "quick fix."
- If your work needs a change in another component, **do not edit it yourself.** Instead:
  depend on that component's documented interface (its usage doc, Rule 5); and if the
  interface itself needs to change, record the request (in `/docs/active-work.md` or an
  agreed handoff note) and let the owning agent make it. Flag the dependency; don't
  cross the boundary.

**Cross-component work goes through interfaces, never internals.**
- Components integrate through their published usage docs (Rule 5), not by one agent
  editing another's implementation. If you can't do your task without reading or
  changing another component's internals, that's a signal to stop and coordinate.

**Be careful with shared files.**
- A few files are shared by everyone: `/docs/build-log.md`, `/docs/active-work.md`, and
  `/plans/`. **Append; never rewrite or reformat the whole file.** Add your entry and
  leave the rest untouched, so you don't clobber another agent's edits.
- Never delete or restructure another agent's entries.

**If in doubt, stop.** Uncertain whether something is yours to touch? Assume it isn't,
and coordinate before acting. A brief pause is cheaper than two agents overwriting each
other.

---

## Definition of Done (check every task against this)

A change is not complete until:

- [ ] You claimed the component and stayed within its boundary; no other component touched (Rule 7).
- [ ] Code is modular — no oversized files, one responsibility per module (Rule 3).
- [ ] It lives in the correct component folder (Rule 4).
- [ ] No throwaway/one-off scripts committed; reusable tooling preferred (Rule 6).
- [ ] The affected component's usage doc is created/updated (Rule 5).
- [ ] The build log has an entry explaining what and why (Rule 1).
- [ ] If a plan drove the work, the plan is in `/plans/` and current (Rule 2).
- [ ] Your claim in `/docs/active-work.md` is released (Rule 7).
