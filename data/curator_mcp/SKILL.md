---
name: defi-market-analysis
description: Analyse DeFi lending markets and token prices on Base using the curator-mcp tools. Use when deciding where to allocate an asset for yield, comparing lending protocols, checking whether a headline APY is trustworthy, or pricing tokens. Covers reading yields correctly, weighing APY against liquidity depth and utilization, and citing data provenance.
---

# DeFi market analysis

How to use the `curator-mcp` tools to reach a defensible allocation decision instead of a plausible
one. The tools give you live market data; this document is about not misreading it.

## The tools

| Tool | Use it when |
|---|---|
| `compare_protocols(asset)` | You know the asset and must choose where it goes. **Start here.** |
| `get_market_yields(asset)` | You only need the rates, without the ranking commentary. |
| `list_markets(assets)` | You are surveying, not yet deciding. |
| `get_token_price(symbol)` | You need to value a holding in USD. |

---

## Three ways to misread this data

### 1. APY comes in two units. Do not mix them.

Every response carries both:

- `supply_apy` — a **fraction**. `0.0432` means 4.32%. Use this for arithmetic.
- `supply_apy_pct` — a **percentage**. `4.32` means 4.32%. Use this for display.

Multiplying a balance by `supply_apy_pct` overstates the return 100×. If you are computing, use
`supply_apy`. If you are writing a sentence for a human, use `supply_apy_pct` and add the `%`.

### 2. A non-empty `errors` array means you are looking at a partial market.

Every response has `errors`. When it is non-empty, one or more protocols could not be reached — so
the protocol you are about to call "the best available" may simply be the best of what *responded*.

**Say so.** "Aave has the highest APY of the two protocols that responded; Moonwell timed out" is a
useful sentence. "Aave has the highest APY" — when Moonwell was silently missing — is a false one.

### 3. The highest APY is frequently the wrong answer.

`compare_protocols` deliberately reports `best_apy` and `deepest_tvl` as separate fields because
they usually name different protocols. That gap *is* the decision. Reasoning that stops at the
highest number has not done the work.

---

## Reading a market properly

For each candidate, three numbers matter together:

**`supply_apy`** — what you earn. Necessary, not sufficient.

**`tvl_usd`** — how deep the market is. This is your exit. A position that is a large fraction of a
market's TVL cannot be unwound without moving the rate against you. As a rough discipline: a
position above ~1% of TVL deserves an explicit note; above ~5% treat depth as the binding
constraint, not the yield.

**`utilization`** — borrowed ÷ supplied, between 0 and 1. The most informative and most ignored:

| Utilization | What it means |
|---|---|
| < 0.5 | Rate is stable but low. Plenty of headroom to withdraw. |
| 0.5 – 0.8 | Healthy. The rate reflects real demand. |
| 0.8 – 0.9 | Rate is sensitive; small changes in demand move it materially. |
| **> 0.9** | **Withdrawals may be constrained.** The headline APY is volatile and often unrepresentative of what you'll actually average. Treat a high APY here as a warning, not a reward. |

A 5.9% APY at 0.95 utilization and a 4.3% APY at 0.6 utilization are not 1.6 percentage points
apart in any meaningful sense. The first can trap the position; the second is liquid.

---

## Citing your sources

Every number carries `fact_ids` and `sources`. Cite them when you explain a decision:

> Allocating to Aave V3 (4.32% APY, $84.2M TVL, 0.91 utilization) over Moonwell (5.87%, $12.1M,
> 0.96). The 1.55pp of extra yield does not compensate for a market one-seventh the depth at higher
> utilization — an exit would be constrained exactly when it mattered.
> *Facts: `messari:yield:aave-v3/usdc`, `messari:tvl:aave-v3/usdc`, `messari:utilization:aave-v3/usdc`.*

Fact ids are stable across snapshots for the same market, so decisions can be diffed over time.

**Never state a number these tools did not return.** If you need a figure that isn't in a response,
say it is unavailable. A fabricated yield is indistinguishable from a real one to the reader, and
acted on identically.

---

## A worked pattern

```
1. compare_protocols("USDC")
2. Check `errors`. Non-empty → note which protocols are missing and qualify everything below.
3. Read best_apy and deepest_tvl. Different? That is the tradeoff to resolve, explicitly.
4. For each candidate, check utilization. Above 0.9 → the APY is not what it appears.
5. Size the position against tvl_usd, not just against your own balance.
6. State the decision, the runner-up, and why the runner-up lost — citing fact ids.
```

If every candidate is unattractive, **say so and recommend holding.** "No market currently justifies
the move" is a complete answer, and a better one than allocating into a 0.97-utilization market
because it had the biggest number.

---

## Scope

Base mainnet by default. Lending and DEX data comes from Messari standardized subgraphs, prices from
the Token API — both via The Graph. The `curator://protocols` resource lists exactly what is
configured; if a protocol you expect is missing it is not being queried, and any "best available"
claim should be scoped to the list that is.
