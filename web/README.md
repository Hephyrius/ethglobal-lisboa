# `web/` — Lane E · the dApp

The judge-facing surface. Genesis chat, vault dashboard, and the agent decision feed.

> Everything else in this repo is invisible at judging time except through this app. Its job is to
> make one claim believable: **an autonomous agent is curating this vault, and here is the
> evidence** — the data it consulted, with provenance, the reasoning it produced, and the
> transaction it sent.

---

## Run it

```sh
pnpm install                 # from the repo root — this is a pnpm workspace
cp web/.env.example web/.env.local
pnpm --filter @curator/web dev          # http://localhost:3000
```

| Command | |
|---|---|
| `pnpm --filter @curator/web dev` | dev server |
| `pnpm --filter @curator/web build` | production build (also type-checks) |
| `pnpm --filter @curator/web typecheck` | types only |
| `pnpm --filter @curator/web audit:deps` | supply-chain check — see [Dependencies](#dependencies) |
| `pnpm --filter @curator/web lint:imports` | fails on imports this app must never contain. Runs automatically as `prebuild`. |
| `pnpm --filter @curator/web verify:write-path` | approve → deposit → redeem against a running fork |

> **`lint:imports` exists for one specific bug and is worth understanding before you delete it.**
> `'wagmi'` is not a dependency of this app, but a stale copy sits at the *workspace root*
> `node_modules/`, so Node and webpack resolve it happily — the import compiles, builds, and then
> throws `WagmiProviderNotFoundError` in the browser, because nothing here mounts a `WagmiProvider`.
> That took the whole homepage down once (#58) and neither `tsc` nor `next build` can catch it.
> Use `@/lib/chain/account` for account state and `@wagmi/core` for actions.

**It runs with nothing else running.** No agent API, no anvil, no deployed contracts. Every screen
falls back to the golden fixtures and says so. See
[Data provenance](#data-provenance--read-this-before-the-demo).

**And the default config is the live config.** With the shared agent on `:8000` in live mode, those
same two commands give a green `LIVE` badge and real data — no overrides. If the badge is amber,
the agent came up in fixture mode; restarting it is a standing authorization, and the command is in
[docs/handoff.md](../docs/handoff.md).

### Environment

Next only reads env files from `web/`, so config lives in `web/.env.local` (gitignored) rather than
the repo-root `.env`. Values mirror the root `.env.example`. Nothing here is secret — the dApp holds
no keys; the agent holds the only one that matters.

| Var | Default | Meaning |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Lane B's FastAPI |
| `NEXT_PUBLIC_CHAIN_ID` | `8453` | Base. The fork keeps the same id. |
| `NEXT_PUBLIC_RPC_URL` | `http://localhost:8540` | Read RPC. A `localhost` value also switches BaseScan links **off** — see [Invariants](#assumptions--invariants). |
| `NEXT_PUBLIC_FIXTURES` | unset | `1` forces fixture mode even when the API is up. |

No `NEXT_PUBLIC_WALLETCONNECT_ID` — this lane is injected-wallet only, on purpose.

---

## Routes it serves

| Route | What it does |
|---|---|
| `/` | Thesis, and the list of known vaults (created here, deployed by Lane A, or the sample). |
| `/create` | Genesis. Chat → mandate assembles live → deploy → redirect to the new vault. |
| `/create` | Also: preset archetypes from `packages/schema/presets/`, one-tap example replies, and the source/venue universe rendered *before* the first question. |
| `/vault/[address]` | Vault state, holdings donut, open Aqua positions, mandate, deposit/withdraw, and the decision feed. |
| `/docs` | How it works — the trust model, **where the mandate actually lives**, the custody model, and what this deliberately is not. Linked from the header and from the vault page. |

## What it consumes

**Lane B — the five frozen routes** (master plan §8). Declared exactly once, in
[`src/lib/api/routes.ts`](src/lib/api/routes.ts):

```
POST /genesis/chat          {messages[]}   → {reply, mandate_draft?}
POST /genesis/finalize      {mandate}      → {mandate_hash, deploy_tx, vault}
GET  /vault/{addr}/state                   → VaultState
GET  /vault/{addr}/decisions?limit=        → AgentAction[]
POST /vault/{addr}/tick                    → AgentAction
```

Plus these, which are Lane B's own endpoints rather than part of the Wave 0 freeze, so they are
declared here with `.passthrough()` schemas and may gain fields without breaking this app:

```
GET  /health                               → {status, mode, …}   provenance badge
GET  /vault/{addr}/mandate                 → Mandate             mandate viewer
GET  /vault/{addr}/performance?window=     → VaultPerformance    track record
GET  /genesis/sources                      → {sources[], venues[]}
GET  /venues                               → VenueManifest[]     venue capability manifest
```

Every response is parsed with the zod mirror from `@curator/schema` before it reaches a component.
Unvalidated JSON never enters the UI.

`GET /venues` serves Lane D's capability manifest (#61, exposed by Lane B in #73). The strip renders
`custody` — `virtual` / `claim` / `rotational` — as the primary badge, because flattening those three
is how a reader concludes `totalAssets()` is broken when it is right. If the route is ever absent the
strip falls back to bare venue keys and says capability detail is unavailable; it does **not** guess,
because a description written in the UI cannot know what the registry actually holds.

**Lane A — the chain.** Reads addresses from `deployments/base-fork.json` (never hardcoded) and
calls the **standard ERC-4626 / ERC-20 surface** declared in
[`src/lib/chain/abis.ts`](src/lib/chain/abis.ts): `asset`, `decimals`, `balanceOf`, `convertToAssets`,
`deposit`, `redeem`, `approve`, `allowance`. That subset is the standard, not Lane A's invention,
which is why deposits work before `contracts/out/**` exists. Anything Lane A adds on top
(`execute`, `approveVenue`, roles) is called by the agent, not by this UI.

## What it needs from other lanes

| From | What | Status |
|---|---|---|
| B | The five frozen routes | ✅ live |
| B | **CORS** for `http://localhost:3000` — the browser calls the API directly (#5) | ✅ done |
| B | `GET /vault/{addr}/mandate` for a vault this browser did not create (#6) | ✅ done — the local cache is now only a second rung |
| B | `GET /venues` exposing Lane D's capability manifest (#73) | ✅ done |
| A | ABIs + `deployments/base-fork.json` (#2) | ✅ done — addresses always read from the file |
| B | A decision carrying `warnings[]`, so the banded-acceptance UI has something to show (§B3) | ⏳ renderer built and wired; 0 of 40 actions carry one yet |

> **After Lane B ships a route, the shared `:8000` needs a restart to serve it.** Lane F alone
> restarts the shared stack (Wave 2 §9), so ask rather than doing it. To verify against new API code
> without touching theirs, run your own instance on another port and point the dev server at it:
> `NEXT_PUBLIC_API_URL=http://localhost:8002 pnpm --filter @curator/web dev`.

---

## Data provenance — read this before the demo

Reads walk a three-rung ladder: **agent API → the chain → golden fixtures.**

The middle rung matters. Lane B's `/vault/{addr}/state` is itself only reading the ERC-4626
contract, so when that service is down there is no reason to drop all the way to invented numbers —
total assets, share price and balances are one `eth_call` away and they are real. Only what the
contract cannot know (decision history, the mandate behind `mandate_hash`) still needs a fixture.

The header badge reports the **worst** source feeding the page:

| Badge | Meaning |
|---|---|
| *(none)* | Nothing fetched yet — the landing page issues no API queries, and claiming LIVE there would assert something about data that was never loaded. |
| `LIVE` | Agent API reachable and reporting itself live. |
| `ON-CHAIN` | Agent API unreachable; these figures were read straight from the vault contract. Real. |
| `FIXTURES` | Something on this page is a golden fixture. |

**`GET /health` is folded into that aggregate, and this is the important part.** The agent API can be
up, healthy and answering every route perfectly *while itself running in fixture mode* — every
response schema-valid, every request a success, and the badge sitting on a confident green over
numbers that came out of `packages/schema/fixtures` on the other side of the wire. That is the
deepest version of exactly the trap the badge exists to prevent, so `mode: "fixture"` or
`status: "degraded"` from `/health` turns the badge amber no matter how well the requests went.

> **If the badge says `FIXTURES` during the demo, stop — something on screen is not live.**

The fallback is **loud, never silent**: each response carries the mode it came from.

> **If the badge says `FIXTURES` during the demo, stop — the numbers on screen are not live.**

That is the point. The Graph disqualifies mocked data on the demo path, and the realistic way that
goes wrong is not deliberate: it is not noticing the API fell over. A silent fallback is a trap; a
loud one is a safety rail you can see from across the room.

**Writes do not fall back.** `POST /genesis/finalize` fails honestly rather than returning a vault
address that was never deployed and a tx hash that does not exist. When it fails, the mandate stays
on screen and the UI offers a clearly-labelled fixture *preview* instead. Reads degrade; writes fail.

Falling back on **schema mismatch** is deliberate too: if Lane B drifts from the frozen interface,
that surfaces as an amber badge plus a legible zod error, not a white screen.

---

## Layout

```
src/
  app/                     routes + providers + global styles
  components/
    decision/              THE CENTREPIECE — DecisionCard is the three-stage causal chain,
                           plus venue intents (SwapVM params), yield comparison, banded warnings
    vault/                 header, stats, holdings donut, Aqua positions, deposit/withdraw, shell
    mandate/               mandate viewer + the data-source grant list
    genesis/               chat panel, live mandate draft, deploy panel, preset cards, universe strip
    venues/                venue capability strip (Lane D's manifest)
    performance/           track-record charts — hand-rolled SVG, no charting dependency
    portfolio/             cross-vault strip for a connected wallet
    layout/                header + the persistent disclaimer
    ui/                    Badge, Card, Button, Stat, AddressChip, ModeBadge, TokenMark
    wallet/                connect button
  lib/
    api/                   frozen routes, fetch+fallback client, fixtures, query hooks, mode context
    chain/                 wagmi config, React account bindings, ABIs, deployments, explorer
    format/                units (bigint-safe), facts, time
    mandate/               presets, suggested replies, client-side mandate cache
scripts/
  audit-dependency-age.mjs   supply-chain policy check, over the whole lockfile
  check-forbidden-imports.mjs imports this app must never contain (runs as prebuild)
  verify-vault-write-path.mjs approve → deposit → redeem against a running fork
```

### Two components worth knowing about before you change them

**`vault/HoldingsDonut.tsx`** — zero balances are filtered (a `0.00` row is a permitted asset the
agent chose not to hold, which belongs in the mandate) and slices are sized by `value_in_asset`, the
only field that makes two tokens comparable. A holding the API could not value is listed *below* the
chart rather than given an invented share. `committed_to_venue` survives the redesign deliberately —
see invariant 5.

**`vault/AquaPositions.tsx`** — an open Aqua strategy is the least self-explanatory thing on the
page: the vault is quoting as a maker, yet `totalAssets()` has not moved and the tokens are still in
holdings. Unexplained, that reads as double-counting. The curve and maker fee come from the
*decision* that shipped it, not from vault state — they were a choice, not chain state. **Ships whose
intent omits `program` render "parameters not recorded" rather than defaulting to `xyc`**: the schema
defaults `shape` *inside* a program object, which is not the same as an absent program meaning `xyc`,
and a real model-authored ship (`act_000036`) omitted it.

### The decision card

`components/decision/DecisionCard.tsx` renders one `AgentAction` as three columns, so the causality
is spatial rather than something the viewer reconstructs from a log:

```
①  DATA CONSULTED          ②  REASONING              ③  EXECUTED
   each Fact with the         the curator's own          calldata + tx hashes,
   source that reported       words, verbatim, plus      linked to BaseScan
   it and when                its target allocation      (suppressed on the fork)
```

Four details there carry the argument rather than decorate it:

- **`snapshot.errors[]` renders as "could not see."** A failing source degrades the snapshot instead
  of crashing the loop, so the agent routinely decides on incomplete information. An agent that
  reasons openly about the limits of its inputs is more trustworthy than one that appears
  omniscient — the golden decision cites a missing volatility series as its reason to size down.
- **`status: "rejected"` renders in full**, with the validation retry count. It is the only visible
  evidence that Lane B's output validation is load-bearing. A feed showing only successes looks like
  a feed with nothing to validate.
- **`facts_used` ids that do not resolve** against the snapshot render as *unresolved* rather than
  being dropped. The schema says that is how a model inventing numbers is caught; hiding them would
  defeat it.
- **Steps and tx hashes pair by index only when the counts match.** The schema declares no
  correspondence between them, so inventing one would be a guess presented as a fact.

---

## Assumptions & invariants

1. **Never `Number()` a uint256.** Amounts cross as decimal strings and exceed `MAX_SAFE_INTEGER`.
   All conversion goes through [`lib/format/units.ts`](src/lib/format/units.ts), which stays in
   bigint until after the scaling divide. A silently wrong TVL is the worst bug this app could ship.
2. **APY is a fraction** — `0.0432` renders as `4.32%`.
3. **`share_price` has no declared scale, so it is derived rather than trusted.** The Wave 0 fixture
   reports it 1e18-scaled; the deployed vault's `convertToAssets(1 whole share)` returns a 6-decimal
   asset amount. The two differ by 1e12, and guessing prints the headline number wrong by a factor
   of a million. The dashboard computes it from `total_assets` and `total_supply` — whose scales
   *are* specified — with share decimals read from the contract, and treats the reported field as
   advisory. It therefore renders correctly under either convention. (Cross-lane request #18.)
4. **Shares and assets do not share a decimal scale.** OZ's `_decimalsOffset() = 12` gives 6-decimal
   assets against 18-decimal shares, and `VaultState` carries only `asset_decimals`. So the
   dashboard deliberately **does not** show "shares outstanding" — printing it with an assumed scale
   would be wrong by 1e12. The depositor's own position is read from the chain, where the scale is
   known.
5. **`committed_to_venue` flags encumbrance, not location.** The vault is sole custodian (Pattern 1);
   Aqua tracks virtual balances while the tokens stay put. The copy says so explicitly, because a
   judge who reads "committed" as "sent away" would conclude `totalAssets()` is broken when it is
   exactly right.
6. **Explorer links are suppressed on a local RPC.** The fork reports chain id 8453 exactly like
   mainnet, so a link built from the chain id opens a transaction that does not exist. A dead
   BaseScan link in front of a judge reads as a fabricated transaction — worse than no link.
7. **The golden fixtures are parsed through the zod mirror at module load.** Wave 0's
   `test_conformance.py` checks them against the JSON Schema and *pydantic*; nothing checked them
   against *zod*. Parsing at import closes that half — and since the landing page is prerendered,
   any Python/TypeScript drift fails `pnpm build` rather than appearing in front of a judge.

### The mandate viewer

`GET /vault/{addr}/mandate` (cross-lane request #6, closed by Lane B) is the primary source. The
local cache written at `POST /genesis/finalize` is kept as a second rung — it still covers a vault
created in this browser while the API happens to be down — and the golden fixture is the last
resort, shown **badged `SAMPLE MANDATE`** with a note to verify against `mandate_hash`. A 404 from
that route is a normal answer, not a fault: it means no mandate is stored for a vault some other
harness deployed.

## Verification status

**Verified:** `pnpm build` and `tsc --noEmit` clean · all three routes rendered in a real browser ·
every read function in `lib/chain/abis.ts` exercised by `eth_call` against Lane A's **deployed vault**
on the fork · live integration with Lane B across all five frozen routes plus `/health`,
`/vault/{addr}/mandate` and `/genesis/sources` · the badge correctly reads `FIXTURES` while the agent
API is up but in fixture mode · golden fixtures parse through the zod mirror at build time.

**The write path is verified on-chain** — approve, deposit and redeem all landed against the
deployed vault on the fork, minting 100.004782308691914570 shares for 100 USDC and redeeming them
back. Reproduce with:

```sh
pnpm --filter @curator/web verify:write-path              # deposit, verify, redeem
pnpm --filter @curator/web verify:write-path -- --keep    # leave the position in place
```

It issues the same three calls with the same ABI fragments and argument shapes as the deposit
panel, and leaves the vault as it found it — the shared-fork delta was 1 wei of USDC (ERC-4626
rounding, in the vault's favour) and zero shares. Tx hashes are in
[docs/handoff.md](../docs/handoff.md).

**Still not exercised: the browser wallet handshake.** Connecting MetaMask and having it sign is
`@wagmi/core` plus the extension rather than our code, and needs a human with a wallet installed.
*~2 min:* import anvil account #0 into MetaMask, add a network on `http://localhost:8540` with chain
id `8453`, open the vault from the list on `/` (or `/vault/<demoVault.address from
deployments/base-fork.json>`), connect, deposit 1 USDC.

> Don't hardcode the vault address anywhere. Anvil holds fork state in memory, so the phase-2
> cold-start replay — and any restart — deploys a **new** vault and rewrites
> `deployments/base-fork.json`. The app already follows that file; if you land on a dead address the
> page says **NO CONTRACT AT THIS ADDRESS** and tells you why rather than quietly showing fixtures.

## Visual language

Institutional finance, not crypto-native: warm paper ground, serif headings, hairline rules, tabular
figures, tight corners, one sober accent, colour only where it carries meaning. The product's claim
is that an agent can do a job real allocators do, so it should look like it belongs in that world
rather than adopting the dark-with-neon convention of most DeFi front-ends. Colour tokens are
semantic (`agent`, `data`, `ok`, `warn`, `bad`) rather than literal, so the palette can move without
touching components. No webfont — the stacks resolve natively on macOS and Windows.

---

## Dependencies

Next 14 · React 18 · TypeScript · Tailwind · `@wagmi/core` + `viem` · `@tanstack/react-query` ·
zod (via `@curator/schema`).

**Every version is pinned exactly and is at least 180 days old**, install scripts are disabled, and
the whole resolved tree is checked by:

```sh
pnpm --filter @curator/web audit:deps          # exits non-zero if anything is too new
pnpm --filter @curator/web audit:deps -- --max-age-days 90
```

Notable consequence: this lane uses **`@wagmi/core` directly, not the `wagmi` React package**.
`wagmi` depends on `@wagmi/connectors`, which pulls ~347 packages we never import (the `@solana/*`
kit, Coinbase CDP SDK, MetaMask SDK, WalletConnect, socket.io, lit, preact, axios) — and eagerly
resolving that barrel breaks the webpack build on `@x402/evm`, an optional peer. The React bindings
we write instead are ~40 lines in [`lib/chain/account.ts`](src/lib/chain/account.ts). Full reasoning
in [`docs/build-log.md`](../docs/build-log.md).

Wallet support is **injected only** (MetaMask, Rabby, Coinbase extension; EIP-6963 discovery is on).
That drops `NEXT_PUBLIC_WALLETCONNECT_ID` from the critical path entirely.

## Cross-platform

No absolute paths, no PowerShell, no OS-specific config, and no `next/font/google` — that fetches at
build time, which would make a fresh clone depend on network access. `pnpm install && pnpm dev` is
the whole story on macOS.
