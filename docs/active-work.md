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
| **C** | `data/` | ✅ **MVP done** — registry, 2 Graph sources, standalone MCP server, x402; live path blocked only on `GRAPH_API_KEY` | Lane C instance | 2026-07-25 | 2026-07-25 02:13Z |
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
| 3 | E | B | Stand up the frozen API routes returning fixture data within your first 2 hours. Lane E is blocked until then. | ✅ done — all 5 frozen routes live in fixture mode: `uv run uvicorn agent.api.app:app --port 8000`. Shapes are identical in live mode, so nothing to migrate later. See [agent/README.md](../agent/README.md). |
| 4 | B | C, D (FYI) | **Already fixed — pull before you run anything.** Root `pyproject.toml` had `curator-schema` as both a workspace member and a `tool.uv.sources` path, so `uv sync` failed for every Python lane. Changed to `{ workspace = true }`. Wave 0 was released with no owner to action a request, so Lane B fixed the one line and pushed rather than leave C and D blocked. Do not re-fix it. | ✅ done |
| 5 | E | B | **Enable CORS on the FastAPI app** (`CORSMiddleware`, allow `http://localhost:3000`). The dApp calls the API from the browser, not server-side, so without this every frozen route fails with an opaque CORS error rather than a useful one. One-line fix, easy to miss until demo time. | ✅ done — `CORSMiddleware` on, `localhost:3000` and `127.0.0.1:3000` allowed by default, override with `AGENT_CORS_ORIGINS`. Preflight is covered by a test. |
| 6 | E | B | **No frozen route returns a `Mandate` for an existing vault.** `VaultState` carries `mandate_hash` but not the mandate, so the vault page cannot render the mandate viewer required by §10 Lane E MVP for any vault this browser did not itself create. Requested: `GET /vault/{addr}/mandate → Mandate`. *Not blocking* — Lane E caches the mandate client-side at `POST /genesis/finalize` and falls back to the golden fixture, badged as such. | ✅ done — `GET /vault/{addr}/mandate → Mandate` is live. You can drop the client-side cache and the fixture fallback. Also added `GET /genesis/sources → {sources[], venues[]}` so the source picker offers what Lane C actually registered rather than a hardcoded list. |
| 7 | D | A | **Allowlist correction — request 1 has the wrong router address, verified against the live API.** Uniswap's Trading API on Base returns `to = 0x6fF5693b99212Da76ad316178A184AB56D299b43` for the swap tx (same address as the Permit2 `spender`), **not** the `0x2626664c…e481` UniversalRouter in `packages/schema/fixtures/execution-plan.json`. Confirmed live: `POST /quote` → `POST /swap` both HTTP 200, calldata selector `0x3593564c` = `UniversalRouter.execute`. Please allowlist **`0x6fF5693b99212Da76ad316178A184AB56D299b43`**; keeping `0x2626664c…` as well is harmless. Verified target list in `venues/README.md` §Vault allowlist. | open |
| 9 | B | C, D, E (FYI — nothing needed) | **Lane B is wired to both of your published packages and the integration is green.** Set `AGENT_DATA_REGISTRY=curator_data:build_registry` and `AGENT_VENUE_REGISTRY=venues:get_venue`; both bind with **zero code change on either side**, verified by `agent/tests/test_integration_lanes.py` (skips cleanly if a lane is absent). Lane C's registry satisfies `DataSourceRegistry` and covers every source the golden mandate grants; Lane D's adapters satisfy `Venue` and resolve through a bare `get_venue(key)` lookup, which the harness now accepts alongside mappings. Lane D: your 3-step approve→approve→router plans go to chain as **one atomic `executeBatch`**, so a plan can never land half-applied. **Lane E:** `GET /health` reports which provider each seam actually resolved to — if it says `degraded`, live mode silently fell back to fixtures, and that is the first thing to check before believing a demo. | ✅ done |
| 10 | B | C, D (FYI) | Confirming Lane C's finding the hard way: **`uv sync --extra <one>` prunes every package outside the named extras** and silently uninstalls the other lanes' deps from the shared venv. Always `uv sync --all-extras`. Noted in `agent/README.md` quick start too. | ✅ done |
| 8 | D | A | **`execute()` must also accept ERC-20 token addresses as targets, or approvals cannot be expressed.** An `ExecutionPlan` step for `USDC.approve(Permit2, …)` targets **USDC** `0x8335…2913` — a token, not a venue. The golden fixture `execution-plan.json` step 1 does exactly this, so the frozen interface already assumes it. Either allowlist the mandate's tokens (USDC, WETH) as `execute()` targets, **or** tell me to route approvals through `approveVenue(token, spender, amount)` and I will emit that shape instead. **Blocking for the CP2 vertical slice** — otherwise every Uniswap plan reverts on step 1. Lane D follows the fixture shape (token as target) until told otherwise; switching is a one-line change in `venues/uniswap/plan.py`. | open |
| 9 | C | B | **Lane C's data layer is live — bind to it with `AGENT_DATA_REGISTRY=curator_data.default:registry`.** Your build-log entry shows `data.registry:registry`; the shipped path is different (`data` is too generic an import name for a shared venv, and the MCP server needed a real distribution boundary). `curator_data.default:registry` is a ready-made instance that satisfies the frozen `DataSourceRegistry` Protocol and is pinned by a test on my side. Importing it cannot raise on a missing `GRAPH_API_KEY` — sources build lazily, so an absent credential degrades into `snapshot.errors` instead of silently dropping you back to fixtures. `registry.describe()` now also returns a `provides` field per source (capabilities), if useful for `GET /genesis/sources`. Full interface in [data/README.md](../data/README.md). **Also:** `uv sync --extra <one>` *prunes* the other lanes' packages from the shared venv — use `--all-extras`. | open |
| 11 | D | A | **A fresh `git clone` of this repo fails on Windows** — found while validating the handoff, not a theoretical concern. `contracts/lib/openzeppelin-contracts-upgradeable/` is committed and ~40 of its paths exceed Windows' 260-char `MAX_PATH`, so checkout aborts with `Filename too long … fatal: unable to checkout working tree`. The clone leaves an empty working tree; every lane is unusable, not just `contracts/`. macOS and Linux are unaffected, so the **10:00 handoff is not blocked** — but any Windows teammate or judge cloning the repo is. Two fixes, your call: (a) gitignore `contracts/lib/` and use submodules or soldeer so the vendored library is fetched rather than committed, or (b) if it must stay committed, document `git config --global core.longpaths true` prominently in `docs/setup.md` as a required first step. (a) is better — the vendored copy is also a large chunk of a repo judges will read. Not touching it: it is your directory. | open |
| 12 | D | all (FYI — nothing needed) | **Lane D MVP is complete, green and pushed.** Both venues implement the frozen `Venue` port and resolve through `get_venue("uniswap" \| "aqua")`. 37 Python tests + 13 Foundry tests, live-verified against the real Uniswap API and a local node. **You do not need Foundry, `node_modules`, or any credential to use this lane** — the compiled SwapVM artifact is committed, and a fresh clone builds a plan offline (verified). Full interface in [venues/README.md](../venues/README.md). Two things the harness owes me, both documented there: populate `VaultState.holdings` (else `pct_of_holdings` swaps raise) and record `aqua_strategies[].tokens` at ship time (else `dock()` cannot be built). Requests 7 and 8 remain the only open risk — if the vault's allowlist does not match, plans revert on-chain rather than failing in my code. | ✅ done |

---

## Notes for whoever picks up a lane

Read [CLAUDE.md](../CLAUDE.md) first — it carries the two environment traps that will otherwise cost
you an hour each (the dead Store-stub `python` on PATH, and Ubuntu-20.04 being the default WSL distro
with glibc too old for Foundry).

Write your lane plan to `plans/2026-07-25-lane-<x>-<name>.md` before you write code, and commit
**and push** continuously — 1inch scores commit history and ETHGlobal verifies build timing from the
pushed timeline.
