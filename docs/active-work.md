# Active work — claim before you build

Five Claude Code instances work this repo simultaneously. This file is how they stay out of each
other's way ([INSTRUCTIONS.md](../INSTRUCTIONS.md) Rule 7).

**Before touching anything: read this file.** If a lane is claimed, do not touch it — not even a
one-line fix. **Append your entry; never rewrite or reformat someone else's.**

Need a change in someone else's lane? Do not make it. Add a row to *Cross-lane requests* at the
bottom and let the owner do it.

---

## Claims

| Lane | Directory | Status | Owner / instance | Claimed | Released |
|---|---|---|---|---|---|
| **Wave 0** | `packages/schema/`, `docs/`, `plans/`, root config | ✅ **complete — interface frozen** | scaffolding instance | 2026-07-25 | 2026-07-25 |
| **A** | `contracts/` | 🟡 unclaimed | | | |
| **B** | `agent/` | 🟡 unclaimed | | | |
| **C** | `data/` | 🟡 unclaimed | | | |
| **D** | `venues/` | 🟡 unclaimed | | | |
| **E** | `web/` | 🟡 unclaimed | | | |

To claim: change 🟡 unclaimed → 🔵 in progress, add your name and a timestamp. On finish:
✅ done plus a release timestamp.

---

## Boundaries — the parts people get wrong

- **`contracts/` is Lane A only.** Lane D also writes Solidity, but in its *own* Foundry project at
  `venues/aqua/solidity/`. Lane A never imports it; Lane D never opens `contracts/`.
- **`packages/schema/` is frozen.** Nobody edits it. File a request below instead.
- **`docs/` and `plans/` are shared and append-only.** Add your entry, leave the rest alone.
- **`contracts/out/` is committed on purpose** (not gitignored) — it's how Lane A publishes ABIs to
  everyone else.
- Integrate through the other lane's `README.md`, never by reading its source. If you can't finish
  your task without reaching into another lane, that's the signal to stop and coordinate.

---

## Cross-lane requests

Something you need from a lane you don't own. Owner ticks it off.

| # | From | To | Request | Status |
|---|---|---|---|---|
| 1 | D | A | Confirm the `execute()` target allowlist by CP1 (T+4h): Aqua `0x4999…6d31`, SwapVM `0x8fdd…958f`, Uniswap UniversalRouter, Permit2, WETH. Lane D's `ExecutionPlan.steps[].target` must all be on it or every plan reverts. | open |
| 2 | B, D, E | A | Publish ABIs to `contracts/out/` plus `deployments/base-fork.json` by CP1, even with an incomplete vault. Three lanes are stubbed until this lands. | open |
| 3 | E | B | Stand up the frozen API routes returning fixture data within your first 2 hours. Lane E is blocked until then. | open |

---

## Notes for whoever picks up a lane

Read [CLAUDE.md](../CLAUDE.md) first — it carries the two environment traps that will otherwise cost
you an hour each (the dead Store-stub `python` on PATH, and Ubuntu-20.04 being the default WSL distro
with glibc too old for Foundry).

Write your lane plan to `plans/2026-07-25-lane-<x>-<name>.md` before you write code, and commit
**and push** continuously — 1inch scores commit history and ETHGlobal verifies build timing from the
pushed timeline.
