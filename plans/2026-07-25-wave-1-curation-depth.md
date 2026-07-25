# Wave 1 — curation depth

**Owner: single instance.** The five-lane split is over; Rule 7 isolation no longer applies and one
worker owns every directory. Rules 1–6 still do: claim in `docs/active-work.md`, commit and push per
meaningful change, `docs/build-log.md` entry for every non-trivial decision, docs are deliverables.

**The thesis this wave defends:** the vertical slice works, but it is *thin*. The agent reads yields
it cannot capture, holds two assets, has no memory of whether its last decision was any good, and
shows a depositor no evidence of performance. A judge reading the feed sees a bot doing swaps. This
wave turns it into something that looks like Gauntlet's vault pages and behaves like a curator.

---

## What is actually wrong today, measured

Aggregated over the 36 journalled actions on the fork (`.agent-state/actions/*.jsonl`):

| Count | Source | Message |
|---|---|---|
| 35 | `token_api` | `USDC is a quote token on this venue; a dex-derived price against itself is meaningless` |
| 27 | `messari` | `uniswap-v3: no response within 6s - skipped` |
| 8 | `messari` | `uniswap-v3: GatewayError: gateway timed out` |
| 2 | `token_api`, `aave` | `RuntimeError: Event loop is closed` |
| 3 | `token_api` | `HTTP 500 for /evm/pools`, `/evm/swaps`, `pool discovery returned nothing` |

Facts produced: `aave` 204, `messari` 105, `token_api` 32, `chainlink` 6. Statuses: 20 held,
7 rejected, 5 failed, 4 executed.

Read that table as a product problem, not a logging problem. **Every tick tells the model that two
of its four data sources are broken**, and the prompt (`_render_gaps`) instructs it to reason about
that explicitly. The top two rows are not failures at all — one is a structural non-applicability
(you cannot price USDC against USDC) and one is a subgraph we choose not to wait for. Reporting them
as failures makes the agent time its own data feed, which is exactly the wrong prior.

And the deeper gap: **`aave` produced 204 facts about lending yields, and there is no intent type in
the schema that can supply capital to a lending market.** The agent reads Aave's APY and its only
possible response is a Uniswap swap between USDC and WETH. That is the single most visible
incoherence in the product.

---

## Nine phases, in dependency order

Each phase is independently shippable and pushed before the next begins. Phases 1 and 2 come first
because they are cheap and because **P2 accrues value in wall-clock time** — a performance curve
cannot be built the hour before the demo.

| # | Phase | Why it is where it is |
|---|---|---|
| 1 | Data-feed health | Every later phase reads these traces. Fix the noise first. |
| 2 | Performance recording + backfill | Time-sensitive: history accumulates while later phases are built. |
| 3 | Universe expansion | More assets, more protocols, more free sources. Feeds P4 and P5. |
| 4 | Real protocol deployment | The biggest gap. Needs P3's allowlist and valuation work. |
| 5 | Reflection harness | Needs P2's outcome data and P4's richer action space. |
| 6 | Charts / Gauntlet-style vault page | Needs P2's series and P5's reflections to render. |
| 7 | Peer awareness + Aqua dock | Needs P2 (peer performance is the fact) and P4 (a shipped strategy to dock into). |
| 8 | Portfolio tracking | Independent; last because it is the smallest judge-facing win. |
| 9 | Bounty compliance audit | Last by definition — audits what the other eight built. |

---

## P1 · Data-feed health

**Goal: a healthy tick reports zero `snapshot.errors`.** Not "fewer" — zero. The errors channel is
shown to the model as *what you could not see*, so it must mean exactly that.

1. **`token_api` quote-token (35×).** Not an error. The venue prices everything *against* USDC, so
   a USDC/USDC price is a category mistake, not an outage. Suppress it as a `SourceError` and let
   `chainlink` be the price of record for the base asset. Add a source-level `provides` /
   `not_applicable` distinction so a source can say "this is not mine to answer" without claiming
   failure.
2. **`messari` uniswap-v3 timeout (35× across two shapes).** The 6s per-protocol budget is right —
   the comment justifying it is measured and correct. What is wrong is retrying a subgraph that has
   timed out 35 consecutive times and then reporting it. Add a **per-process circuit breaker**:
   after N consecutive timeouts a protocol is skipped without a request and noted once per snapshot
   at most, and the note goes in a new `snapshot.notes` channel rather than `errors`. Also
   re-evaluate whether uniswap-v3 belongs in the default protocol set at all now that P3 adds a
   DEX-data source that answers.
