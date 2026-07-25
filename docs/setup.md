# Setup

Fresh clone → running stack. Two columns because the build starts on Windows/WSL and hands over to
macOS at 10:00 — if a step only works on one, that's a bug in this document.

## 0. Prerequisites

| | Windows (+ WSL) | macOS |
|---|---|---|
| Python 3.12 | via `uv` (below) | via `uv` (below) |
| Node 20 + pnpm 9 | ✅ already installed (20.13.1 / 9.5.0) | `brew install node && corepack enable pnpm` |
| Foundry | in **`wsl -d Ubuntu-24.04`** — see §2 | native `foundryup` |
| git | ✅ | ✅ |

### ⚠️ Two Windows-only traps

**`python` on PATH is a dead Microsoft Store stub.** It prints *"Python was not found"* instead of
running, and it shadows the real install. Real Python is `C:\ProgramData\anaconda3\python.exe`
(3.12.7) — but use the project venv, not either of those directly.

**There are two WSL distros and the default is the wrong one.**

| Distro | glibc | Python | |
|---|---|---|---|
| **Ubuntu-24.04** | 2.39 | 3.12.3 | ✅ all Foundry work |
| Ubuntu-20.04 *(default)* | 2.31 | 3.8.10 | ❌ `foundryup` fails: `GLIBC_2.34 not found` |

A bare `wsl <cmd>` lands in 20.04. **Always `wsl -d Ubuntu-24.04`.**

---

## 1. Python toolchain

`uv` manages a project-pinned Python 3.12 identically on Windows, WSL and macOS — which is what
makes the handoff a no-op. It also avoids the polluted global site-packages (see Troubleshooting).

```bash
# macOS / WSL
curl -LsSf https://astral.sh/uv/install.sh | sh
```
```powershell
# Windows PowerShell
irm https://astral.sh/uv/install.ps1 | iex
```

Then, from the repo root:

```bash
uv sync                                   # creates .venv pinned to 3.12
uv run pytest packages/schema/python -q   # 22 tests — confirms the interface is intact
```

`uv run <cmd>` executes inside the venv; no manual activation needed.

---

## 2. Foundry

```bash
# Windows: FIRST drop into the right distro
wsl -d Ubuntu-24.04

# then (WSL 24.04 and macOS are identical from here)
curl -L https://foundry.paradigm.xyz | bash
source ~/.bashrc     # macOS: source ~/.zshrc
foundryup
forge --version
```

glibc 2.39 on Ubuntu-24.04 means the prebuilt binaries work. If they somehow don't, build from
source instead and write contracts while it compiles (~15–30 min):

```bash
cargo install --git https://github.com/foundry-rs/foundry --profile release forge cast anvil
```

---

## 3. Credentials

```bash
cp .env.example .env
```

Fill the three blocking keys before anything works — rationale for each is in `.env.example` and
master plan §8.1:

- `UNISWAP_API_KEY` — https://developers.uniswap.org/dashboard
- `BASE_RPC_URL` — **must be archive-capable** (Alchemy/QuickNode/dRPC free tier). The public
  `mainnet.base.org` is rate-limited and will crawl or fail under forking.
- `GRAPH_API_KEY` — https://thegraph.com/studio → API Keys

`.env` is gitignored. Never commit a real key — the repo is public for submission.

---

## 4. Run the stack

Four processes. Start the fork first; everything else depends on it.

```bash
# 1 — Base mainnet fork.  Windows: inside `wsl -d Ubuntu-24.04`
./scripts/anvil-fork.sh
```

```bash
# 2 — local model (any OpenAI-compatible server works)
ollama serve
ollama pull qwen2.5:3b-instruct-q4_K_M     # ~2GB. This is what the stack is configured for.
```

> ⚠️ **Pull the 3B, not a 14B.** This block used to say `qwen2.5:14b-instruct`, which is a ~9GB
> download that **nothing here uses** — `.env` sets the 3B, and a fresh clone that took the old
> advice *and* the old documented default died on its first tick with `model not found`
> (active-work #49). The 3B is also the only size this machine can hold: measured 1.1 GB free
> against 33.5 of 37.9 GB committed, so a 7B would page rather than run (see
> `uv run python -m scripts.bakeoff --check`). It is a real limitation of the model, not of the
> plumbing — the measurements are in the build log.

```bash
# 3 — agent API (Lane B)
uv run uvicorn agent.api.app:app --port 8000
```

```bash
# 4 — dApp (Lane E).  Windows: on the host, not WSL
pnpm install && pnpm --filter @curator/web dev
```

Then check the whole thing rather than trusting it:

```bash
./scripts/preflight.sh      # 6 checks; names the fix for each failure
```

`preflight.sh` is the single source of truth on demo-readiness. Run it **from the host side** where
ollama and the API live — run inside WSL it can only reach the model indirectly, and it will say so
rather than claim a blocker.

Open http://localhost:3000.

The fork binds `0.0.0.0`, so Windows host processes and the browser reach WSL's anvil on
`localhost` normally. Port is `8540` (not the 8545 default) — see `.env.example`.

---

## 5. Verify

```bash
uv run pytest packages/schema/python -q                  # interface intact
wsl -d Ubuntu-24.04 -- bash -lc 'cd contracts && forge test --fork-url $BASE_RPC_URL'
pnpm --filter web build
```

---

## Troubleshooting

**`Python was not found`** — you hit the Store stub. Use `uv run`, or
`C:\ProgramData\anaconda3\python.exe` directly.

**`GLIBC_2.34 not found` from forge/anvil** — you're in Ubuntu-20.04. Use `wsl -d Ubuntu-24.04`.

**pytest fails collecting with `ImportError: cannot import name 'ContractName' from 'eth_typing'`** —
a broken global `web3` install registers a `pytest_ethereum` plugin. Use `uv run pytest` (the venv
doesn't have it), or `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` as an escape hatch.

**Browser wallet can't reach the fork** — anvil must bind `0.0.0.0`, not `127.0.0.1`.
`scripts/anvil-fork.sh` does this; a hand-rolled `anvil` command won't.

**Anvil forking is slow or 429s** — your `BASE_RPC_URL` isn't archive-capable. Swap to an Alchemy or
QuickNode endpoint.

**Whole-file diffs after the macOS handoff** — `.gitattributes` sets `eol=lf`. If you cloned before
it landed: `git rm --cached -r . && git reset --hard`.
