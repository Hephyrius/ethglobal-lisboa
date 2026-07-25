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

## Fixture mode — read this before the demo

Every **read** falls back to `packages/schema/fixtures/` when the agent API is unreachable, errors,
or returns something that does not match the frozen schema. The fallback is **loud, never silent**:
each response carries the mode it came from and the header badge shows it on every page.

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
3. **`share_price` is 1e18-scaled whole-assets-per-whole-share**, so `1002506265664160401` is
   1.0025 USDC per share.
4. **Shares and assets do not share a decimal scale.** OZ's ERC-4626 decimals offset gives the
   fixture 6-decimal assets against 18-decimal shares, and `VaultState` carries only
   `asset_decimals`. So the dashboard deliberately **does not** show "shares outstanding" — printing
   it with an assumed scale would be wrong by 1e12. The depositor's own position is read from the
   chain, where the scale is known.
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

### Known limitation — the mandate viewer

No frozen route returns a `Mandate` for an existing vault (`VaultState` has `mandate_hash` only), so
the viewer reads what this browser saved at `POST /genesis/finalize` and otherwise shows the golden
fixture **badged `SAMPLE MANDATE`**, with a note to verify against `mandate_hash`. Filed as
cross-lane request #6; when it lands, `lib/mandate/store.ts` becomes a cache in front of the route
instead of the only source.

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
