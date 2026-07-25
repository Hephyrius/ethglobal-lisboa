import type { Fact } from '@curator/schema'
import { formatPercent, formatUsd } from './units'

/**
 * A `Fact` is deliberately generic — a source describes what it knows and
 * leaves the rest unset — so rendering one is a small dispatch rather than a
 * fixed template. This module is where that dispatch lives, so every place the
 * UI shows an observation shows it identically.
 *
 * The invariant that matters here: `unit: "apy_fraction"` means 0.0432 is
 * 4.32%. Rendering that as "0.04%" or "4.32" would misreport the agent's
 * inputs, which is the one thing this app must never do.
 */

const KIND_LABELS: Record<Fact['kind'], string> = {
  yield: 'Yield',
  price: 'Price',
  tvl: 'TVL',
  liquidity: 'Liquidity',
  volatility: 'Volatility',
  utilization: 'Utilization',
  volume: 'Volume',
  // A market-mood index and a gas price are not market observations in the
  // same sense as the rest, and labelling them as such is how a reader (or a
  // model) mistakes one for a rate. See the same table in the curator prompt.
  sentiment: 'Sentiment',
  gas: 'Gas',
  // A prediction market's implied odds. Forward-looking and a *consensus about
  // the future*, which is a different kind of claim from every backward-looking
  // rate beside it — labelling it distinctly is what stops it being read as one.
  probability: 'Implied odds',
}

export function kindLabel(kind: Fact['kind']): string {
  return KIND_LABELS[kind] ?? kind
}

/** The formatted value, unit-aware. */
export function factValue(fact: Fact): string {
  switch (fact.unit) {
    case 'apy_fraction':
      return formatPercent(fact.value)
    case 'usd':
      return formatUsd(fact.value)
    case 'ratio':
      // Kind before unit: `sentiment` also arrives as a ratio and means
      // something entirely different. A utilization of 0.78 is "78% of
      // capacity"; a sentiment of 0.78 is extreme greed, and rendering the
      // second as the first is exactly the misread the kind labels exist for.
      if (fact.kind === 'sentiment') {
        return `${fact.value.toFixed(2)} / 1.00`
      }
      // Odds read as a chance, not as a share of anything: "62% chance" rather
      // than a bare "62%" sitting in a column of utilisation figures.
      if (fact.kind === 'probability') {
        return `${formatPercent(fact.value, 0)} chance`
      }
      // Utilization and similar ratios read far better as percentages.
      return formatPercent(fact.value, fact.value >= 0.1 ? 1 : 2)
    case 'bps':
      return `${fact.value} bps`
    case 'token_amount':
      return new Intl.NumberFormat('en-US', { maximumFractionDigits: 6 }).format(fact.value)
    default:
      return String(fact.value)
  }
}

/**
 * What the fact is *about*: "morpho-blue · USDC", "uniswap-v3 · USDC/WETH".
 * Built from whichever subject fields the source chose to populate.
 */
export function factSubject(fact: Fact): string {
  const { protocol, market, token, pair } = fact.subject
  const parts: string[] = []
  if (protocol) parts.push(protocol)
  if (pair) parts.push(pair.join('/'))
  else if (market) parts.push(market)
  else if (token) parts.push(token)
  return parts.length > 0 ? parts.join(' · ') : (fact.subject.chain ?? 'base')
}

/** One-line summary, for dense contexts like a tooltip or a collapsed row. */
export function factHeadline(fact: Fact): string {
  return `${kindLabel(fact.kind)} ${factSubject(fact)} — ${factValue(fact)}`
}

/**
 * Facts grouped by the source that reported them. Provenance is the point of
 * the snapshot, so the UI groups by it in at least one place.
 */
export function groupBySource(facts: Fact[]): Array<{ source: string; facts: Fact[] }> {
  const bySource = new Map<string, Fact[]>()
  for (const fact of facts) {
    const existing = bySource.get(fact.source)
    if (existing) existing.push(fact)
    else bySource.set(fact.source, [fact])
  }
  return [...bySource.entries()]
    .map(([source, grouped]) => ({ source, facts: grouped }))
    .sort((a, b) => a.source.localeCompare(b.source))
}
