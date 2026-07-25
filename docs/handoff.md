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

### Verified against the fully live stack

Run with Lane B in live mode and the badge goes green `LIVE`. Confirmed end to end at 07:38:

- **Share price renders `1.00`** — derived from `total_assets`/`total_supply` with share decimals
  read from the contract, matching the chain exactly (`convertToAssets(1 share)` = `1000000`).
- **Holdings show Lane B's real rotation**: 1,750.00 USDC and 0.403383 WETH (≈749.88 in asset).
- **The yield comparison renders live Graph data**: moonwell 4.18% on $15.1M at 88% utilization vs
  aave-v3 3.48% on $173.2M at 85% — *"Deepest is aave-v3 at $173.2M — not the highest yield"*. That
  is the composability argument made visible, from two different Graph sources (`messari`, `aave`).
- Reasoning is real `qwen2.5:3b-instruct-q4_K_M` output, 132.3s for the cycle.

```sh
# live agent on its own port, so a fixture-mode instance is left undisturbed
AGENT_MODE=live AGENT_DATA_REGISTRY=curator_data:build_registry \
AGENT_VENUE_REGISTRY=venues:get_venue uv run uvicorn agent.api.app:app --port 8001
NEXT_PUBLIC_API_URL=http://localhost:8001 pnpm --filter @curator/web dev
```

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

### If you need to redeploy

```sh
DEPLOY_NETWORK=base-fork forge script script/Deploy.s.sol \
  --rpc-url http://127.0.0.1:8540 --broadcast
```

⚠️ **This overwrites `deployments/base-fork.json`, and Lanes B, D and E all read the vault address
from it.** The currently-deployed vault `0x0E2c0e50E67B96C9C401C94e111a3DBD00DEB5d1` holds real
positions those lanes assert against. Only redeploy if anvil has been restarted, and tell the other
lanes when you do.

For a real network, set `DEPLOY_NETWORK`, `DEPLOYER_PRIVATE_KEY`, `AGENT_ADDRESS` and
`GUARDIAN_ADDRESS` to funded, non-anvil values; `priceMaxAge` defaults to 3600 automatically. Then
`./script/verify.sh <network>`.

---

## Lane C — `data/` · the market data layer

**Status: MVP + phase 2 extensions complete.** Four sources live, 180 tests, no chain contention —
this lane never writes to the chain, so nothing here can disturb the fork.

### Run it

```bash
uv sync --all-extras                        # NOT --extra data; see gotchas
uv run pytest data/tests -q                 # 180 tests, no network, no credentials
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
- **`uvx curator-mcp` does not work yet** — the packages are not on PyPI. `uv pip install
  ./data/curator_mcp` works today from a clone (verified in a clean 3.10 venv outside the repo).
  Publishing needs a token: [data/PUBLISHING.md](../data/PUBLISHING.md) has the verified commands.
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

## Lane D — `venues/` · Uniswap (taker) and 1inch Aqua/SwapVM (maker)

**Status: MVP complete, claim released.** Both venues implement the frozen `Venue` port. 59 Python
tests + 25 Foundry tests green; 1 Foundry test committed **skipped** on purpose (see the open
question below). Lane B is already bound to this lane with zero code change on either side.

### Run it

```sh
uv sync --all-extras                      # NOT --extra venues: that prunes other lanes' packages
uv run pytest venues/tests                # offline, green with no credentials
uv run pytest venues/tests -m live        # real Uniswap API + a live RPC
```

Solidity (needs Foundry, in `wsl -d Ubuntu-24.04`; native on macOS):

```sh
cd venues/aqua/solidity
pnpm install --ignore-workspace           # the flag is REQUIRED — see below
forge test                                # 13 encoding tests, offline
forge test --fork-url $BASE_RPC_URL       # + 12 against the REAL deployed Aqua
sh build.sh                               # recompile + republish program_builder.json
```

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

### Outstanding

| Item | Owner |
|---|---|
| **Uniswap Developer Feedback Form** — `FEEDBACK.md` is written and substantive; the *form* is a separate hard requirement | **a human** |
| Taker fill / "the vault earns" demo | blocked on the deployed opcode table above |
| Surfacing SwapVM program parameters in the UI | Lane E, optional; ask me for a decode helper |

Full interface: [venues/README.md](../venues/README.md). Plan and DoD:
[plans/2026-07-25-lane-d-venues.md](../plans/2026-07-25-lane-d-venues.md).