3. **`RuntimeError: Event loop is closed` (2×).** A real bug: an `httpx.AsyncClient` cached on a
   source instance outlives the event loop that created it, because the registry caches source
   instances for its lifetime while FastAPI/anyio may run ticks on different loops. Bind the client
   to its creating loop and rebuild it if the running loop has changed.
4. **`HTTP 500` from the Token API (3×).** Genuinely upstream and genuinely an error — keep it, but
   make it retry once with backoff before reporting.

**Schema change:** `MarketSnapshot.notes: list[SourceNote]` alongside `errors`. Prompt renders notes
as "context on your data sources", not as gaps.

**Proof:** run five consecutive ticks against the live stack; assert every snapshot has
`errors == []` and ≥ 4 sources contributing facts.

---

## P2 · Performance recording, backfill, and metrics

Nothing in the system records what a share was worth an hour ago. `AgentAction` carries no
`VaultState`, so the journal cannot be mined for it either. Two halves:

**Forward recording.** A `PerformanceRecorder` appends one row per observation to
`.agent-state/performance/<vault>.jsonl`: `{ts, block, share_price, total_assets, total_supply,
holdings:[{token,symbol,balance,value_in_asset}]}`. Written on every tick *and* by a lightweight
sampler so a vault that is not ticking still has a curve.

**Backfill from chain.** The anvil fork retains every block it has produced, so the true historical
curve is recoverable rather than invented: walk blocks from the vault's creation, `eth_call`
`convertToAssets(1e18)`, `totalAssets()` and `totalSupply()` at each, and write the same rows. This
is worth the effort precisely because the alternative — a chart that starts when we shipped the
chart — looks like a mock.

> On a pinned fork, blocks only advance when a transaction is mined, so the series is event-spaced,
> not time-spaced. Chart against timestamps and interpolate nothing; a flat segment between two
> trades is the truth.

**Metrics** (`agent/performance/metrics.py`), computed from the series, never stored: return since
inception, 24h / 7d return, annualised return, realised volatility, **max drawdown**, and a
Sharpe-style risk-adjusted figure. Every metric returns `None` rather than a number when the series
is too short to support it — a Sharpe ratio computed from four points is a lie with a decimal point.

**API:** `GET /vault/{addr}/performance?window=24h|7d|all` → `{points: [...], summary: {...}}`.
**Schema:** `performance.schema.json` + `PerformancePoint` / `PerformanceSummary` pydantic + zod.

---

## P3 · Universe expansion

### Assets

Verified live against the fork this session — token contract, symbol, decimals, and a Chainlink
Base feed with a fresh answer for each:

| Asset | Token | Feed | Dec |
|---|---|---|---|
| WETH | `0x4200…0006` | ETH/USD `0x7104…Bb70` | 18 |
| cbBTC | `0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf` | cbBTC/USD `0x07DA0E54543a844a80ABE69c8A12F22B3aA59f9D` | 8 |
| DAI | `0x50c5725949A6F0c72E6C4a641F24049A917DB0Cb` | DAI/USD `0x591e79239a7d679378eC8c847e5038150364C78F` | 18 |
| AERO | `0x940181a94A35A4569E4529A3CDfB74e38FD98631` | AERO/USD `0x4EC5970fC728C5f65ba413992CD5fF6FD70fcfF0` | 18 |

**wstETH is deliberately excluded.** Its Base feed `0x43a5…251a` reports `WSTETH / ETH` at 18
decimals, not USD — composing it with ETH/USD is a second oracle hop and a second staleness surface,
and `CuratedVault.totalAssets()` assumes a USD-quoted feed. A wrong price mints wrong shares, so it
stays out until it can be done properly.

**No contract change is required.** `VaultFactory.setDefaultValuation(token, feed)` and
`setDefaultTarget(target, bool)` are `onlyOwner`, and every vault created afterwards snapshots the
new defaults at `initialize`. So this is `scripts/expand-universe.sh`, not a redeploy.

> **Consequence to state plainly in the docs:** valuations are immutable per vault by design (a
> mutable valuation set lets whoever controls it register a bogus feed and mint shares — the
> `VaultFactory` header argues this and it is right). **Existing vaults keep their two-asset
> universe.** The wide universe applies to vaults created from now on. The demo therefore creates a
> fresh vault, and that is a feature: the genesis flow chooses the universe.

### Protocols and sources

Three new sources, all free and none token-gated, registered the same one-line way `chainlink` was:

- **`defillama`** — `https://yields.llama.fi/pools` filtered to Base. Dozens of protocols' APY and
  TVL in one unauthenticated call. This is the protocol-diversity fix: Aave and Moonwell become two
  rows among many rather than the whole comparison set.
