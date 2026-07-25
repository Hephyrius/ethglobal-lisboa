# Plan — Integrated end-to-end local deployment

**Outcome: the full demo narrative runs start to finish on a Base fork, reproducibly, proven by a
command rather than by five lanes each saying their part works.**

---

## Context

Every lane is green in isolation — 499 Python tests, 86 Foundry tests, five on-chain transactions, a
dApp verified against the live stack. What does not exist is the whole thing, start to finish,
rebuildable.

That is a structural consequence, not carelessness. [INSTRUCTIONS.md](INSTRUCTIONS.md) Rule 7 gave
every lane a directory and forbade crossing boundaries, which is exactly why five parallel agents
converged instead of colliding. But **the seam between all five belongs to no lane, so nobody built
it.** Concretely:

- **Nothing funds a fresh fork.** [contracts/script/Deploy.s.sol](contracts/script/Deploy.s.sol)
  deploys the factory and a demo vault but never transfers USDC — no `deal`, no impersonation. The
  2,500 USDC in the current vault was put there by hand. A fresh fork cannot reach a demoable state.
- **The demo runs on a process nobody can rebuild.** Vault `0x0E2c…B5d1` exists only in the memory
  of an anvil started hours ago. If it dies, the demo dies.
- **No end-to-end check.** [agent/tests/test_integration_lanes.py](agent/tests/test_integration_lanes.py)
  verifies the *seams bind*; it never runs the narrative.
- **Startup order is folklore**, spread across five READMEs, with two silent-failure modes
  (fixture-mode API, evicted model) that present as success.

Owner: **Wave 0** — `scripts/` and root config are already its territory, and this work is
cross-lane by definition. The four lane fixes below stay with their lanes.

---

## The narrative, and where it breaks

