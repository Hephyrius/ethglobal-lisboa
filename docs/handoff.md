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

### What is known-broken / unverified

**Deposit and withdraw have never been signed.** This is the one real gap and the top item to close.
The read path is proven against the deployed vault and the write path uses the same ABI constants,
but no transaction has been submitted from this app — it needs a browser wallet holding a funded
key, and broadcasting from an unlocked anvil account would have mutated fork state other lanes
assert against.

*To close it (~2 min):* start the fork, import anvil account #0 into MetaMask, add a network on
`http://localhost:8540` with chain id `8453`, open `/vault/0x0E2c0e50E67B96C9C401C94e111a3DBD00DEB5d1`,
connect, deposit 1 USDC. The panel does approve-then-deposit and waits for each receipt.

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
