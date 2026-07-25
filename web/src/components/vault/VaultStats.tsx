import type { VaultState } from '@curator/schema'
import { Stat, StatRow } from '@/components/ui/Stat'
import { formatAmount, formatRatio } from '@/lib/format/units'

/**
 * Headline vault numbers.
 *
 * Deliberately **not** showing "shares outstanding": `VaultState` carries
 * `asset_decimals` but no share decimals, and OZ's ERC-4626 decimals offset
 * means shares and assets do not share a scale (the golden fixture has 6-decimal
 * assets against 18-decimal shares). Rendering that with an assumed scale would
 * print a number that is wrong by a factor of a million. TVL and share price are
 * both well-defined without it, and the depositor's own position is shown
 * exactly, read from the chain, in the deposit panel.
 *
 * `share_price` is 1e18-scaled whole-assets-per-whole-share, so 1002506265664160401
 * is 1.0025 USDC per share.
 */
export function VaultStats({ state }: { state: VaultState }) {
  const committed = state.holdings.filter((holding) => holding.committed_to_venue !== null)

  return (
    <StatRow>
      <Stat
        label="Total assets"
        value={formatAmount(state.total_assets, state.asset_decimals, { maxFractionDigits: 2 })}
        sub={`in ${assetSymbol(state)}`}
      />
      <Stat
        label="Share price"
        value={state.share_price ? formatRatio(state.share_price) : '—'}
        sub={state.share_price ? `${assetSymbol(state)} per share` : 'not reported'}
        tone={state.share_price ? 'ok' : 'default'}
      />
      <Stat
        label="Holdings"
        value={String(state.holdings.length)}
        sub={
          committed.length > 0
            ? `${committed.length} committed to a venue`
            : 'none committed to a venue'
        }
      />
      <Stat
        label="Aqua positions"
        value={String(state.aqua_strategies.length)}
        sub={state.aqua_strategies.length > 0 ? 'tokens still in the vault' : 'no open strategies'}
        tone={state.aqua_strategies.length > 0 ? 'agent' : 'default'}
      />
    </StatRow>
  )
}

function assetSymbol(state: VaultState): string {
  const match = state.holdings.find(
    (holding) => holding.token.toLowerCase() === state.asset.toLowerCase(),
  )
  return match?.symbol ?? 'asset'
}
