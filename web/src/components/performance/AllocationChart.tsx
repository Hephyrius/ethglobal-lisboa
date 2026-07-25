'use client'

import { useMemo } from 'react'
import type { PerformancePoint } from '@curator/schema'
import { cn } from '@/lib/cn'

/**
 * Allocation over time, as a 100% stacked area.
 *
 * This is where deployment becomes *visible*. A share-price curve shows what the
 * vault is worth; this shows what it is made of, so a rotation into WETH, a
 * supply into a lending market and an Aqua commitment all read as a change in
 * shape rather than as a line in a feed.
 *
 * ## Normalised to 100%, not to dollars
 *
 * A vault that doubles in size has not changed strategy. Plotting absolute
 * values would make every deposit look like a reallocation, which is the
 * opposite of what this chart is for. Absolute size is the other chart's job.
 *
 * ## Points with no allocation are skipped, and the gap is left visible
 *
 * Backfilled points carry `total_assets` but no per-asset breakdown — decoding
 * `holdings()` from raw calldata is Lane A's to own and a wrong decode would put
 * a confidently wrong slice on the page. Those points are dropped from this
 * chart rather than filled in, so its history starts where real breakdowns
 * start. That is why it can be shorter than the price curve above it.
 */

const VIEW_W = 800
const VIEW_H = 120

/** Deliberately the semantic palette, not a rainbow. Base asset first. */
const BANDS = [
  'rgba(29,59,107,0.85)', // agent
  'rgba(27,106,102,0.80)', // data
  'rgba(20,107,60,0.75)', // ok
  'rgba(138,82,9,0.70)', // warn
  'rgba(158,43,32,0.65)', // bad
  'rgba(91,100,111,0.55)', // muted
]

export function AllocationChart({
  points,
  className,
}: {
  points: PerformancePoint[]
  className?: string
}) {
  const stack = useMemo(() => build(points), [points])

  if (!stack) {
    return (
      <div
        className={cn(
          'flex h-[120px] items-center justify-center rounded border border-dashed border-line px-4 text-center text-xs text-faint',
          className,
        )}
      >
        No per-asset breakdown recorded yet. Reconstructed history carries the vault&apos;s total
        worth but not its composition.
      </div>
    )
  }

  return (
    <div className={className}>
      <svg
        viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
        className="h-[120px] w-full"
        preserveAspectRatio="none"
        role="img"
        aria-label="Allocation over time, as a share of the vault"
      >
        {stack.bands.map((band, index) => (
          <path key={band.symbol} d={band.path} fill={BANDS[index % BANDS.length]}>
            <title>{band.symbol}</title>
          </path>
        ))}
      </svg>

      <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
        {stack.bands.map((band, index) => (
          <li key={band.symbol} className="flex items-center gap-1.5 text-2xs text-muted">
            <span
              aria-hidden
              className="inline-block h-2 w-2 rounded-sm"
              style={{ background: BANDS[index % BANDS.length] }}
            />
            <span className="font-medium text-ink">{band.symbol}</span>
            <span className="tabular">{(band.latest * 100).toFixed(1)}%</span>
            {band.committed ? (
              <span className="text-agent" title={`committed to ${band.committed}`}>
                · {band.committed}
              </span>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  )
}

function build(points: PerformancePoint[]) {
  const withAllocation = points.filter((point) => point.allocation.length > 0)
  if (withAllocation.length < 2) return null

  // Stable band order across the whole series. Order by final weight so the
  // legend reads as "what the vault is now", largest first.
  const finalWeights = weightsAt(withAllocation[withAllocation.length - 1])
  const symbols = Object.keys(finalWeights).sort((a, b) => finalWeights[b] - finalWeights[a])
  if (symbols.length === 0) return null

  const columns = withAllocation.map(weightsAt)
  const n = columns.length
  const x = (i: number) => (i / (n - 1)) * VIEW_W

  const bands: { symbol: string; path: string; latest: number; committed: string | null }[] = []
  const baseline = new Array(n).fill(0)

  for (const symbol of symbols) {
    const top = columns.map((column, i) => baseline[i] + (column[symbol] ?? 0))

    const upper = top.map((value, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(2)} ${((1 - value) * VIEW_H).toFixed(2)}`)
    const lower = baseline
      .map((value, i) => ({ value, i }))
      .reverse()
      .map(({ value, i }) => `L${x(i).toFixed(2)} ${((1 - value) * VIEW_H).toFixed(2)}`)

    bands.push({
      symbol,
      path: `${upper.join(' ')} ${lower.join(' ')} Z`,
      latest: finalWeights[symbol] ?? 0,
      committed: committedVenue(withAllocation[withAllocation.length - 1], symbol),
    })

    for (let i = 0; i < n; i += 1) baseline[i] = top[i]
  }

  return { bands }
}

/** Per-symbol share of the point's total, summing to 1. */
function weightsAt(point: PerformancePoint): Record<string, number> {
  const values: Record<string, number> = {}
  let total = 0
  for (const slice of point.allocation) {
    const value = Number(slice.value_in_asset)
    if (!Number.isFinite(value) || value <= 0) continue
    values[slice.symbol] = (values[slice.symbol] ?? 0) + value
    total += value
  }
  if (total <= 0) return {}
  for (const symbol of Object.keys(values)) values[symbol] /= total
  return values
}

function committedVenue(point: PerformancePoint, symbol: string): string | null {
  return point.allocation.find((slice) => slice.symbol === symbol)?.committed_to_venue ?? null
}
