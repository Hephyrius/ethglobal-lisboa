'use client'

import { useMemo, useState } from 'react'
import type { VaultState } from '@curator/schema'
import { Badge } from '@/components/ui/Badge'
import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { AddressChip } from '@/components/ui/AddressChip'
import { TokenMark } from '@/components/ui/TokenMark'
import { formatAmount, toBigInt } from '@/lib/format/units'
import { cn } from '@/lib/cn'

/**
 * What the vault is made of, as a donut.
 *
 * Replaces the flat list, which gave a five-row table the same visual weight
 * whether one asset was 99% of the book or 20% — composition is a *proportion*
 * and a list does not render proportion.
 *
 * ## Assets the vault does not hold are not shown
 *
 * Zero balances are filtered out. A row reading `0.00` is not information; it
 * is a permitted asset the agent has chosen not to hold, which belongs in the
 * mandate (where it is listed) rather than in a statement of holdings.
 *
 * ## `committed_to_venue` survives the redesign, deliberately
 *
 * It flags **encumbrance, not location** — an Aqua position tracks a virtual
 * balance while the tokens stay in the vault. A reader who takes "committed" to
 * mean "sent away" concludes `totalAssets()` is overstated when it is exactly
 * right, so the label has to survive any change to how holdings are drawn.
 *
 * ## Sized by value, and it says so when it cannot be
 *
 * Slices are proportional to `value_in_asset`, the only field that makes two
 * different tokens comparable. A holding the API could not value is listed
 * below the chart rather than given an invented share — the same rule as
 * everywhere else here: show the gap, do not fill it.
 *
 * Colours match `AllocationChart` band-for-band so an asset reads as the same
 * colour in both, which is what lets the two charts be read together.
 */

/** Same palette and order as AllocationChart. Base asset first. */
const BANDS = [
  'rgba(29,59,107,0.85)',
  'rgba(27,106,102,0.80)',
  'rgba(20,107,60,0.75)',
  'rgba(138,82,9,0.70)',
  'rgba(158,43,32,0.65)',
  'rgba(91,100,111,0.55)',
]

const SIZE = 132
const STROKE = 22
const RADIUS = (SIZE - STROKE) / 2
const CIRCUMFERENCE = 2 * Math.PI * RADIUS

type Slice = {
  symbol: string
  token: string
  decimals: number
  balance: string
  value: bigint
  share: number
  committedTo: string | null
  colour: string
}

export function HoldingsDonut({ state }: { state: VaultState }) {
  const [active, setActive] = useState<string>()

  const { slices, unvalued, held } = useMemo(() => build(state), [state])

  return (
    <Card>
      <CardHeader
        title="Holdings"
        subtitle="The vault is sole custodian — committed balances are encumbered by a venue, not held by it."
      />
      <CardBody>
        {held.length === 0 ? (
          <p className="py-4 text-center text-xs text-faint">The vault holds nothing yet.</p>
        ) : (
          <div className="flex flex-col items-center gap-5 sm:flex-row sm:items-start sm:gap-6">
            {slices.length > 0 ? (
              <Donut slices={slices} active={active} onHover={setActive} />
            ) : null}

            <ul className="w-full min-w-0 flex-1 space-y-2.5">
              {slices.map((slice) => (
                <li
                  key={slice.token}
                  onMouseEnter={() => setActive(slice.token)}
                  onMouseLeave={() => setActive(undefined)}
                  className={cn(
                    'rounded px-2 py-1.5 transition-colors',
                    active === slice.token && 'bg-raised',
                  )}
                >
                  <div className="flex items-center gap-2">
                    <span
                      aria-hidden
                      className="h-2.5 w-2.5 shrink-0 rounded-sm"
                      style={{ background: slice.colour }}
                    />
                    <TokenMark symbol={slice.symbol} />
                    <span className="text-sm font-medium text-ink">{slice.symbol}</span>
                    {slice.committedTo ? (
                      <Badge
                        tone="agent"
                        title={`Backing an open position on ${slice.committedTo}. The tokens remain in the vault — this flags encumbrance, not location.`}
                      >
                        {slice.committedTo}
                      </Badge>
                    ) : null}
                    <span className="tabular ml-auto text-sm text-ink">
                      {Math.round(slice.share * 100)}%
                    </span>
                  </div>

                  <div className="mt-1 flex flex-wrap items-center justify-between gap-x-3 gap-y-1 pl-[1.125rem]">
                    <AddressChip address={slice.token} />
                    <span className="tabular text-2xs text-faint">
                      {formatAmount(slice.balance, slice.decimals)} {slice.symbol}
                    </span>
                  </div>
                </li>
              ))}

              {unvalued.map((holding) => (
                <li key={holding.token} className="rounded border border-warn/25 bg-warn/[0.05] px-2 py-1.5">
                  <div className="flex flex-wrap items-center gap-2">
                    <TokenMark symbol={holding.symbol} />
                    <span className="text-sm font-medium text-ink">{holding.symbol}</span>
                    <span className="tabular ml-auto text-2xs text-warn">not valued</span>
                  </div>
                  <p className="mt-1 text-2xs leading-relaxed text-warn/80">
                    Held, but no value was reported for it, so it has no share of the chart rather
                    than an invented one.
                  </p>
                </li>
              ))}
            </ul>
          </div>
        )}
      </CardBody>
    </Card>
  )
}

