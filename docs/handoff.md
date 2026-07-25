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

### What is stubbed

- **Fixture fallback on every read**, by design — and it is *loud*, never silent. The header badge
  reads `LIVE` / `ON-CHAIN` / `FIXTURES` and reports the **worst** source on the page.
  **If it says `FIXTURES` during the demo, something on screen is not live.** That includes the case
  where Lane B is up but internally in fixture mode, which `GET /health` exposes.
- The fixture-mode genesis chat is a scripted interviewer, not a model. It only runs when Lane B is
  unreachable.

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
`http://localhost:8540` with chain id `8453`, open `/vault/0x0E2c0e50E67B96C9C401C94e111a3DBD00DEB5d1`,
connect, deposit 1 USDC.

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
  an invented value, and it passed all four layers, because grounding catches fabricated **ids**, not
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
