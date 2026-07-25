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

**It runs with nothing else running.** No agent API, no anvil, no deployed contracts. Every screen
falls back to the golden fixtures and says so. See [Fixture mode](#fixture-mode-read-this-before-the-demo).

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
| `/vault/[address]` | Vault state, holdings, mandate, deposit/withdraw, and the decision feed. |

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

Every response is parsed with the zod mirror from `@curator/schema` before it reaches a component.
Unvalidated JSON never enters the UI.

**Lane A — the chain.** Reads addresses from `deployments/base-fork.json` (never hardcoded) and
calls the **standard ERC-4626 / ERC-20 surface** declared in
[`src/lib/chain/abis.ts`](src/lib/chain/abis.ts): `asset`, `decimals`, `balanceOf`, `convertToAssets`,
`deposit`, `redeem`, `approve`, `allowance`. That subset is the standard, not Lane A's invention,
which is why deposits work before `contracts/out/**` exists. Anything Lane A adds on top
(`execute`, `approveVenue`, roles) is called by the agent, not by this UI.

## What it needs from other lanes

| From | What | Status |
|---|---|---|
| B | The five routes above | Fixtures until they land |
| B | **CORS** for `http://localhost:3000` — the browser calls the API directly (request #5) | open |
| B | A route returning the `Mandate` for an existing vault (request #6) | open — worked around, see below |
| A | ABIs + `deployments/base-fork.json` (request #2) | standard subset used meanwhile |

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
    decision/              THE CENTREPIECE — DecisionCard is the three-stage causal chain
    vault/                 header, stats, holdings, deposit/withdraw, dashboard shell
    mandate/               mandate viewer + the data-source grant list
    genesis/               chat panel, live mandate draft, deploy panel
    ui/                    Badge, Card, Button, Stat, AddressChip, ModeBadge
    wallet/                connect button
  lib/
    api/                   frozen routes, fetch+fallback client, fixtures, query hooks, mode context
    chain/                 wagmi config, React account bindings, ABIs, deployments, explorer
    format/                units (bigint-safe), facts, time
    mandate/               client-side mandate cache (workaround for request #6)
scripts/
  audit-dependency-age.mjs supply-chain policy check
```

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

**Not verified — deposit and withdraw have never been signed.** The read path is proven against the
real contract and the write path uses the same ABI constants, but no transaction has been submitted
from this app: that needs a browser wallet holding a funded key, and broadcasting from an unlocked
anvil account would mutate fork state other lanes assert against.

*To close it (~2 min):* run the fork, import anvil account #0 into MetaMask, add a network on
`http://localhost:8540` with chain id `8453`, open
`/vault/0x0E2c0e50E67B96C9C401C94e111a3DBD00DEB5d1`, connect, deposit 1 USDC. The panel does
approve-then-deposit and waits for each receipt.

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
