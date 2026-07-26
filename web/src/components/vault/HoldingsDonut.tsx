'use client'

import { useMemo, useState } from 'react'
import type { VaultState } from '@curator/schema'
import { Badge } from '@/components/ui/Badge'
import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { AddressChip } from '@/components/ui/AddressChip'
import { TokenMark } from '@/components/ui/TokenMark'
import { formatAmount, toBigInt } from '@/lib/format/units'
import { useVaultYield } from '@/lib/api/yield-queries'
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
// Validated with the dataviz palette checker (light surface, categorical):
// lightness band, chroma floor, CVD separation, normal-vision floor and
// contrast all PASS. Worst adjacent pair is teal↔magenta at ΔE 9.2 (deutan),
// above the 8 floor.
//
// These are NOT the brand blues, and that is deliberate. A run of blues and
// greys FAILS badly as a categorical set: the two grey steps came out at
// ΔE 1.7 from each other — "hard to tell apart even with full colour vision" —
// and three bands fell under the chroma floor, i.e. they read as grey rather
// than as an identity. A near-monochrome brand simply cannot supply six
// categorical hues. The base asset keeps the brand blue; the rest step away
// far enough to be distinguishable.
//
// Solid, not alpha. The checker was run on these exact values; compositing
// them at 0.85 over white changes the colour and voids the result.
//
// No orange: it would sit next to the semantic `warn` amber, and status
// colours are reserved rather than reused as "series 5".
const BANDS = [
  '#005BCC', // base asset — the brand blue
  '#B23A7A',
  '#00A38F',
  '#7A5AD6',
  '#7C8794', // overflow / "other" — a neutral, not an identity
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
  /** The underlying a receipt token is a claim on, e.g. `aBasUSDC` -> `USDC`. */
  represents: string | null
  /**
   * Current rate as a fraction. Three distinct states, and collapsing any two
   * of them would misreport the book: `undefined` = not loaded yet, `null` =
   * no rate found, `0` = idle and genuinely earning nothing.
   */
  apy?: number | null
  apySource?: string | null
  colour: string
}

export function HoldingsDonut({ state }: { state: VaultState }) {
  const [active, setActive] = useState<string>()
  const yields = useVaultYield(state.address)

  const { slices: base, unvalued, held } = useMemo(() => build(state), [state])

  // Joined by token address rather than symbol: two holdings can share a
  // symbol across protocols, and a wrong join here would print one position's
  // rate against another's balance.
  const slices = useMemo(() => {
    const byToken = new Map(
      (yields.data?.positions ?? []).map((p) => [p.token.toLowerCase(), p]),
    )
    return base.map((slice) => {
      const match = byToken.get(slice.token.toLowerCase())
      return match
        ? { ...slice, apy: match.apy ?? null, apySource: match.source ?? null }
        : slice
    })
  }, [base, yields.data])

  return (
    <Card>
      <CardHeader
        title="Holdings"
        subtitle="The vault is sole custodian. Committed balances are encumbered by a venue, not held by it."
        right={
          /* The blended rate across the whole book, idle capital included at
             0%. Excluding idle would quietly report only the productive half
             and overstate what a depositor earns — which is the number they
             actually care about. Hidden rather than zeroed while loading or
             when nothing is known. */
          yields.data?.weighted_apy != null ? (
            <div className="text-right">
              <div className="tabular text-sm font-medium text-agent">
                {(yields.data.weighted_apy * 100).toFixed(2)}% APY
              </div>
              <div className="text-2xs text-faint">
                {yields.data.coverage >= 0.999
                  ? 'blended, whole book'
                  : `blended over ${Math.round(yields.data.coverage * 100)}% of the book`}
              </div>
            </div>
          ) : null
        }
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
                    {/* Mark and name follow the *underlying* where there is
                        one: a reader looking for their USDC should find it
                        under USDC, not under a receipt symbol they have never
                        seen. The receipt symbol is still shown, small, beside
                        it — dropping it entirely would hide which protocol
                        issued the claim, and that is the part a depositor
                        needs to assess the risk. */}
                    <TokenMark symbol={slice.represents ?? slice.symbol} />
                    <span className="text-sm font-medium text-ink">
                      {slice.represents ?? slice.symbol}
                    </span>
                    {slice.represents ? (
                      <span className="font-mono text-2xs text-faint" title={`Held as ${slice.symbol}, a receipt token representing ${slice.represents}.`}>
                        {slice.symbol}
                      </span>
                    ) : null}
                    {/* The rate this slice is actually earning. Idle capital
                        shows 0%, which is the point of showing it at all; a
                        position whose rate we could not find shows a dash,
                        because "earns nothing" and "unknown" are different
                        claims and 0% would state the wrong one. */}
                    {slice.apy !== undefined ? (
                      <span
                        className={cn(
                          'tabular text-2xs',
                          slice.apy === null
                            ? 'text-faint'
                            : slice.apy > 0
                              ? 'text-agent'
                              : 'text-muted',
                        )}
                        title={
                          slice.apy === null
                            ? 'No rate was found for this position, which is not the same as it earning nothing.'
                            : slice.apy === 0
                              ? 'Idle in the vault, earning nothing.'
                              : `Current rate${slice.apySource ? ` per ${slice.apySource}` : ''}.`
                        }
                      >
                        {slice.apy === null ? '—' : `${(slice.apy * 100).toFixed(2)}% APY`}
                      </span>
                    ) : null}
                    {slice.committedTo ? (
                      <Badge
                        tone="agent"
                        title={`Backing an open position on ${slice.committedTo}. The tokens remain in the vault. This flags encumbrance, not location.`}
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
      // What the receipt token is a claim *on*. `aBasUSDC` is 20,000 USDC
      // supplied to Aave, and rendering only the receipt symbol makes a
      // position the agent deliberately opened read as a mystery token —
      // which is what "the UI does not show protocol positions" looks like
      // from the outside, even though the balance was on screen all along.
      // Null means "not known to be a receipt token", so anything without it
      // still shows as itself.
      represents: holding.represents ?? null,
      colour: BANDS[index % BANDS.length],
    }
  })

  return { slices, unvalued, held }
}
