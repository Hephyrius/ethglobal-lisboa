import type { VaultState } from '@curator/schema'
import { Stat, StatRow } from '@/components/ui/Stat'
import { formatAmount, toBigInt } from '@/lib/format/units'

/**
 * Headline vault numbers.
 *
 * **Share price is derived, not read.** `VaultState.share_price` has no declared
 * scale in the frozen schema, and the two plausible conventions differ by 1e12
 * here: the golden fixture reports it 1e18-scaled, while the deployed vault's
 * `convertToAssets(1 share)` returns a 6-decimal asset amount. Lane A flagged
 * the same discrepancy from the contract side. Rather than guess — and print a
 * share price wrong by a factor of a million — this derives it from
 * `total_assets` and `total_supply`, whose scales *are* specified
 * (`asset_decimals` and the vault's own `decimals()`), and treats the reported
 * field as advisory. Filed as cross-lane request #12.
 *
 * Also deliberately absent: "shares outstanding". Same reason — rendering
 * `total_supply` requires the share scale, and when it cannot be read there is
 * no honest way to show it. TVL and share price stand on their own, and the
 * depositor's exact position is in the deposit panel, read from the chain.
 */
export function VaultStats({
  state,
  shareDecimals,
}: {
  state: VaultState
  shareDecimals?: number
}) {
  const committed = state.holdings.filter((holding) => holding.committed_to_venue !== null)
  const sharePrice = deriveSharePrice(state, shareDecimals)

  return (
    <StatRow>
      <Stat
        label="Total assets"
        value={formatAmount(state.total_assets, state.asset_decimals, { maxFractionDigits: 2 })}
        sub={`in ${assetSymbol(state)}`}
      />
      <Stat
        label="Share price"
        value={sharePrice ?? '—'}
        sub={sharePrice ? `${assetSymbol(state)} per share` : 'no shares issued'}
        tone={sharePrice ? 'ok' : 'default'}
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
        sub={state.aqua_strategies.length > 0 ? 'assets still in the vault' : 'no open strategies'}
        tone={state.aqua_strategies.length > 0 ? 'agent' : 'default'}
      />
    </StatRow>
  )
}

/**
 * assets-per-whole-share = total_assets · 10^shareDecimals / total_supply,
 * evaluated in bigint and formatted in asset decimals. Multiplying before
 * dividing keeps the precision that the other order would throw away.
 */
function deriveSharePrice(state: VaultState, shareDecimals = 18): string | null {
  const supply = toBigInt(state.total_supply)
  if (supply === 0n) return null

  const assets = toBigInt(state.total_assets)
  const perShare = (assets * 10n ** BigInt(shareDecimals)) / supply
  return formatAmount(perShare, state.asset_decimals, { maxFractionDigits: 4 })
}

function assetSymbol(state: VaultState): string {
  const match = state.holdings.find(
    (holding) => holding.token.toLowerCase() === state.asset.toLowerCase(),
  )
  return match?.symbol ?? 'asset'
}