- **`feargreed`** — `https://api.alternative.me/fng/`. One number, 0–100, daily. Needs a new
  `FactKind` of `sentiment`; do not smuggle it in as `ratio`, because the prompt's `_KIND_LABELS`
  table exists precisely to stop the model misreading one kind as another.
- **`gas`** — Base `eth_gasPrice` + a computed cost-per-rebalance estimate. The agent currently has
  no way to know that a 3 bps improvement is not worth a $0.40 transaction.

**The Graph stays the depth layer, not a peer.** DefiLlama is breadth and is explicitly labelled as
an unverified aggregator in its facts' provenance; Messari/Aave subgraphs remain the sources the
agent is told to prefer when they disagree. Say this in the README — a Graph judge will look for
exactly this dilution and the answer needs to be deliberate.

---

## P4 · Deploying capital to protocols

Two halves, both about the same complaint: *swaps happen, deployment does not.*

### 4a — Lending (the incoherence fix)

`aave` contributes 204 facts and there is no way to act on them. Fix:

- **Schema:** `SupplyIntent {venue:"aave", kind:"supply", asset, amount|pct_of_holdings}` and
  `WithdrawIntent {venue:"aave", kind:"withdraw", asset, amount|all}`. Widen
  `Mandate.permitted_venues` beyond the `Literal["uniswap","aqua"]` it is frozen at.
- **Venue:** `venues/aave/venue.py` building `approve` + `Pool.supply(asset, amount, onBehalfOf=vault,
  0)` and `Pool.withdraw(asset, amount, to=vault)`. Pool `0xA238Dd80C259a72e81d7e4664a9801593F98d1c5`,
  verified on the fork.
- **Valuation — and this is the part that would otherwise silently destroy the share price.** Supply
  USDC and the vault receives `aBasUSDC`, which `totalAssets()` does not count, so `totalAssets()`
  collapses to near zero the moment the agent earns yield for the first time. The fix needs no new
  contract: an aToken is a 1:1 rebasing claim on its underlying, so it is correctly valued by the
  **underlying's own Chainlink feed**. Register `aBasUSDC` → USDC/USD and `aBasWETH` → ETH/USD as
  factory default valuations. Both aToken addresses were confirmed two ways on the fork —
  `UNDERLYING_ASSET_ADDRESS()` and `Pool.getReserveData(USDC)[8]`:
  - `aBasUSDC` `0x4e65fE4DbA92790696d040ac24Aa414708F5c0AB` (6 dec, underlying USDC)
  - `aBasWETH` `0xD4a0e0b9149BCee3C920d2E00b5dE09138fd8bb7` (18 dec, underlying WETH)
  - Known ~1 bp artefact: raw USDC counts at par while aUSDC is valued at the USDC/USD feed
    (0.9999). It is a constant offset on a pinned fork, so it adds no false volatility. Document it
    rather than hiding it.
- **Holdings:** aTokens surface with `committed_to_venue: "aave"` so the UI and the prompt both show
  deployed capital as deployed rather than as a mystery balance.

### 4b — Aqua, actually proven (R5)

Still the unproven rung, and it is the 1inch centrepiece. `ship()` from the real vault, driven by an
agent tick, with the position asserted afterwards.

