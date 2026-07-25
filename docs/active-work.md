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
| **A** | `contracts/` | 🔵 in progress | Lane A instance (Claude Code) | 2026-07-25 01:35Z | |
| **B** | `agent/` | 🔵 in progress | Lane B instance | 2026-07-25 T+1:00 | |
| **C** | `data/` | 🔵 in progress | Lane C instance | 2026-07-25 | |
| **D** | `venues/` | 🔵 in progress | Lane D instance | 2026-07-25 02:10 | |
| **E** | `web/` | 🔵 in progress | Lane E instance (Claude Code) | 2026-07-25 | |

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
| 4 | B | C, D (FYI) | **Already fixed — pull before you run anything.** Root `pyproject.toml` had `curator-schema` as both a workspace member and a `tool.uv.sources` path, so `uv sync` failed for every Python lane. Changed to `{ workspace = true }`. Wave 0 was released with no owner to action a request, so Lane B fixed the one line and pushed rather than leave C and D blocked. Do not re-fix it. | ✅ done |
| 5 | E | B | **Enable CORS on the FastAPI app** (`CORSMiddleware`, allow `http://localhost:3000`). The dApp calls the API from the browser, not server-side, so without this every frozen route fails with an opaque CORS error rather than a useful one. One-line fix, easy to miss until demo time. | open |
| 6 | E | B | **No frozen route returns a `Mandate` for an existing vault.** `VaultState` carries `mandate_hash` but not the mandate, so the vault page cannot render the mandate viewer required by §10 Lane E MVP for any vault this browser did not itself create. Requested: `GET /vault/{addr}/mandate → Mandate`. *Not blocking* — Lane E caches the mandate client-side at `POST /genesis/finalize` and falls back to the golden fixture, badged as such. | open |
| 7 | D | A | **Allowlist correction — request 1 has the wrong router address, verified against the live API.** Uniswap's Trading API on Base returns `to = 0x6fF5693b99212Da76ad316178A184AB56D299b43` for the swap tx (same address as the Permit2 `spender`), **not** the `0x2626664c…e481` UniversalRouter in `packages/schema/fixtures/execution-plan.json`. Confirmed live: `POST /quote` → `POST /swap` both HTTP 200, calldata selector `0x3593564c` = `UniversalRouter.execute`. Please allowlist **`0x6fF5693b99212Da76ad316178A184AB56D299b43`**; keeping `0x2626664c…` as well is harmless. Verified target list in `venues/README.md` §Vault allowlist. | open |
| 8 | D | A | **`execute()` must also accept ERC-20 token addresses as targets, or approvals cannot be expressed.** An `ExecutionPlan` step for `USDC.approve(Permit2, …)` targets **USDC** `0x8335…2913` — a token, not a venue. The golden fixture `execution-plan.json` step 1 does exactly this, so the frozen interface already assumes it. Either allowlist the mandate's tokens (USDC, WETH) as `execute()` targets, **or** tell me to route approvals through `approveVenue(token, spender, amount)` and I will emit that shape instead. **Blocking for the CP2 vertical slice** — otherwise every Uniswap plan reverts on step 1. Lane D follows the fixture shape (token as target) until told otherwise; switching is a one-line change in `venues/uniswap/plan.py`. | open |

---

## Notes for whoever picks up a lane

Read [CLAUDE.md](../CLAUDE.md) first — it carries the two environment traps that will otherwise cost
you an hour each (the dead Store-stub `python` on PATH, and Ubuntu-20.04 being the default WSL distro
with glibc too old for Foundry).

Write your lane plan to `plans/2026-07-25-lane-<x>-<name>.md` before you write code, and commit
**and push** continuously — 1inch scores commit history and ETHGlobal verifies build timing from the
pushed timeline.
