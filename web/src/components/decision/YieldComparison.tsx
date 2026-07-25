import type { Fact } from '@curator/schema'
import { Badge } from '@/components/ui/Badge'
import { formatPercent, formatUsd } from '@/lib/format/units'
import { cn } from '@/lib/cn'

/**
 * The comparison the agent was actually making, in one glance.
 *
 * Individual fact cards show each observation faithfully but scatter the
 * comparison across many of them: a reader has to hold "moonwell 4.18%" in
 * their head while scrolling to "moonwell $15.1M TVL" and then to the Aave
 * pair. The interesting fact — **the highest headline yield is not the deepest
 * market** — is the relationship *between* those numbers, and a list of cards
 * does not render a relationship.
 *
 * **Grouped by market asset, and that grouping is load-bearing.** Live
 * snapshots carry lending markets for several assets at once: Aave's Base
 * deployment reports USDC at 3.48% and WETH at 1.46%. Ranking those together
 * would compare yields on different assets and, worse, would name Aave's
 * $174.8M *WETH* market as "deeper" than a USDC market it has nothing to do
 * with. Only protocols lending the same asset are compared, and a market with
 * one protocol in it is not a comparison, so it is skipped.
 *
 * Built entirely from facts already in the snapshot — invents nothing and adds
 * no data dependency.
 */

type Row = {
  key: string
  protocol: string
  apy: number
  source: string
  tvl?: number
  utilization?: number
  cited: boolean
}

export function YieldComparison({ facts, citedIds }: { facts: Fact[]; citedIds: string[] }) {
  const groups = buildGroups(facts, citedIds)
  if (groups.length === 0) return null

  return (
    <div className="mb-3 space-y-2">
      {groups.map((group) => (
        <MarketComparison key={group.market} market={group.market} rows={group.rows} />
      ))}
    </div>
  )
}

function MarketComparison({ market, rows }: { market: string; rows: Row[] }) {
  const spreadBps = Math.round((rows[0].apy - rows[rows.length - 1].apy) * 10_000)
  const withTvl = rows.filter((row) => row.tvl !== undefined)
  const deepest = withTvl.length > 0 ? withTvl.reduce((a, b) => ((b.tvl ?? 0) > (a.tvl ?? 0) ? b : a)) : null
  const deepestIsNotBest = deepest !== null && deepest.key !== rows[0].key

  return (
    <div className="rounded border border-line bg-raised/40 p-3">
      <div className="flex items-baseline justify-between gap-2">
        <span className="label">Yield comparison · {market}</span>
        <span className="text-2xs text-faint">{rows.length} protocols</span>
      </div>

      {/* Scrolls inside its own box rather than making the page scroll
          sideways. Four numeric columns do not fit at 375px, and a table that
          widens the viewport breaks every other section on the page too. */}
      <div className="scroll-slim -mx-1 mt-2 overflow-x-auto px-1">
      <table className="tabular w-full min-w-[19rem] text-2xs">
        <thead>
          <tr className="text-faint">
            <th className="pb-1 text-left font-medium">Protocol</th>
            <th className="pb-1 text-right font-medium">APY</th>
            <th className="pb-1 text-right font-medium">TVL</th>
            <th className="pb-1 text-right font-medium">Util</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr
              key={row.key}
              className={cn(index === 0 ? 'text-ink' : 'text-muted', !row.cited && 'opacity-60')}
              title={row.cited ? undefined : 'Read, but not cited by the decision'}
            >
              <td className={cn('py-0.5 pr-2', index === 0 && 'font-medium')}>{row.protocol}</td>
              <td className="py-0.5 text-right font-medium">{formatPercent(row.apy)}</td>
              <td className="py-0.5 text-right">{row.tvl ? formatUsd(row.tvl) : '—'}</td>
              <td className="py-0.5 text-right">
                {row.utilization !== undefined ? formatPercent(row.utilization, 0) : '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-2 border-t border-line pt-2">
        <Badge tone="neutral">{spreadBps} bp spread</Badge>
        {deepestIsNotBest && deepest?.tvl ? (
          <span className="text-2xs text-muted">
            Deepest is <span className="text-ink">{deepest.protocol}</span> at{' '}
            {formatUsd(deepest.tvl)} — not the highest yield.
          </span>
        ) : null}
      </div>
    </div>
  )
}

/** One group per market asset; only groups with something to compare survive. */
function buildGroups(facts: Fact[], citedIds: string[]): Array<{ market: string; rows: Row[] }> {
  const keyOf = (fact: Fact) => `${fact.subject.protocol ?? '?'}|${fact.subject.market ?? ''}`

  const rows = new Map<string, Row & { market: string }>()
  for (const fact of facts) {
    if (fact.kind !== 'yield' || !fact.subject.protocol) continue
    rows.set(keyOf(fact), {
      key: keyOf(fact),
      market: fact.subject.market ?? '—',
      protocol: fact.subject.protocol,
      apy: fact.value,
      source: fact.source,
      cited: citedIds.includes(fact.id),
    })
  }

  // Attach TVL and utilization reported for the same protocol+market by any source.
  for (const fact of facts) {
    const row = rows.get(keyOf(fact))
    if (!row) continue
    if (fact.kind === 'tvl') row.tvl = fact.value
    if (fact.kind === 'utilization') row.utilization = fact.value
  }

  const byMarket = new Map<string, Row[]>()
  for (const row of rows.values()) {
    const existing = byMarket.get(row.market)
    if (existing) existing.push(row)
    else byMarket.set(row.market, [row])
  }

  return [...byMarket.entries()]
    .filter(([, group]) => group.length >= 2)
    .map(([market, group]) => ({ market, rows: group.sort((a, b) => b.apy - a.apy) }))
    .sort((a, b) => b.rows.length - a.rows.length)
}
