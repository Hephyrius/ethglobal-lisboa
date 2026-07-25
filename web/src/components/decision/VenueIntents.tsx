import type { AllocationDecision, VenueIntent } from '@curator/schema'
import { Badge } from '@/components/ui/Badge'
import { formatAmount } from '@/lib/format/units'

/**
 * What the agent decided to *do*, before it became calldata.
 *
 * `venue_intents` is the layer between reasoning and execution: the venue, the
 * shape of the action, and — for Aqua — the **SwapVM program parameters the
 * agent chose**. Those parameters were previously invisible in the UI, which
 * made the single most distinctive part of the 1inch integration something a
 * judge had to take on faith. A `ship` renders here as "SwapVM · xyc curve ·
 * 30 bps fee", so the agent's choice of program is legible rather than implied.
 *
 * This sits between stage ② and stage ③ of the card on purpose: it is the last
 * thing that is still a *decision*, and the first thing that is nearly a
 * transaction.
 */
export function VenueIntents({
  intents,
  tokenDecimals,
}: {
  intents: NonNullable<AllocationDecision['venue_intents']>
  /** symbol → decimals, from the vault's holdings. Amounts are unscaled without it. */
  tokenDecimals?: Record<string, number>
}) {
  if (intents.length === 0) return null

  return (
    <div className="mt-4">
      <div className="label">Venue intents</div>
      <div className="mt-2 space-y-2">
        {intents.map((intent, index) => (
          <Intent key={index} intent={intent} tokenDecimals={tokenDecimals} />
        ))}
      </div>
    </div>
  )
}

function Intent({
  intent,
  tokenDecimals,
}: {
  intent: VenueIntent
  tokenDecimals?: Record<string, number>
}) {
  return (
    <div className="rounded border border-line bg-raised/50 px-3 py-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={intent.venue === 'aqua' ? 'agent' : 'data'}>{intent.venue}</Badge>
        <span className="text-2xs uppercase tracking-[0.09em] text-faint">{intent.kind}</span>
      </div>

      {intent.kind === 'swap' ? (
        <p className="mt-1.5 text-xs text-ink">
          <span className="font-medium">{intent.token_in}</span>
          <span className="text-faint"> → </span>
          <span className="font-medium">{intent.token_out}</span>
          <span className="text-muted">
            {' · '}
            {intent.pct_of_holdings !== undefined
              ? `${Math.round(intent.pct_of_holdings * 100)}% of holdings`
              : intent.amount_in
                ? describeAmount(intent.amount_in, intent.token_in, tokenDecimals)
                : 'amount decided at execution'}
          </span>
        </p>
      ) : null}

      {intent.kind === 'ship' ? (
        <>
          <SwapVmProgram program={intent.program} />
          <p className="mt-1.5 text-xs text-muted">
            {intent.tokens
              .map((token, index) => describeAmount(intent.amounts[index], token, tokenDecimals))
              .join(' · ')}
          </p>
        </>
      ) : null}

      {intent.kind === 'dock' ? (
        <p className="mt-1.5 font-mono text-2xs text-muted" title={intent.strategy_hash}>
          unwinding strategy {intent.strategy_hash.slice(0, 10)}…
        </p>
      ) : null}
    </div>
  )
}

/**
 * The 1inch-specific detail worth making loud: which SwapVM program the agent
 * composed, and on what terms.
 */
function SwapVmProgram({
  program,
}: {
  program?: { shape: 'xyc' | 'pegged'; fee_bps?: number }
}) {
  const shape = program?.shape ?? 'xyc'
  const feeBps = program?.fee_bps

  return (
    <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 rounded border border-agent/20 bg-agent/[0.05] px-2 py-1.5">
      <span className="text-2xs font-semibold uppercase tracking-[0.09em] text-agent">SwapVM</span>
      <span className="text-2xs text-muted">
        {shape === 'xyc' ? 'constant-product (xyc) curve' : 'pegged curve'}
        {feeBps !== undefined ? ` · ${feeBps} bps maker fee` : null}
      </span>
    </div>
  )
}

/**
 * Amounts cross as base-unit strings with no decimals attached, so they can
 * only be scaled if the vault told us the token's decimals. When it did not,
 * the raw value is shown and labelled as such rather than divided by a guess.
 */
function describeAmount(
  raw: string | undefined,
  symbol: string,
  tokenDecimals?: Record<string, number>,
): string {
  if (!raw) return symbol
  const decimals = tokenDecimals?.[symbol]
  return decimals === undefined
    ? `${raw} ${symbol} base units`
    : `${formatAmount(raw, decimals, { maxFractionDigits: 4 })} ${symbol}`
}
