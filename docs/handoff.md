# Handoff

**For the teammate picking this up on macOS at 10:00.**

Master plan §3 asks for this to exist *before* the freeze rather than at 09:55, so it is started
here. **Append your lane's section; do not rewrite anyone else's** — same rule as
[active-work.md](active-work.md) and [build-log.md](build-log.md).

Each section answers the same four questions: **what works · what is stubbed · what is known-broken ·
how to run it.** Be honest in the third one — a green checklist that hides a gap costs more at 10:00
than the gap itself.

Setup for a fresh clone is in [setup.md](setup.md). Per-lane detail lives in each lane's `README.md`
and in `plans/2026-07-25-lane-<x>-*.md`.

---

## Lane E — `web/` · the dApp

**Docs:** [web/README.md](../web/README.md) · [plans/2026-07-25-lane-e-web.md](../plans/2026-07-25-lane-e-web.md)

### Run it

```sh
pnpm install                          # repo root — pnpm workspace
cp web/.env.example web/.env.local    # defaults already point at the fork
pnpm --filter @curator/web dev        # http://localhost:3000
```

**It runs with nothing else running.** No agent API, no anvil, no deployed contracts — every screen
falls back and says so in the header badge. Nothing to stand up first just to see the UI.

macOS needs nothing extra: Node 20+, `corepack enable`, no native modules, no webfont fetch at build
time.

### Wave 2 additions

- **`/docs`** — the constitutional text moved out of the vault view, plus the thing nothing else
  answers: the mandate lives **off-chain** (one JSON per vault under `AGENT_STATE_DIR`); only its
  keccak hash is on-chain, and that hash is the depositor's entire verification handle.
- **Disclaimer on every page**, not dismissible. A deep-linked vault from a shared URL is exactly
  where someone lands with no context beside a working deposit form.
- **Holdings are a donut**, zero balances filtered, `committed_to_venue` preserved (encumbered ≠
  sent away). **Aqua positions** get their own panel with the SwapVM curve and maker fee, pulled
  from the decision that shipped them.
- **Genesis** offers Lane F's preset archetypes (each leading with what it *gives up*), one-tap
  example replies, and the source/venue universe before the first question.
- **Banded acceptances** (`AgentAction.warnings`) render beside the reasoning.
- **`pnpm --filter @curator/web lint:imports`** — `'wagmi'` can never be imported again; it runs
  automatically as `prebuild`. The build log explains why `tsc` cannot catch that class of bug.
- **Venue strip** renders Lane D's capability manifest live from `GET /venues` (#61 + #73). `custody` — `virtual` / `claim` / `rotational` — is the primary badge: flattening those three is how a reader concludes `totalAssets()` is broken when it is right. Verified enriching with zero code change the moment Lane B shipped the route. Unavailable venues render *with* their reason rather than being filtered out.

> ⚠️ **If you are taking screenshots or recording the video, read cross-lane note #66 first.**
> `msedge --headless --window-size=375,H` lays out at 492px and *crops* — it does not give you the
> viewport you asked for, and the result looks exactly like a broken responsive layout.

### What works

- All three routes: `/` (thesis + vault list), `/create` (genesis chat → live mandate draft →
  deploy), `/vault/[address]` (state, holdings, mandate, deposit/withdraw, decision feed).
- **The decision feed** — the centrepiece. Each cycle renders as three columns: data consulted with
  per-fact provenance → the curator's reasoning verbatim → calldata and tx hashes. Renders all five
  `AgentAction` statuses including `rejected` and the blind-spots panel.
- Live integration with Lane B: all five frozen routes plus `/health`,
  `/vault/{addr}/mandate`, `/genesis/sources`. CORS confirmed working from the browser.
- Every read function in `lib/chain/abis.ts` verified by `eth_call` against Lane A's **deployed
  vault** `0x0E2c…B5d1` on the fork.
- Verified in a real browser at 1600 / 1280 / 820 px — no horizontal overflow.
- Dependency supply-chain policy: every package pinned exactly and ≥180 days old, install scripts
  disabled, enforced by `pnpm --filter @curator/web audit:deps` (exits non-zero on violation).

### Verified against the fully live stack