function Donut({
  slices,
  active,
  onHover,
}: {
  slices: Slice[]
  active?: string
  onHover: (token?: string) => void
}) {
  let offset = 0

  return (
    <svg
      viewBox={`0 0 ${SIZE} ${SIZE}`}
      className="h-[132px] w-[132px] shrink-0"
      role="img"
      aria-label="Holdings by share of vault value"
    >
      <g transform={`rotate(-90 ${SIZE / 2} ${SIZE / 2})`}>
        {slices.map((slice) => {
          const length = slice.share * CIRCUMFERENCE
          const dash = `${length} ${CIRCUMFERENCE - length}`
          const element = (
            <circle
              key={slice.token}
              cx={SIZE / 2}
              cy={SIZE / 2}
              r={RADIUS}
              fill="none"
              stroke={slice.colour}
              strokeWidth={active === slice.token ? STROKE + 3 : STROKE}
              strokeDasharray={dash}
              strokeDashoffset={-offset}
              onMouseEnter={() => onHover(slice.token)}
              onMouseLeave={() => onHover(undefined)}
              className="transition-[stroke-width]"
            />
          )
          offset += length
          return element
        })}
      </g>
    </svg>
  )
}

function build(state: VaultState) {
  // A zero balance is a permitted asset the agent chose not to hold. That
  // belongs in the mandate, not in a statement of what is held.
  const held = state.holdings.filter((holding) => toBigInt(holding.balance) > 0n)

  const valued = held.filter((holding) => toBigInt(holding.value_in_asset) > 0n)
  const unvalued = held.filter((holding) => toBigInt(holding.value_in_asset) === 0n)

  // Base asset first so its colour is stable across vaults, matching
  // AllocationChart's ordering.
  const ordered = [...valued].sort((a, b) => {
    const aIsBase = a.token.toLowerCase() === state.asset.toLowerCase()
    const bIsBase = b.token.toLowerCase() === state.asset.toLowerCase()
    if (aIsBase !== bIsBase) return aIsBase ? -1 : 1
    return Number(toBigInt(b.value_in_asset) - toBigInt(a.value_in_asset))
  })

  const total = ordered.reduce((sum, holding) => sum + toBigInt(holding.value_in_asset), 0n)

  const slices: Slice[] = ordered.map((holding, index) => {
    const value = toBigInt(holding.value_in_asset)
    return {
      symbol: holding.symbol,
      token: holding.token,
      decimals: holding.decimals ?? 18,
      balance: holding.balance,
      value,
      // Ratio in floating point is fine here: it drives a stroke length, not a
      // balance. The bigint work is done before the divide.
      share: total > 0n ? Number((value * 10_000n) / total) / 10_000 : 0,
      committedTo: holding.committed_to_venue,
      colour: BANDS[index % BANDS.length],
    }
  })

  return { slices, unvalued, held }
}
