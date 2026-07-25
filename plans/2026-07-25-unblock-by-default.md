# Plan — Unblock by default: finish the build without anyone stopping

**Rule 7 stopped the lanes colliding. It is now stopping them moving.** This plan keeps the
isolation that made parallel work succeed, and removes the four ways it currently makes people wait.

Supersedes nothing. Read alongside
[the e2e plan](2026-07-25-e2e-local-deployment.md) (what to build) — this one is *how to keep going
when something is in the way*.

---

## 1. Why work stops today

Not one big blocker. Four small ones, each of which turns a five-minute fix into a wait:

1. **Requests sit open with no owner online.** #19 waited for a one-word mandate edit. #43 waited
   for the same edit again. #45 was a bug in a shared script that its author was not looking at.
   Every one was minutes of work and hours of latency.
2. **Wave 0 owns things nobody else may touch** — frozen schema, root config, `scripts/` — and Wave
   0 is not always active. Lane B already worked around this once, correctly, by fixing a one-line
   `pyproject.toml` break rather than leaving C and D stuck (#4).
3. **Shared services have ambiguous ownership.** The agent API sat in fixture mode for hours because
   restarting it felt like Lane B's call. It blocked R4 verification for everyone.
4. **"Blocked on another lane" is treated as "stop"** rather than "build against the documented
   interface and mark the gap".

The fix is not less isolation. It is **explicit standing permissions, and a rule that says never
wait — downgrade.**

---

## 2. Standing authorizations — do these without asking

Any lane, any time, no request needed. If you were unsure whether you were allowed, you now are.

| You may | Notes |
|---|---|
| **Restart any shared service** — agent API, ollama, web dev server | Say so in `docs/active-work.md`. Restarting the API to pick up `AGENT_MODE=live` is *expected*, not intrusive. |
| **Run `scripts/preflight.sh` and `scripts/seed-fork.sh`** | Both are read-only or idempotent. Seeding tops up to a target; it cannot over-fund. |
| **Add or change a variable in `.env`** | It is gitignored and machine-local. Add the corresponding line to `.env.example` and say why. |
| **Create your own vault via the factory** | For any test or experiment. Never assert against the shared demo vault. |
| **Warm the model** | `keep_alive: 30m`. Free, and prevents the failure that looks like a dead server. |
| **Fix a one-line break in shared root config that blocks you** | Precedent: Lane B's #4. Fix it, push it, announce it. Do not sit behind it. |

**Still requires the owner** — these are the ones where a wrong guess costs more than the wait:
another lane's source, `packages/schema/*` shape changes, `contracts/` (Lane A only), and
**restarting anvil** — which destroys the shared vault three lanes assert against.

### Wave 0's authority is delegated when Wave 0 is absent

Wave 0 owns the frozen schema, root config and `scripts/`. When it is not responding:

- **Golden fixtures** (`packages/schema/fixtures/`): if a request has sat unanswered for **30
  minutes** and the change is *additive* — a new `permitted_data_sources` entry, a looser optional
  field — **make it, run the full suite, and log it**. Both `aave` and `chainlink` were exactly this
  and both waited.
- **Schema *shape* changes stay blocked.** Adding a required field or changing a type breaks four
  lanes silently. File it and route around it (§3).
- **`scripts/`**: fix bugs in it directly. It is shared tooling, not a lane.

---

## 3. The ladder — never wait, always downgrade

When something blocks you, walk down until something is actionable. **Only the bottom rung involves
stopping, and it has never been the right answer yet.**

1. **Is it covered by a standing authorization (§2)?** → do it.
2. **Can you build against the *documented interface* and stub the missing side?** → do that. Every
   lane already did this for the first four hours; it still works. Mark the stub loudly.
3. **Can you write the test now and mark it `xfail`/`skip` with the reason?** → do that. The test
   becomes the acceptance criterion for whoever unblocks it, and it flips to green by itself.
4. **Can you do a different task from your lane's list while it clears?** → do that, and file the
   request before switching so the clock starts.
5. **Only now:** file the request and say explicitly *what you are doing meanwhile*. A request that
   ends "blocked, waiting" is a request that will still be open in an hour.

**Timebox: 20 minutes.** If you have been stuck on the same thing for twenty minutes without
descending this ladder, you are waiting rather than working.

---

## 4. Writing a request that unblocks itself

The requests that got resolved fastest had three things. Copy the pattern:

- **The diagnosis, not the symptom.** #45 said *"line 31 `set -a` overwrites the caller's export"*,
  not *"the script doesn't work"*. That is the difference between a fix and an investigation.
- **The repro.** #45 gave the exact command and the wrong output it produced.
- **What you are doing meanwhile**, so nobody waits on the answer.

And when you are wrong, say so plainly and move — #39 corrected a proof in someone else's plan and
was right to; the plan changed within the hour.

**Answering:** if a request is addressed to you and you can resolve it in under five minutes, do it
before your next task. Latency on small things is what has cost this build most.

---

## 5. Outstanding work — self-serve

Nothing here needs a meeting. Each item names its owner, and every one has a fallback.

### Unblocked right now

| Owner | Task | If it fights you |
|---|---|---|
| **Anyone** | **Restart the agent API in live mode.** It has been serving fixtures for hours; `/health` proves it. This blocks R4 verification for everyone. | Standing authorization §2. Just do it. |
| **Wave 0** | R4 e2e test — #32 landed and `UNISWAP_SLIPPAGE_BPS=50` is set | If a tick still rejects, check `/health` for a seam that fell back to fixtures (Lane D's note on #32) |
| **Lane C** | Publish `curator-schema` → `curator-data` → `curator-mcp` to PyPI | Names are free (verified). 25% of the largest single Graph prize, and independent of every other rung |
| **Lane B** | `createVault` on-chain → unblocks R6 | Genesis already mints a fresh vault per run, so nothing shared is at risk |

### Needs a human, not an agent

Uniswap Developer Feedback Form · fund `X402_PRIVATE_KEY` (`0x64D2…fBb7`) with a few dollars of USDC
on real Base — Lane C reports x402 fails with `insufficient_balance` only, so funding is the whole
remaining gap · flip the repo public before submitting · record the 2–4 minute demo video.

### Blocked, with the route around it already known

| Item | Blocked on | Route around |
|---|---|---|
| **R5 Aqua ship** | Lane B + D | Lane D's relay already proves a contract maker can ship. Write the e2e test now, `xfail`, gated on the **vault→Aqua allowance** — not `safeBalances()`, which passes on a dead position (#39) |
| **Taker fill** | 1inch's deployed `SwapVMRouter` source (#34) | Optional polish. R5 alone satisfies the 1inch requirement; do not let this hold the rung |
| **R8 cold replay** | R4–R6 | Less disruptive than feared — Lane E reports the vault redeploys to the **same address**, and the dApp follows `deployments/base-fork.json` anyway |

---

## 6. Traps with pre-agreed answers

Do not rediscover these. Each cost someone real time already.

| Trap | Answer |
|---|---|
| API answers everything, numbers look canned | Fixture mode. `GET /health`. Restart — you are allowed |
| First tick times out as `ModelUnavailable` | Model evicted, not a dead server. Warm it |
| Reads fine, every write reverts | `AGENT_PRIVATE_KEY` must be anvil **#1**, not #0 |
| Aqua position looks healthy, never fills | Approvals dropped. Check the **allowance**, not `safeBalances` (#17, #39) |
| A script ignores an env var you exported | Fixed — `.env` is now a default, exports win (#45) |
| `uv sync --extra one` breaks another lane | Always `--all-extras`; it prunes otherwise (#10) |
| Third-party interface behaves unlike its docs | Check the deployed bytecode. Found the SwapVM version mismatch in two minutes (#29, #30) |
| `git add -A` sweeps another lane's work | Stage explicit paths. It has already misattributed a day of Lane E's work (#14, #21) |
| Share price looks 1e12 wrong | It is 6-decimal. `999952` is correct; `1e18` is the error (#27) |

---

## 7. Definition of done

- [ ] No request open longer than 30 minutes without either a resolution or a stated workaround
- [ ] R4 green; R5 and R6 green or `xfail` with the allowance-based criterion recorded
- [ ] MCP server installable from a clean machine
- [ ] The four human items done
- [ ] R8 replay green from a cold anvil
- [ ] `docs/runbook.md` walkable by someone who has not seen the repo

**The test of this plan is not that nothing goes wrong.** It is that when something does, the next
commit lands within twenty minutes rather than after a handoff.