**The default config is the live config now.** The shared agent on `:8000` runs in live mode
(cross-lane note #48), so `cp web/.env.example web/.env.local && pnpm --filter @curator/web dev`
gives a green `LIVE` badge with no overrides. Re-verified at 10:05Z against 11 real cycles — 2
executed, 3 held, 4 rejected, 2 failed — with zero fixture notices on the page.

> Always check the badge rather than assuming. If the agent is restarted without `AGENT_MODE=live`
> it will answer every request perfectly over invented data, and the badge going amber is the only
> thing that tells you.

Earlier end-to-end confirmation at 07:38, which still holds:

- **Share price renders `1.00`** — derived from `total_assets`/`total_supply` with share decimals
  read from the contract, matching the chain exactly (`convertToAssets(1 share)` = `1000000`).
- **Holdings show Lane B's real rotation**: 1,750.00 USDC and 0.403383 WETH (≈749.88 in asset).
- **The yield comparison renders live Graph data**: moonwell 4.18% on $15.1M at 88% utilization vs
  aave-v3 3.48% on $173.2M at 85% — *"Deepest is aave-v3 at $173.2M — not the highest yield"*. That
  is the composability argument made visible, from two different Graph sources (`messari`, `aave`).
- Reasoning is real `qwen2.5:3b-instruct-q4_K_M` output, 132.3s for the cycle.

If the agent ever comes back up in fixture mode, this is the command that fixes it — restarting a
shared service is a standing authorization, not an intrusion
([unblock-by-default](../plans/2026-07-25-unblock-by-default.md) §2):

```sh
AGENT_MODE=live AGENT_DATA_REGISTRY=curator_data:build_registry \
AGENT_VENUE_REGISTRY=venues:get_venue uv run uvicorn agent.api.app:app --port 8000
```

### What is stubbed

- **Fixture fallback on every read**, by design — and it is *loud*, never silent. The header badge
  reads `LIVE` / `ON-CHAIN` / `FIXTURES` and reports the **worst** source on the page.
  **If it says `FIXTURES` during the demo, something on screen is not live.** That includes the case
  where Lane B is up but internally in fixture mode, which `GET /health` exposes.
- The fixture-mode genesis chat is a scripted interviewer, not a model. It only runs when Lane B is
  unreachable.
- ~~The Aqua ship rendering is proven against a fixture only.~~ **Closed — a real ship is in the
  feed.** `act_000036`, executed, tx `0x37f2d4da…`, and **model-authored** (`qwen2.5:3b-instruct-q4_K_M`,
  zero validation retries) rather than scripted. Its three plan steps render with the two Aqua
  approvals visible, which per #17 is the difference between a fillable position and one that looks
  perfect and silently never fills.

  **One thing to know about it:** that intent carries **no `program` field**, so the card reads
  *"program parameters not recorded on this decision"* rather than naming a curve. The zod schema
  defaults `shape` to `xyc` *inside* a program object, which is not the same as an absent program
  meaning `xyc` — printing a curve the decision never chose would be an unsourced claim about the
  most scrutinised part of the 1inch integration. `act_000020` (the older, scripted one) does carry
  `{shape: xyc, fee_bps: 30}` and renders it in full, so both paths are exercised against real data.

### ✅ The write path is verified on-chain — phase 2 §3.5 is closed

Ran after Lane B landed its `executeBatch`, against the shared fork:

```
approve   0x2a30080a856ea28828ada8c05089326599505dbb6c68048ca50cceb9a5f8dbaa   gas 55,425
deposit   0x03cba9d04d77d60dc6b7195023bf4213d9b091bc5cbd09d62cb7dff0c90086b3   gas 111,242
redeem    0xcd955921e40ec99cfa628e2037e683d6b5293beaf26b21d2ccb983730c98d34f   gas 111,528

100 USDC in -> 100.004782308691914570 shares minted, worth 99.999999 USDC
vault totalAssets  2499.880448 -> 2599.880448 -> 2499.880449
```

Reproduce with `pnpm --filter @curator/web verify:write-path`. It issues the same three calls with
the same ABI fragments and argument shapes as the deposit panel, waiting for each receipt the way
the UI does.

**It leaves the vault as it found it**: deposit, verify, then redeem exactly the shares just minted.
Net effect on the shared fork was **1 wei of USDC** (0.000001) and a shares delta of exactly zero —
that wei is ERC-4626 rounding in the vault's favour, which is the correct direction. Pass `--keep`
if you want the position left in place.

### What is known-broken / unverified

**The browser wallet handshake itself has not been exercised.** The write path above proves the
calldata and the share accounting; what it does not cover is connecting MetaMask and having it sign
— that is `@wagmi/core` plus the extension rather than our code, and it needs a human with a wallet
installed. *~2 min:* import anvil account #0 into MetaMask, add a network on
`http://localhost:8540` with chain id `8453`, open the vault from the list on `/` — **not a
hardcoded address**, because anvil keeps fork state in memory and any restart deploys a new vault and
rewrites `deployments/base-fork.json`. The app follows that file. If you do land on a dead address
the page now says **NO CONTRACT AT THIS ADDRESS** and explains why, instead of quietly falling back
to fixtures.

Smaller notes:

- Wallet support is **injected only** (MetaMask / Rabby / Coinbase extension, EIP-6963 discovery on).
  No WalletConnect, so no `NEXT_PUBLIC_WALLETCONNECT_ID` is needed — a phone wallet will not connect.
- Explorer links are deliberately suppressed when `NEXT_PUBLIC_RPC_URL` is a localhost address: the
  fork reports chain id 8453 like mainnet, so a BaseScan link would open a transaction that does not
  exist. Point that env var at a real RPC for the mainnet run and the links come back automatically.
- `VaultState.share_price` has no declared scale in the frozen schema and the two plausible
  conventions differ by 1e12, so the dashboard **derives** share price from `total_assets` /
  `total_supply` with share decimals read from the contract, and ignores the reported field. Do not
  "fix" this by trusting `share_price` — see cross-lane request #18.
- `web/.env.local` is gitignored; `web/.env.example` is the template and its defaults already point
  at the fork.

---

## Lane B — `agent/` · the curator harness

**Docs:** [agent/README.md](../agent/README.md) · [plans/2026-07-25-lane-b-agent.md](../plans/2026-07-25-lane-b-agent.md)

### 🔗 The first on-chain write — phase 2 §2.1 is closed

```
tx        0x789066d43ed0f54be903312dbc732a5c1b03ffb14dcdac0a5cd1e6f8ffa28a4b
block     49077778   status 1   gas 280,971
from      0x70997970C51812dc3A010C7d01b50e0d17dc79C8   (agent, AGENT_ROLE)
to        0x0E2c0e50E67B96C9C401C94e111a3DBD00DEB5d1   (vault)
selector  0x34fcd5be = executeBatch   (3 steps, atomic)
effect    2,500.000000 USDC / 0 WETH  ->  1,750.000000 USDC / 0.403383 WETH
          totalAssets 2500.000000 -> 2499.880448  (0.12 USDC execution cost, ~0.005%)
```

**11 logs, of which 4 are ERC-20 `Transfer` events** across USDC and WETH. That is the "onchain
execution of token transfers" 1inch asks to see, on a local fork — which their rules permit in
writing. The agent signed it itself with its own key: no human in the loop, which *is* the trust
model.

Built by Lane D's Uniswap adapter from a live quote (750 USDC → ~0.403526 WETH quoted, 0.403383
delivered — 0.035% off, well inside tolerance), submitted by this lane as a single `executeBatch`.

