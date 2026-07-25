# CLAUDE.md — read this first, every session

Agentic vault curation for ETHGlobal Lisbon 2026. **Five Claude Code instances build this repo
simultaneously.** Strict component isolation is what keeps that from corrupting itself.

## Read before you touch anything

1. **[INSTRUCTIONS.md](INSTRUCTIONS.md)** — the 7 operating rules. Not optional.
2. **[plans/2026-07-25-master-build-plan.md](plans/2026-07-25-master-build-plan.md)** — lanes,
   frozen interface, timeline, credentials, submission gates.
3. **[plans/initiate_plan.md](plans/initiate_plan.md)** — concept + locked architecture decisions.
4. **[docs/active-work.md](docs/active-work.md)** — who currently owns what. **Check before editing.**

---

## ⚠️ Environment traps — both will cost you an hour

**`python` on PATH is a dead Microsoft Store stub.** It prints "Python was not found" instead of
running. Real Python is Anaconda `C:\ProgramData\anaconda3\python.exe` (3.12.7), but prefer the
project venv: `uv sync` then `uv run …`.

**There are two WSL distros and the default is the wrong one.**

| Distro | glibc | Python | |
|---|---|---|---|
| **Ubuntu-24.04** | 2.39 | 3.12.3 | ✅ **All Foundry work here** |
| Ubuntu-20.04 *(default)* | 2.31 | 3.8.10 | ❌ `foundryup` binaries fail: `GLIBC_2.34 not found` |

A bare `wsl <cmd>` lands in 20.04. **Always `wsl -d Ubuntu-24.04`.**

Anvil runs in WSL — bind `--host 0.0.0.0` or Windows clients can't reach `localhost:8545`.
Node 20.13 + pnpm 9.5 are on the Windows host and work fine.

---

## Lanes — you own exactly one

| Lane | Directory | Stack |
|---|---|---|
| A | `contracts/` | Foundry — run in `wsl -d Ubuntu-24.04` |
| B | `agent/` | Python |
| C | `data/` | Python |
| D | `venues/` | Python + its own Foundry project in `venues/aqua/solidity/` |
| E | `web/` | Next.js / TypeScript |

`packages/schema/` is **frozen and read-only** after Wave 0. `docs/` and `plans/` are shared and
**append-only** — add your entry, never rewrite or reformat someone else's.

**Do not read or edit another lane's code.** Integrate through `packages/schema/` and the other
lane's `README.md`. Need something changed elsewhere? File a request in `docs/active-work.md` and
let the owner do it. If you can't finish your task without reaching into another lane, stop and
coordinate — that's the signal, not an obstacle to route around.

---

## Non-negotiables

**Commit and push after every meaningful change.** Not at the end. Two scored reasons: 1inch
explicitly disqualifies *"single-commit entries on the final day"*, and ETHGlobal judges verify the
work happened inside the hackathon window using the **pushed** GitHub timeline. Local commits prove
nothing.

**Claim before you build.** Register your lane in `docs/active-work.md`, and write your lane plan to
`plans/2026-07-25-lane-<x>-<name>.md` before writing code.

**Build against `packages/schema/fixtures/`.** Mock-first means no lane ever blocks on another.
But the *demo path* must use live data — The Graph disqualifies mocked data at submission.

**Stay cross-platform.** A teammate on macOS takes over at 10:00. No absolute paths, no
Windows-only paths, no PowerShell in the committed tree. Scripts are POSIX `sh`/`bash`.

**Docs are deliverables, ~20% of your time.** Your component `README.md` (purpose, public interface,
data shapes, dependencies, example, invariants) is the *only* way the other four lanes integrate
with you. Every non-trivial decision gets a `docs/build-log.md` entry explaining **why** —
especially library choices and tradeoffs.

**MVP only.** Each lane has an MVP list and a Stretch list in the master plan. Nothing from Stretch
until MVP is green, documented, and pushed. Feature freeze T+14h; MVP + macOS handoff at 10:00.

---

## Credentials

Real values in `.env` (gitignored); template and rationale in `.env.example` and master plan §8.1.
Three are blocking: `UNISWAP_API_KEY`, an archive-capable `BASE_RPC_URL`, and `GRAPH_API_KEY`.
**No 1inch API key is needed** — Aqua and SwapVM are plain on-chain contracts. No model API key —
local Ollama.
