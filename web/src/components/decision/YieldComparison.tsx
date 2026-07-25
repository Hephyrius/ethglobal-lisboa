import type { Fact } from '@curator/schema'
import { Badge } from '@/components/ui/Badge'
import { formatPercent, formatUsd } from '@/lib/format/units'

/**
 * The comparison the agent was actually making, in one glance.
 *
 * Individual fact cards show each observation faithfully but scatter the
 * comparison across six of them: a judge has to hold "moonwell 12.74%" in their
 * head while scrolling to "moonwell $14.5M TVL" and then to the Aave pair. The
 * interesting fact — **the highest headline yield is not the deepest market** —
 * is the relationship *between* those numbers, and a list of cards does not
 * render a relationship.
 *
 * So yields are pulled together into one table, sorted, with TVL and
 * utilization beside each and the spread stated. That is exactly the reasoning
 * the mandate asks for ("prefer lending markets with deep liquidity … over the
 * highest headline APY"), and this is where a reader can check the agent
 * actually did it.
 *
 * Built entirely from facts already in the snapshot — it invents nothing and
 * adds no data dependency. Renders only when there are at least two yields to
 * compare, because one row is not a comparison.
 */

type Row = {
  key: string
  protocol: string
  market?: string
  apy: number
  source: string
  tvl?: number
  utilization?: number
  cited: boolean
}

export function YieldComparison({ facts, citedIds }: { facts: Fact[]; citedIds: string[] }) {
  const rows = buildRows(facts, citedIds)
  if (rows.length < 2) return null

  const spreadBps = Math.round((rows[0].apy - rows[rows.length - 1].apy) * 10_000)
  const deepest = rows.reduce((best, row) => ((row.tvl ?? 0) > (best.tvl ?? 0) ? row : best), rows[0])
  const highestYieldIsDeepest = deepest.key === rows[0].key

  return (
    <div className="mb-3 rounded border border-line bg-raised/40 p-3">
      <div className="flex items-baseline justify-between gap-2">
        <span className="label">Yield comparison</span>
        <span className="text-2xs text-faint">{rows.length} markets</span>
      </div>

      <table className="tabular mt-2 w-full text-2xs">
        <thead>
          <tr className="text-faint">
            <th className="pb-1 text-left font-medium">Market</th>
            <th className="pb-1 text-right font-medium">APY</th>
            <th className="pb-1 text-right font-medium">TVL</th>
            <th className="pb-1 text-right font-medium">Util</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={row.key} className={index === 0 ? 'text-ink' : 'text-muted'}>
              <td className="py-0.5 pr-2">
                <span className={index === 0 ? 'font-medium' : undefined}>{row.protocol}</span>
                {row.market ? <span className="text-faint"> · {row.market}</span> : null}
                {!row.cited ? (
                  <span className="text-faint" title="Read, but not cited by the decision">
                    {' '}
                    ·
                  </span>
                ) : null}
              </td>
              <td className="py-0.5 text-right font-medium">{formatPercent(row.apy)}</td>
              <td className="py-0.5 text-right">{row.tvl ? formatUsd(row.tvl) : '—'}</td>
              <td className="py-0.5 text-right">
                {row.utilization !== undefined ? formatPercent(row.utilization, 0) : '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="mt-2 flex flex-wrap items-center gap-2 border-t border-line pt-2">
        <Badge tone="neutral">{spreadBps} bp spread</Badge>
        {!highestYieldIsDeepest && deepest.tvl ? (
          <span className="text-2xs text-muted">
            Deepest market is <span className="text-ink">{deepest.protocol}</span> at{' '}
            {formatUsd(deepest.tvl)} — not the highest yield.
          </span>
        ) : null}
      </div>
    </div>
  )
}

/** One row per protocol+market that reported a yield, enriched from its siblings. */
function buildRows(facts: Fact[], citedIds: string[]): Row[] {
  const keyOf = (fact: Fact) => `${fact.subject.protocol ?? '?'}|${fact.subject.market ?? ''}`

  const rows = new Map<string, Row>()
  for (const fact of facts) {
    if (fact.kind !== 'yield' || !fact.subject.protocol) continue
    rows.set(keyOf(fact), {
      key: keyOf(fact),
      protocol: fact.subject.protocol,
      market: fact.subject.market,
      apy: fact.value,
      source: fact.source,
      cited: citedIds.includes(fact.id),
    })
  }

  // Attach TVL and utilization reported for the same market by any source.
  for (const fact of facts) {
    const row = rows.get(keyOf(fact))
    if (!row) continue
    if (fact.kind === 'tvl') row.tvl = fact.value
    if (fact.kind === 'utilization') row.utilization = fact.value
  }

  return [...rows.values()].sort((a, b) => b.apy - a.apy)
}