### Every transaction this lane has sent, and what each one taught

| tx | driver | outcome |
|---|---|---|
| `0x789066d4…` | plan submitted directly | ✅ the gate: 2,500 USDC → 1,750 USDC + 0.4034 WETH |
| `0x129da1a0…` | **fully autonomous tick**, 0 retries | ⚠️ right diagnosis, **wrong direction** — sold the underweight asset, 70/30 → 79/21 |
| `0x704f54a2…` | **fully autonomous tick**, 0 retries | ⚠️ right direction, **`pct_of_holdings: 1.0`** — 79/21 → **0/100**, breaching two mandate limits |
| `0xd10d560d…` | autonomous tick | ⚠️ **reverted on-chain.** Recorded as `failed` with the hash, vault untouched — that path had only ever been exercised by a stubbed test |
| `0x533e8e61…` | corrective, submitted directly | ✅ restored the book to **50.0% / 50.0%** |

**Vault left at 50.0% USDC / 50.0% WETH, total 2,498.51** — compliant with its stored mandate
(30% cash floor, 60% position ceiling), and holding both legs so Lane D can ship into Aqua. The
mandate for this vault lives in `.agent-state/mandates/` and is *not* the golden fixture: it sets
`max_slippage_bps: 300`, because Uniswap reports its 250 bps default tolerance and the golden
mandate's 50 would reject every plan (request #26).

The loop demonstrably runs end to end on its own. It also produced two bad trades in a row, and
**every validation layer then in place passed both** — correctly, because each decision was
internally consistent in every respect except the one that mattered. That is the honest headline
finding of this lane, and it is why there are now six layers rather than four:

- **Layer 5 — direction.** You may not sell an asset already below its target, nor buy one already
  above it.
- **Layer 6 — projected outcome.** The swap is projected forward at current valuations and the
  *result* is checked: the mandate's cash floor and position ceiling must survive, and a book that
  was materially off target must end closer to it.

Both compare the decision against **reality**, not against the mandate's text. The structural gap
they close is that mandate limits were being applied to what the model *declared it wanted* and never
to what its trade would actually *do*. Declared intent and realised effect are different things, and
only the second one spends money.

Weights come from the vault's own `value_in_asset` — the Chainlink figure `totalAssets()` is built
from — so the checks agree with the contract rather than forming a second opinion.

### ✅ R5 and R6 closed, and the guards demonstrated catching

**R6 — genesis deploys for real.** `POST /genesis/finalize` → `createVault` on-chain:
vault `0xCa58ff3ebe6CD8FAFB1f5f35Ae59e47e3BE59F29`, tx `0x9868681c…`, and **the `mandate_hash` shown
at genesis equals the on-chain `mandateHash`**. That equality is the depositor's only verification
handle. Genesis mints a *fresh* vault every run, so the shared vault is never touched.

**R5 — agent-driven Aqua ship**, tx `0x16eae7a2…`, three steps in Lane D's order as one atomic
`executeBatch`:

```
allowance USDC->Aqua   0 -> 500000000            (exactly the shipped amount)
allowance WETH->Aqua   0 -> 250000000000000000   (exactly the shipped amount)
vault                  50.0% / 50.0%, totalAssets 2,498.51 — UNCHANGED
```

> ⚠️ **The e2e plan gates R5 on `safeBalances()` being non-zero. That does not prove what it says.**
> Request #17 states plainly that a ship with *no* approvals yields "non-zero `safeBalances`, valid
> hash, no error, a successful tx" and is silently never fillable — so the plan's proof passes on
> exactly the dead position #17 exists to warn about. **The allowance is what separates the two
> cases**, needs only a standard ERC-20 ABI, and is what this lane asserts. Filed as request #39.

`totalAssets()` unchanged with a position open is the Pattern 1 proof: capital never left the vault.
That is what makes Aqua load-bearing rather than cosmetic.

**The guards, shown rejecting.** All three produced a journaled `AgentAction(status="rejected")` with
no plan and no transaction — visible in Lane E's feed:

| layer | fed a decision that | rejected with |
|---|---|---|
| 4 grounding | cited fact ids not in its snapshot | the invented ids *and* the real ones |
| 5 direction | sold the underweight asset | *"selling WETH, already at 50.0% against a 60.0% target … swap the other way"* |
| 6 outcome | swapped 100% of holdings | cash floor, position ceiling, and overshoot on both legs |

They had existed and been unit-tested but never been seen catching the failures that motivated them.
Now they have, on the live stack, against a real vault.

### Run it