| # | Step | Status |
|---|---|---|
| 1 | Base fork running | ✅ `scripts/anvil-fork.sh` |
| 2 | Contracts deployed | ✅ `Deploy.s.sol` → `deployments/base-fork.json` |
| 3 | **Accounts hold USDC** | ❌ **nothing does this** |
| 4 | Genesis chat → mandate | ✅ live mode, model warm |
| 5 | Vault deployed from the chat | ❌ `createVault` never submitted on-chain |
| 6 | Wallet deposits USDC | ✅ proven `0x03cba9d0` (browser handshake still manual) |
| 7 | Tick reads live Graph data | ✅ moonwell vs aave, live |
| 8 | Agent rotates via Uniswap | ❌ golden mandate rejects every plan (#32) |
| 9 | Agent ships into Aqua | ❌ never done from the real vault |
| 10 | Feed renders data → reasoning → tx | ✅ |
| 11 | Withdraw at correct share price | ✅ proven `0xcd955921` |

---

## Deliverables

### Wave 0 — `scripts/` + root

Match the conventions in [contracts/script/check-deployment.sh](contracts/script/check-deployment.sh):
POSIX bash 3.2 (macOS ships it), `set -eu`, no arrays, no `jq`, header explaining *why*, non-zero
exit so it doubles as a gate.

**1. `scripts/seed-fork.sh`** — closes step 3.

Verified on the fork: **Morpho Blue `0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb` holds ~179M USDC.**
Impersonate it rather than writing storage:

```sh
cast rpc anvil_setBalance <addr> 0x21E19E0C9BAB2400000
cast rpc anvil_impersonateAccount $WHALE
cast send $USDC "transfer(address,uint256)" <addr> <amt> --from $WHALE --unlocked --rpc-url $RPC
cast rpc anvil_stopImpersonatingAccount $WHALE
```

`anvil_setStorageAt` is the tempting alternative and the wrong one: USDC on Base is a proxy, a
hardcoded balance slot breaks on upgrade, and the failure looks like "the transfer didn't happen".

Parameterised `--accounts/--usdc/--eth` (Rule 6), and **idempotent** — top up to a target balance
rather than blind-transfer, because a demo gets re-seeded more than once.

**2. `scripts/preflight.sh`** — replaces the `up.sh` I first considered.

**Why not a one-command `up.sh`:** anvil runs in `wsl -d Ubuntu-24.04` while Python and Node run on
the Windows host. A single script cannot start both without shelling across the boundary, which is
fragile in exactly the situation you would rely on it. `preflight.sh` instead *checks* all six
prerequisites read-only and, for each failure, prints the cause and the exact command to fix it.
Safe to re-run, works identically on macOS where everything is native.

Checks, in dependency order: ollama up **and model resident** (`/api/ps` — `{"models":[]}` means a
~2GB cold load on first tick) · anvil reachable on 8540 · `deployments/base-fork.json` addresses have
bytecode · demo accounts hold USDC · agent `/health` reports **`live` on all three seams** · web dev
server responding.

**3. `tests/e2e/` — pytest, not bash.** The one place I deliberately break from the shell-script
convention.

The frozen schemas in `packages/schema/` exist precisely so responses can be validated structurally;
a bash script can only check for HTTP 200. Python lets each step assert against `VaultState`,
`AgentAction`, `Mandate`, reusing `curator_schema`, and it joins the existing 499-test suite. Follow
the established `requires_network` / skip-cleanly pattern from
[agent/tests/test_integration_lanes.py](agent/tests/test_integration_lanes.py) so it is inert when
the stack is down. Add `tests/e2e` to `testpaths` in the root `pyproject.toml`, and note the new
top-level directory in the build log (Rule 4).

**Critically, the suite creates its own vault via the factory each run** rather than touching shared
vault `0x0E2c…B5d1`, which Lanes B, D and E all assert against. That makes it safe to run repeatedly
during the working session.

Coverage: steps 1–5 and 7–11. Step 6's browser-wallet handshake is inherently manual and stays a
runbook item; the suite covers the same deposit path at contract level.

**4. `docs/runbook.md`** — the demo script. Exact commands, expected output, what to say, and the
recovery for each failure in the table below.

### Lanes — the four narrative breaks

| Owner | Item | Size |
|---|---|---|
| **D** | Request #32 — wire `UNISWAP_SLIPPAGE_BPS` into `get_venue()`; both ends already exist | one function |
| **B** | Submit `createVault` on-chain once (step 5 currently falls back to the stub client) | small |
| **B + D** | Agent-driven Aqua ship from the real vault — the 1inch centrepiece rests on Lane D's relay | real work |
| **B** | Show validation layers 5/6 rejecting a bad decision | small |

⚠️ On the Aqua ship, recall request #17: **`ship()` succeeds with zero allowance** and yields a
position that looks healthy and is silently unfillable. "The ship succeeded" is not evidence —
assert `Aqua.safeBalances()` for the vault afterwards.

Do **not** unblock #32 by loosening the golden mandate. A "low drawdown" mandate advertising 3%
slippage is the detail a judge checks, and the real fill was 0.035%.

---

## Startup order — the constraints that bite

```
1. ollama serve          OLLAMA_KEEP_ALIVE=30m exported, then warm the model
2. scripts/anvil-fork.sh   (WSL)  binds 0.0.0.0 — 127.0.0.1 is unreachable from Windows
3. forge script Deploy     (WSL)  writes deployments/base-fork.json
4. scripts/seed-fork.sh    (WSL)  USDC + ETH into demo accounts
5. agent API             AGENT_MODE=live — gate on /health saying live on ALL THREE seams
6. pnpm --filter @curator/web dev
```

Two gates exist because both failures **present as success**: an API in fixture mode answers every
request and validates every response over invented data, and an evicted model surfaces as
`ModelUnavailable` — reading as "server down" when it is merely cold — precisely when the stack has
idled while someone explains the architecture.

---

## Failure modes, pre-written for the runbook

| Symptom | Cause | Fix |
|---|---|---|
| Badge green, numbers look canned | API in fixture mode | `GET /health`; restart with `AGENT_MODE=live` |
| Every tick `rejected`, slippage message | #32 | set `UNISWAP_SLIPPAGE_BPS` |
| First tick times out, `ModelUnavailable` | model evicted | warm it; `OLLAMA_KEEP_ALIVE=30m` needs an `ollama serve` restart |
| Reads fine, every write reverts | `AGENT_PRIVATE_KEY` is anvil #0 not #1 | compare with `/vault/{addr}/state`.`agent` |
| Aqua position healthy but never fills | approvals dropped (#17) | check `safeBalances()`; never skip Aqua approvals |
| `GLIBC_2.34 not found` | wrong WSL distro | `wsl -d Ubuntu-24.04` |
| `next build` dies `EPERM` | stale `next dev` holds `.next/trace` | kill the dev server |
| Vault address 404s | anvil restarted, state was in memory | re-run steps 3–4 |

---

## Verification

The rungs above *are* the verification — each one's proof becomes a test in `tests/e2e`. Beyond
those, three checks on the tooling itself, because a broken gate is worse than no gate:

- **`seed-fork.sh` is idempotent** — run twice; the second run is a no-op and balances are unchanged.
- **`preflight.sh` names the right cause** — stop the agent API and confirm it reports *that*, not
  something downstream. A preflight that misattributes failures will cost more time than it saves.
- **`tests/e2e` skips rather than fails when the stack is down** — following the existing
  `requires_network` pattern, so a fresh clone running the full suite stays green.

**Definition of done**
- [ ] R8 green — the whole narrative from a cold anvil
- [ ] Every rung's proof passing, nothing stubbed; `/health` `live` on three seams throughout
- [ ] One agent-driven Uniswap rotation **and** one agent-driven Aqua ship, with tx hashes, and
      `safeBalances()` confirming the Aqua position is real rather than merely created
- [ ] At least one validation guard shown *rejecting* a bad decision — the layers exist but have
      never been demonstrated catching the failures that motivated them
- [ ] `docs/runbook.md` walkable by someone who has not seen the repo
- [ ] One full rehearsal, timed, recorded

---

## Walking to the v1 vertical slice

Nine rungs. Each one **runs a command, proves something, and leaves the system in a known-good
state** — so work can stop at any rung and we know exactly how deep the slice goes. Each rung's
proof is also a test case in `tests/e2e`, built as we climb rather than written at the end.

The rule: **do not start a rung until the one below it is green.** Every integration failure in this
project so far has been a lower rung assumed rather than checked.

---

### R0 · Cold start reaches a funded fork — *Wave 0*

The foundation nothing currently provides.

```sh
scripts/anvil-fork.sh                                            # WSL, terminal 1
cd contracts && forge script script/Deploy.s.sol \
  --rpc-url http://127.0.0.1:8540 --broadcast                    # WSL, terminal 2
scripts/seed-fork.sh                                             # WSL
```

**Proves:** `deployments/base-fork.json` has fresh addresses with bytecode; demo accounts hold USDC
and ETH. **Blocked by:** nothing. **Build first — every rung above sits on it.**

### R1 · Stack up, every seam genuinely live — *Wave 0*

```sh
scripts/preflight.sh
```

**Proves:** ollama up *with the model resident*, anvil reachable, deployed bytecode present,
accounts funded, `/health` reporting **`live` on all three seams**, web responding.

**Why its own rung:** the two failures that present as success both live here. Catch them once, at a
gate, rather than three rungs later disguised as a data problem.

### R2 · First true vertical slice — chain → agent → API

```sh
uv run pytest tests/e2e -k slice_read -v
```

Create a *fresh* vault through the factory, deposit USDC programmatically, read it back.

**Proves:** `GET /vault/{addr}/state` returns a schema-valid `VaultState`; `total_assets` matches
the deposit; share price uses the 6-decimal convention (request #27 — `convertToAssets(1e18)` returns
`999952`, **not** `1e18`; do not let the wrong figure reach the submission).
**Blocked by:** nothing. **This is v1 of the slice** — three components in one path.

### R3 · The agent reasons over live data

```sh
uv run pytest tests/e2e -k slice_decide -v
```

**Proves:** `POST /vault/{addr}/tick` returns a schema-valid `AgentAction`; every `facts_used` id
resolves to a fact in the snapshot it was given; sources include `messari` *and* `aave`, so the
moonwell-vs-aave comparison is genuinely in play.

`held` is a **pass** here. Whether it trades is R4's question; that it reasoned over live Graph data
is this one's. **Blocked by:** nothing.

### R4 · The agent executes — Uniswap rotation

**Blocked by: Lane D #32.** Until then every plan is rejected on slippage and this rung cannot go
green.

**Proves:** a tick produces an `ExecutionPlan`, submits one atomic `executeBatch`, holdings move in
the *intended direction*, and realised slippage sits inside the mandate ceiling.

**Also the 1inch token-transfer requirement** — an Aqua ship moves no tokens, so this swap, or R5's
fill, is the qualifying event.

### R5 · The agent ships into Aqua — the 1inch centrepiece

**Blocked by: Lanes B + D.** Currently proven only through Lane D's relay, not the product.

**Proves:** an agent-driven `ship()` from the real vault, **and `Aqua.safeBalances()` non-zero for
the vault afterwards.**

> Per request #17, `ship()` **succeeds with zero allowance** and leaves a position that looks
> healthy in every observable way and is silently unfillable. A successful tx is *not* evidence here
> — the balance assertion is the whole rung.

### R6 · Genesis closes the loop — chat → mandate → real vault

**Blocked by: Lane B** (`createVault` has never been submitted; live mode falls back to the stub).

**Proves:** `POST /genesis/chat` → `POST /genesis/finalize` deploys a real vault, and its on-chain
`mandate_hash` equals the keccak of the mandate the user was shown. That equality is the depositor's
only verification handle, so it is worth asserting rather than assuming.

### R7 · The browser — the only manual rung

Wallet signing cannot be automated. R2 already covers the same deposit path at contract level; this
rung is about what a judge actually sees.

**Proves:** badge reads `LIVE` (not `FIXTURES`); a signed deposit lands; the decision feed renders
R4's and R5's transactions as data → reasoning → tx hash.

### R8 · Cold-start replay — the gate

Everything above can pass on a fork that has drifted for hours. This is the rung that proves the
demo is *rebuildable*.

Kill anvil, then replay R0 → R7 top to bottom.

> ⚠️ **Destroys vault `0x0E2c…B5d1`, which Lanes B, D and E assert against.** Announce in
> `docs/active-work.md`, run it only once the lane fixes have landed, and expect
> `deployments/base-fork.json` to change.

Green here means the demo survives a laptop reboot at 3am. That is the actual deliverable.

### R9 · Runbook and rehearsal

`docs/runbook.md` from the commands that actually worked, then one full timed rehearsal — which is
also the take you record.

---

## What runs in parallel

**Lanes B and D climb from R4 while Wave 0 builds R0–R3.** No dependency between them until R4, so
neither waits.

**Lane C is independent of all nine rungs** — the PyPI publish touches none of this stack, and it is
25% of the largest single Graph prize. It should not be sequenced behind integration.

**Mainnet stays out of scope.** 1inch accepts local forks in writing and no other sponsor asks for
mainnet, so R8 green *is* the finish line. Deploy only if there is comfortable time left.