> **The trap, restated because it has already caught us once (request #17):** `Aqua.ship()`
> **succeeds with zero allowance** and produces a position that looks healthy in every observable
> way and is silently unfillable. A green transaction is not evidence. The gate is the vault→Aqua
> **ERC-20 allowance** plus non-zero `Aqua.safeBalances()` for the vault.

This is also the honest answer to "are we using the bounty things correctly": Aqua's whole point is
capital that is *committed* without leaving custody. A demo that only swaps has not used Aqua.

---

## P5 · Reflection — the agent grades its own homework

Today each tick is amnesiac. It sees holdings and market data and nothing about whether the last
five decisions worked. Add a **reflection block** to the curator prompt, built from P2's series:

For each of the last N executed actions: what it intended, what it cost (realised vs expected
slippage), and what the share price did over the window that followed. Plus the running summary —
return, drawdown, volatility — so the model can see whether it is winning.

Then close the loop the schema already supports: `MandateAmendment` exists and `apply_amendment`
enforces the invariants (`update_rules` in the golden mandate already forbids dropping `min_cash_pct`
below 0.1 and removing a sole-provider data source). Reflection is what should *drive* an amendment
— "three rotations in a row cost more in slippage than the yield spread they chased, so I am widening
my rebalance cooldown" is a mandate change with a reason, which is the interesting version of an
agent editing its own rules.

**And restate the objective.** The system prompt currently says "pursue its mandate". Make it
explicit: *maximise risk-adjusted return under the mandate's constraints* — a 4% yield taken with no
drawdown beats a 6% yield taken through a 20% swing, and the model should be told so in those words.

**Guardrail:** reflection must not become a reward hack. The prompt has to state that a rising share
price over one window is weak evidence, that drawdown counts against it, and that the honest answer
is often "not enough history to tell yet".

---

## P6 · The vault page, Gauntlet-style

Reference: Gauntlet's vault pages lead with the curve and the risk numbers, not with the mechanics.
Trad-fi, not web3 — light, serif headings, no neon, no pills.

- **Headline row:** TVL, share price, return since inception, 30d return, max drawdown, current APY.
- **Share-price / NAV chart** over the P2 series, with **executed decisions marked on the curve** so
  a judge can click a bump and read the reasoning that caused it. That link — data → reasoning → tx
  → *outcome* — is the thing no other submission will have.
- **Allocation over time** as a stacked area, which is where lending deployment and Aqua commitment
  become visible rather than implied.
- **Reflection panel** — the agent's own assessment of its recent decisions.

Charts: a small hand-rolled SVG line/area component, not a charting dependency. The JS dependency
policy requires ~6-month-old exactly-pinned packages, and adding a chart library the night before
submission is exactly the supply-chain risk that policy exists to prevent.

---

## P7 · Peer vaults — can Sam snoop on the USDC strategy?

Yes, and it should. Two mechanisms, one cheap and one that is a genuinely strong 1inch story:

**Observation.** A `peers` data source reads `VaultFactory.vaults()` and emits facts about every
*other* vault: its objective, current allocation weights, share-price return, and drawdown. The
agent can then reason "the conservative USDC vault is outperforming me with half my drawdown" —
which is real, verifiable, on-chain data about a real competitor.

**Imitation.** `AquaDockIntent` already exists in the frozen schema and is unused. Docking into
another vault's shipped Aqua strategy is *literally* "deploy into another agent's strategy", it
needs no new intent type, and it is a use of Aqua that nobody else at the hackathon will show.

**Do we want it?** Yes, with two things said out loud in the docs rather than discovered by a judge:
peer facts are advisory and every mandate constraint still binds, and copying introduces reflexivity
— if every vault copies the leader, the leader's edge is the crowd. Naming that risk is a stronger
answer than pretending it does not exist.

---

## P8 · Portfolio tracking

`GET /portfolio/{owner}` — across every vault the factory knows: shares held, current value, cost
basis from `Deposit`/`Withdraw` events, and P&L. A portfolio strip on the home page when a wallet is
connected. Background-refreshed, cached, and degrading to "connect a wallet" rather than an error.

---

## P9 · Bounty compliance audit

Re-read all three prize pages and verify, with file and line links in the README, that each
integration is used the way the sponsor asks — including the standalone-usability criteria:

- **The Graph** — Track 1's 25% "reusability & completeness" is still a hard fail while
  `curator-data` does not install from PyPI. Publishing `curator-schema` → `curator-data` →
  `curator-mcp` remains the single highest-value open item in the repo.
- **1inch** — Aqua used as a maker with capital actually committed (P4b), plus at least one
  token-moving transaction. SwapVM in Aqua mode.
- **Uniswap** — Trading API `POST /quote` → `POST /swap`, and the developer feedback form (human).

---

## Definition of done

- [ ] Five consecutive live ticks with `snapshot.errors == []` and ≥ 5 sources contributing
- [ ] A performance curve with real history, backfilled from chain, rendered on the vault page
- [ ] A vault holding ≥ 3 assets, with capital supplied to Aave and visible as an aToken holding
- [ ] An agent-driven Aqua ship gated on allowance + `safeBalances()`, not on a green transaction
- [ ] A tick whose reasoning cites its own prior decisions, and one mandate amendment with a reason
- [ ] Executed decisions clickable on the chart, linking curve → reasoning → tx
- [ ] One vault's decision referencing a peer vault's on-chain performance
- [ ] `docs/build-log.md` entries for every non-trivial choice above, especially the ones with a
      tradeoff: wstETH excluded, DefiLlama as breadth not depth, aToken valuation via the
      underlying's feed, no chart library

## Explicitly out of scope

Mainnet deployment (1inch accepts local forks in writing), a chart dependency, mutable per-vault
valuations, and any Stretch item from the master plan until the above is green and pushed.