```sh
uv sync --all-extras          # NOT --extra agent: a partial sync prunes other lanes' deps
uv run uvicorn agent.api.app:app --reload --port 8000
```

Starts with **no configuration at all** in fixture mode — no model, no chain, no other lane. For the
live stack:

```sh
AGENT_MODE=live \
AGENT_DATA_REGISTRY=curator_data:build_registry \
AGENT_VENUE_REGISTRY=venues:get_venue \
uv run uvicorn agent.api.app:app --port 8000
```

**Check `GET /health` first, always.** It reports what each seam *actually* resolved to and whether
the configured model is really pulled. `status: degraded` means live mode silently fell back — that
one call is the difference between a demo and a debugging session.

### What works

- All five frozen routes in both modes, plus `/health`, `/vault/{addr}/mandate`, `/genesis/sources`.
  Shapes are identical in fixture and live mode, so nothing for Lane E to migrate.
- **Four-layer output validation with reject-and-retry** (extract → schema → mandate → grounding).
  Verified against the real model: it caught an `action: "hold"` carrying a venue intent, fed the
  breach back, and the retry returned a valid decision.
- The decision cycle, journal, mandate store/hash/amend, and `Web3VaultClient` — reads *and* now
  writes, verified against Lane A's deployed vault.
- Bound to Lane C and Lane D's real packages via one env var each, zero code change on any side.
- **192 tests, 3 skipped, ~4s. No network, no model, no chain required.**

### Model, measured — do not guess this

`qwen2.5:3b-instruct-q4_K_M` on the build machine (i5-8265U, **no GPU**, DDR4-2400):
**median 32.7s per validated decision, zero retries.** Token generation is memory-bandwidth-bound,
so a 14B at Q4 streams ~9 GB per token and costs minutes per tick regardless of how well it reasons.
On different hardware, re-measure rather than assume:

```sh
uv run python -m agent.bench --model <tag> --runs 3
```

Ollama tags are **exact** — pull the exact tag in `.env` or `/health` reports degraded.

### What is known-broken / unverified

- **The model's prose is less trustworthy than its decisions.** On the first live run it cited fact
  `f6` — a $12.4M *liquidity* figure — as "the highest headline APY of 10.43%". A real fact id with
  an invented value, and it passed every layer then in place, because grounding catches **ids**, not
  fabricated **numbers**. The fact table was rewritten to make units unmisreadable and the misread
  stopped, but a 3B still makes qualitative errors (it called 91% utilization "low"). Every
  *decision* was mandate-legal throughout — which is the argument for enforcing constraints in code
  rather than trusting reasoning. Read the feed with that in mind.
- **Uniswap plans report 250 bps slippage** (the API's default tolerance, not expected impact), so a
  mandate with `max_slippage_bps: 50` — including the golden fixture — will **reject every Uniswap
  plan**. This is the harness working as designed, being conservative about a ceiling it cannot
  distinguish from an estimate. The vault mandate used for the write above sets 300. If a tick keeps
  coming back `rejected` with a slippage message, this is why.
- `createVault` has not been submitted on-chain; genesis in live mode falls back to the stub client
  unless `VAULT_FACTORY_ADDRESS` is set (it is: `0x0282…F302D`).
- No mainnet run. `AGENT_PRIVATE_KEY` is the anvil #1 test key and is correct **for the fork only**.

### Gotchas that will cost you an hour

- **Set `OLLAMA_KEEP_ALIVE=30m` before the demo.** Ollama evicts an idle model after ~5 minutes, and
  the next tick then pays a ~2 GB reload before generating. A warm decision is ~33s; the first cold
  one exceeded a 120s budget and surfaced as `ModelUnavailable` — which reads as "the server is
  down" when it is merely slow. This fires exactly when the stack has been idle while someone
  explains the architecture. `model_timeout_s` now defaults to 300s so a cold load completes, but
  keeping the model warm is the real fix. **`keep_alive` in the request body does not work** —
  Ollama's OpenAI-compatible endpoint ignores it, verified. `curl localhost:11434/api/ps` shows
  what is resident and when it expires.
- **`AGENT_PRIVATE_KEY` must hold `AGENT_ROLE`.** On this fork that is anvil account **#1**
  (`0x7099…79C8`), not #0. The wrong key reads state perfectly and reverts every write on an
  AccessControl check — healthy-looking right until the first `executeBatch`. Compare the address the
  harness logs at startup against `GET /vault/{addr}/state` → `agent`.
- **A tick needs a mandate stored for that vault.** Genesis writes it; a vault deployed by Lane A's
  script has none, so `POST /tick` returns `failed: no mandate stored`. Store one first.
- Three integration tests reach the live Graph gateway and are skipped by default; run them with
  `AGENT_TEST_NETWORK=1`.

---

## Lane A — `contracts/` · the vault and the agent's authorization boundary

**Docs:** [contracts/README.md](../contracts/README.md) — the full integration surface ·
[plans/2026-07-25-lane-a-contracts.md](../plans/2026-07-25-lane-a-contracts.md)

### Run it

```sh
cd contracts
forge build
forge test            # 79 pass, 7 fork tests skip — no network needed
```

**A fresh clone needs nothing.** No `forge install`, no `git submodule update`, no network, no
credentials. Dependencies are vendored into `contracts/lib/` at pinned tags and committed;
`./script/install-deps.sh` regenerates them but you should not need to. **Verified by actually doing
it** — cloning this repo to a temp dir and running the two commands above.

On macOS, `foundryup` installs natively; there is no WSL step. Everything in `script/` is POSIX bash
that runs under the bash 3.2 macOS ships (no arrays, no `jq`).

Fork tests, when you have an RPC:

```sh
ANVIL_RPC_URL=http://127.0.0.1:8540 forge test   # 86 pass
```

Point it at a running `scripts/anvil-fork.sh` rather than upstream — anvil caches forked state, so
it is far kinder to a rate-limited endpoint.

### What works

- **`CuratedVault`** — ERC-4626, sole custodian (Pattern 1). `execute(target, value, data)` and
  `executeBatch(Call[])` behind `AGENT_ROLE` against a target allowlist; `approveVenue`;
  `totalAssets()` = base balance + registered holdings priced through Chainlink; `holdings()` returns
  the whole priced position in one call.
- **`VaultFactory`** — EIP-1167 clones, mutable default config that each vault snapshots and freezes.
- **86 tests.** 79 mock-based (no network) + 7 against real Base state.
- **Published and consumed by three lanes:** `contracts/abis/*.json` (flat ABI arrays) and
  `deployments/base-fork.json`. Lane D reads the allowlist from that file; Lane E verified every read
  function against the deployed vault; Lane B's `Web3VaultClient` reads it correctly.
- **Proven on-chain, by Lane B's real agent write** — tx
  `0x789066d43ed0f54be903312dbc732a5c1b03ffb14dcdac0a5cd1e6f8ffa28a4b` on the fork. One atomic
  `executeBatch` emitting three `Executed` events: `USDC.approve` (a *token* as target — request #8),
  `Permit2.approve`, then `UniversalRouter.execute` (the router from request #7). All three targets
  were on the allowlist. This is the best validation the lane has: `executeBatch` doing exactly what
  it was built for, and every answer given to Lane D holding up in production.
- **Chainlink valuation confirmed against a real mixed-holding vault.** The vault now holds 1,750
  USDC + 0.4034 WETH. Recomputing the WETH leg independently from the live feed answer gives
  `749880448`, which is exactly what `holdings()` reports — so `totalAssets()` = `2499880448`. Agent,
  contract and UI all agree.

### What is stubbed or deliberately absent

- **No pause, no emergency withdrawal, no human override.** Deliberate — the locked trust model
  ([initiate_plan.md](../plans/initiate_plan.md) §2). `DEFAULT_ADMIN_ROLE` is granted to nobody and
  grant/revoke/renounce all revert, so the role graph is frozen at genesis.
- **One base-asset unit is treated as exactly $1.** True enough for USDC; the single approximation in
  the share-price path. Pricing the asset leg through its own feed was left as Stretch.
- **The vault holds no native ETH** (no `receive()`). `execute`'s `value` parameter exists because the
  frozen `ExecutionPlan` shape has one; in practice it is always `"0"`. Native-ETH swap legs are
  unsupported — use WETH.
- **`aqua_strategies[]` is not tracked on-chain.** The vault does not know what an Aqua position is;
  the harness records it at ship time.
- **No ENS subnames.** Explicitly cut in phase 2 §3.4.

### Known-broken / unverified — read this before trusting anything

- **`script/verify.sh` has never been run against a live Blockscout instance.** It is written, its
  error paths and address extraction are tested, but nothing is deployed to real Base because
  `DEPLOYER_PRIVATE_KEY` is unfunded. Expect to debug it on first real use. Use Blockscout, not
  Etherscan — there is no free Etherscan path for Base (request #23).
- **`priceMaxAge` is `0` on the fork, which means staleness checking is OFF.** Required there: a
  pinned fork's feed `updatedAt` is frozen while `block.timestamp` advances, so any real bound starts
  failing minutes into a session. It is set automatically to 3600 on any non-fork network and the
  deploy script now **refuses** to deploy to one with it disabled.
- **No mainnet deployment.** The deploy script guards it (below) but the path is untested end to end.

### Gotchas that will cost you an hour

- **Shares are 18-decimal over a 6-decimal asset** (`_decimalsOffset() = 12`). So
  `convertToAssets(1e18)` — one whole share — returns a **6-decimal** number: `1000000` means 1.00
  USDC per share, *not* `1e18`. Lane E got this right; the Wave 0 fixture
  `packages/schema/fixtures/vault-state.json` has a `share_price` 10^12 too large for its own
  totals, so develop against the fixture but do not derive the formula from it.
- **`totalAssets()` reverts rather than returning a wrong number** when a feed for a token the vault
  actually *holds* is stale, zero, negative or mid-round. That blocks deposits and withdrawals, which
  is the intended failure — valuing a held token at zero would let a withdrawal quietly take value
  from everyone still in. A token with a **zero balance is skipped before its feed is read**, so a
  broken feed only bites while the vault holds that token.
- **A token the vault holds but was never registered for valuation is invisible to
  `totalAssets()`.** The sharpest edge in the design: the mandate must confine the agent to tokens
  the vault can price. `valuedTokens()` is WETH only on this deployment.
- **`cast` and `forge` hang on *direct* external HTTPS in this WSL setup** while `curl` to the same
  endpoint returns instantly. Not a blocker and probably not present on macOS: `anvil --fork-url`
  works fine, and once anvil holds the fork everything else talks to localhost. Point `forge test`
  and `forge script` at the anvil endpoint.
- **The deploy script will refuse a misconfigured mainnet run, on purpose.** It reverts with
  `UnsafeAnvilKeyOnRealNetwork` if the deployer, agent or guardian is an anvil account — their keys
  are published in Foundry's docs, and `AGENT_ROLE` can never be revoked — and with
  `StalenessCheckDisabledOnRealNetwork` if `priceMaxAge` is 0. An unrecognised `DEPLOY_NETWORK` is
  treated as real, so a typo fails safe. If it stops you, it is doing its job; set the env vars.

### Two traps in the deploy path, both now closed (worth knowing they existed)

- **A fork deploy ignores `DEPLOYER_PRIVATE_KEY` on purpose.** It is the funded *mainnet* wallet, so
  it has zero balance on a fresh fork — reading it meant the deploy worked in a bare shell and failed
  the moment `.env` was sourced, which every `scripts/*.sh` does. Fork deploys sign with anvil #0;
  `FORK_DEPLOYER_PRIVATE_KEY` overrides.
- **A failed deploy used to corrupt `deployments/base-fork.json`.** `forge script` simulates the whole
  script before broadcasting, so an unfunded deployer reached the publish step, wrote the file, and
  *then* failed — leaving four lanes reading a factory address with no bytecode. There is now a
  balance precheck that reverts with `DeployerCannotPayGas` before anything is written. If you ever
  add a side effect to that script, put it after the validation for the same reason.

### If you need to redeploy

```sh
DEPLOY_NETWORK=base-fork forge script script/Deploy.s.sol \
  --rpc-url http://127.0.0.1:8540 --broadcast
```

⚠️ **This overwrites `deployments/base-fork.json`, and Lanes B, D and E all read the vault address
from it.** The currently-deployed vault `0x0E2c0e50E67B96C9C401C94e111a3DBD00DEB5d1` holds real
positions those lanes assert against. Only redeploy if anvil has been restarted, and tell the other
lanes when you do.

Good news for a cold replay (the e2e plan's R8): a deploy signed by anvil #0 at nonce 0 is
deterministic, so on a fresh fork it recreates the vault **at the same address** — verified on a
scratch fork. The addresses in `deployments/base-fork.json` should not change at all.

For a real network, set `DEPLOY_NETWORK`, `DEPLOYER_PRIVATE_KEY`, `AGENT_ADDRESS` and
`GUARDIAN_ADDRESS` to funded, non-anvil values; `priceMaxAge` defaults to 3600 automatically. Then
`./script/verify.sh <network>`.

---

## Lane C — `data/` · the market data layer

**Status: Wave 2 complete.** Ten sources live, 285 tests, no chain contention —
this lane never writes to the chain, so nothing here can disturb the fork, and it is independent of
all nine e2e rungs.

**A snapshot takes ~7.4s** (was 17s). The remainder is the Token API, which takes 8–10s per call on
its own infrastructure regardless of page size; every other source answers in under a second. If a
tick ever needs to be faster, dropping `token_api` from the mandate costs only the price
cross-check — `chainlink` prices the same assets in ~0.5s.

### Run it

```bash
uv sync --all-extras                        # NOT --extra data; see gotchas
uv run pytest data/tests -q                 # 285 tests, no network, no credentials
uv run curator-data verify-live             # the live submission gate
uv run curator-data snapshot --assets USDC,WETH
uv run curator-data sources                 # what a mandate may grant
uv run curator-data protocols               # what is configured
```

### What works, verified live

| Source | Provides | Live status |
|---|---|---|
| `messari` | yield, tvl, utilization, liquidity | ✅ Moonwell. Uniswap V3 intermittent (indexer-side) |
| `aave` | yield, tvl, utilization | ✅ Aave V3 Base, ~$175M USDC market |
| `chainlink` | price | ✅ on-chain via the fork, no credential |
| `token_api` | price | ✅ derived from executed dex swaps |

A representative live snapshot:

```
moonwell   USDC   12.74% APY   $14.5M TVL   0.91 util
aave-v3    USDC    3.41% APY  $174.9M TVL   0.84 util
price WETH: $1,857.18  (via chainlink, token_api, spread 0.19%)
```

Two lending protocols merged from two independent sources, and **two mechanically independent price
sources cross-validating** — an oracle read and executed swap prices agreeing to 0.19%. A wide
spread between them is a real signal (stale oracle, manipulated pool, dislocated market) and is
surfaced as `disagreement`.

### Integration

Lane B binds via `AGENT_DATA_REGISTRY=curator_data:build_registry` (already set). The instance form
`curator_data.default:registry` also works. Both are pinned by tests.

Full interface in [data/README.md](../data/README.md).

### What is known-broken / unverified

- **x402 has never completed a payment — the wallet is unfunded, and that is the only thing left.**
  Verified against the live gateway that the payload format is correct and **the EIP-712 signature
  validates**: the gateway's refusal is `invalid_exact_evm_insufficient_balance`. Send a few dollars
  of USDC on real Base to `X402_PRIVATE_KEY` (`0x64D2…fBb7`) and it should settle at $0.01/query.
  Enable with `X402_ENABLED=true`. It is off by default and falls back to the API key on any
  failure, so it cannot break a demo.
- ~~`uvx curator-mcp` does not work~~ — **published 2026-07-25.** `curator-schema` 0.1.0,
  `curator-data` 0.2.0, `curator-mcp` 0.2.0 are on PyPI; `uvx curator-mcp` verified from a clean
  machine. Next release: `./data/publish.sh` (dry run) then `--publish`. **Bump the version first** —
  a PyPI version is permanent and cannot be re-uploaded.
- ~~The golden mandate does not grant `chainlink`~~ — resolved; it now grants
  `[messari, aave, chainlink, token_api]`.
- **Uniswap V3's subgraph is intermittent** — the gateway returns `bad indexers` or times out at
  ~20s. Not our code; it recovers on its own. Lending data does not depend on it.
- **Prices only cover configured assets.** Chainlink feeds live in `sources/feeds.py`, token
  addresses in `sources/tokens.py`. An unknown symbol produces a note naming the file to edit —
  never a guessed address.

### Gotchas that will cost you an hour

- **`uv sync --extra data` PRUNES every other lane's packages** from the shared venv. It silently
  uninstalled Lane B's `fastapi`/`web3` once. Always `uv sync --all-extras`.
- **The Token API's free plan caps `limit` at 10.** `limit=20` returns a 403 that looks like an auth
  failure but is a parameter complaint. `MAX_PAGE` pins it.
- **`token-api.thegraph.com` does not resolve** — that host is named in The Graph's own docs. The
  live host is `api.pinax.network/v1`. Do not "fix" the working default back to the broken one.
- **The subgraph gateway returns HTTP 200 for auth failures**, with the error inside the GraphQL
  `errors[]`. Status code alone will mislead you.
- **The Token API's `price` field flips with swap direction** — `1858.02` one way, `0.0005` the
  other. We compute from both legs by address instead; never read that field directly.
- Tests are hermetic by design (`data/tests/conftest.py` strips credentials and disables `.env`), so
  they behave identically on a fresh macOS clone. Live checks live in `verify-live`, deliberately.

---

## Lane D — `venues/` · four venues behind one port

**Status: Wave 2 complete.** **168 Python + 46 Foundry tests.** Lane B binds to this lane with zero
code change on either side.

| Venue | Role | Custody | State |
|---|---|---|---|
| `uniswap` | taker — rotates what the vault holds | `rotational` | ✅ live |
| `aqua` | maker — earns fees on what it holds | **`virtual`** — tokens never leave | ✅ live |
| `aave` | lender — earns interest | `claim` (1:1 rebasing aToken) | ✅ live |
| `morpho` | lender — curated MetaMorpho | `claim` (appreciating 4626 share) | ⏳ needs one registration, see below |

**Start here: `from venues import manifest`** — one JSON row per venue with intents, tokens,
custody, availability and the contracts it calls. Performs **no network I/O** (asserted by a test),
so it is safe on every render. Never hardcode a venue list; a test fails if the registry and the
manifest diverge, which is how the fully-built Aave venue stayed invisible for a whole wave.

**If something reverts: `from venues.reverts import describe; describe("0x…")`.** Eleven selectors
across Uniswap, Permit2, Aqua, MetaMorpho and the vault, each with the cause *and* the fix. This
exists because `0x39d35496` blocked R5 for hours — it was `V3TooLittleReceived()`, Uniswap's, while
every hypothesis was about 1inch. An unknown selector returns the search procedure rather than
nothing.

### Run it

```sh
uv sync --all-extras                      # NOT --extra venues: that prunes other lanes' packages
uv run pytest venues/tests                # offline, green with no credentials
uv run pytest venues/tests -m live        # real Uniswap API + a live RPC
```

Solidity (needs Foundry, in `wsl -d Ubuntu-24.04`; native on macOS):

```sh
cd venues/aqua/solidity     # Lane D's only Foundry project; named for its first contract
pnpm install --ignore-workspace           # the flag is REQUIRED — see below
forge test                                # encoding tests, offline
forge test --fork-url $BASE_RPC_URL       # + fork tests vs REAL Aqua and REAL Chainlink
sh build.sh                               # recompile + republish program_builder.json
```

### Making Morpho live — one registration, three steps

The venue is built and refuses to plan until this is done, because supplying into a token the vault
cannot value makes `totalAssets()` fall by the amount supplied with nothing erroring.

1. Deploy `ERC4626PriceFeed(vault=0xeE8F4eC5672F09119b96Ab6fB59C27E1b7e44b61,
   assetFeed=0x7e860098F58bBFC8648a4311b374B1D669a2bc6B, "gtUSDCp / USD")`.
2. `VaultFactory.setDefaultValuation(<share token>, <that feed>)` + `setDefaultTarget`.
3. **Create a new vault** — per-vault valuations are immutable, so existing vaults cannot lend here.

**Why a custom feed at all:** a MetaMorpho share *appreciates* rather than rebasing like an aToken,
so the underlying's Chainlink feed understates it — measured at **760 bps** and worsening every
block. `priceFeed()` only needs something answering `IAggregatorV3`, so the feed was written rather
than waited for. No `contracts/` change was required.

**You do not need Foundry to use this lane.** The compiled artifact is committed at
`venues/aqua/program_builder.json`, so Python works on a fresh clone with no toolchain. Verified by
cloning and building a plan with nothing installed.

### What is proven, and against what

Everything below ran against the **real deployed Aqua and SwapVM contracts** on a Base mainnet fork,
not mocks:

- `ship()` accepted by the live registry; the strategy hash it returns equals the one we compute
  off-chain, so a later `dock()` targets the right position
- **`ship()` moves zero tokens** — the Pattern 1 custody invariant, asserted against the contract
  rather than against our description of it
- virtual balances match the shipped amounts; `dock()` clears them and is equally capital-neutral
- a **contract maker** works end to end (the vault has no private key — this is what
  `useAquaInsteadOfSignature = true` is for), with balances credited to the vault rather than to the
  agent EOA that authorised the call
- the full Uniswap path: live `/quote` → `/swap` → a schema-valid three-step `ExecutionPlan`

### ⚠️ The one open question — read before claiming anything about SwapVM

**We cannot yet claim the strategy prices correctly when executed.** `Aqua.ship()` stores the
strategy as *opaque bytes* and never runs it; the first execution is a taker fill.

`@1inch/swap-vm` was originally unpinned and resolved to the default branch, which numbers opcodes
completely differently from the deployed contract (banked hex enum vs positions in
`AquaOpcodes._opcodes()` — `XYCSwap` is `0x50` there and `17` on chain). Now pinned to **v1.0.1**,
and the builder derives every opcode from 1inch's own table via function pointers, so no opcode
number appears in our source.

The deployed table still does not match v1.0.1 exactly: it reads index 20 as `Decay` where v1.0.1
puts `Salt`, and no probed index produced a real constant-product quote. Full evidence and the next
step are in the header of `venues/aqua/solidity/test/AquaTakerFillFork.t.sol`, which is committed
and `vm.skip`ped rather than passing on a claim we cannot support.

**Next step: ask 1inch at the venue for the exact deployed source or ABI.** Five minutes for them,
hours of probing otherwise. Do **not** guess the indices — a wrong opcode ships successfully, looks
healthy, and misprices on fill, which is strictly worse than shipping no position.

Safe phrasing for the submission: *"the vault ships and docks real Aqua positions in SwapVM/Aqua
mode, verified on-chain"* — not *"the vault market-makes"*.

### Traps that will cost you time

- **`pnpm install` here must use `--ignore-workspace`.** Without it pnpm walks up, finds the repo
  root workspace, and installs the *web app's* dependencies into this directory while ignoring the
  local `package.json`. There is no `.npmrc` key for it. `build.sh` already passes the flag.
- **`uv sync --extra venues` prunes every other lane's packages** from the shared venv. Always
  `--all-extras`.
- **An Aqua ship with no approvals does not revert** — it produces a position that looks healthy in
  every observable way and is silently never fillable, because shipping moves nothing and the
  allowance is only consumed on fill. Never drop or reorder the approval steps. This is the only
  place in the lane where a missing step fails quietly (cross-lane request #17).
- **The allowlist is read from `deployments/base-fork.json`**, not hardcoded — the vault's
  `allowedTargets()` is guardian-mutable. Point `DEPLOYMENTS_FILE` at a mainnet manifest for the
  mainnet run.
- **The public `https://mainnet.base.org` supports `eth_call` state overrides**, which is why the
  program builder needs no deployment and no funded key. If you swap in an endpoint that lacks
  override support, set `AQUA_PROGRAM_BUILDER_ADDRESS` to a deployed builder instead.
- Uniswap's API rejects `routingPreference: CLASSIC` while echoing `routing: CLASSIC` back in
  successful responses, and returns `swap.value` hex-encoded while every sibling integer is decimal.
  Both are handled; both are written up in `FEEDBACK.md`.
- **A tight slippage band and a stale fork do not mix.** `UNISWAP_SLIPPAGE_BPS=50` is right for
  mainnet, where quote-to-execution is one block. The Trading API prices against **live** Base while
  a pinned fork executes hours behind — measured at 15.5 h of drift and a **72 bps** price gap, so a
  50 bps band reverts *deterministically* with `V3TooLittleReceived`. **Set ~150 bps for fork runs.**
  That is honest rather than a fudge: the widened band is absorbing fork staleness, not granting the
  agent looser real-world slippage.
- **A Morpho redeem can exceed withdrawal liquidity.** The shares are real; the underlying is lent
  out. Reverts with `ERC4626ExceededMaxRedeem` — read `maxRedeem(vault)` and redeem that, repeating
  as liquidity returns.
- **Do not trust a per-leg reading of the Uniswap `minOut`.** Where the minimum lives depends on the
  route the API picked: per-leg `amountOutMin` on a pure-V3 split, or a single trailing `SWEEP` on a
  mixed V3+V4 route where **every leg reads 0**. Both observed minutes apart. Only the aggregate
  means anything, and `amountIn` may be the `CONTRACT_BALANCE` sentinel (`1 << 255`) rather than a
  number. Three route-shape assumptions in one file have already been wrong.

### Outstanding

| Item | Owner |
|---|---|
| **Uniswap Developer Feedback Form** — `FEEDBACK.md` is written and substantive; the *form* is a separate hard requirement | **a human** |
| **Register the MetaMorpho valuation** (3 steps above) to make `morpho` live | whoever owns `scripts/` |
| **Expose `venues.manifest()` over HTTP** as `GET /venues` — Lane E's strip degrades to bare keys without it | Lane B |
| Taker fill / "the vault earns" demo | needs 1inch's deployed SwapVM source; **not** blocking anything else |
| Surfacing SwapVM program parameters in the UI | ✅ Lane E did it in Wave 2 |

**Nothing in this lane is waiting on another lane.** The two registration items are one-liners for
whoever owns the stack; the venue refuses safely until then rather than failing at execution.

Full interface: [venues/README.md](../venues/README.md). Plan and DoD:
[plans/2026-07-25-lane-d-venues.md](../plans/2026-07-25-lane-d-venues.md).
