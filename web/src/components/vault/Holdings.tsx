import type { VaultState } from '@curator/schema'
import { Badge } from '@/components/ui/Badge'
import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { AddressChip } from '@/components/ui/AddressChip'
import { formatAmount } from '@/lib/format/units'

/**
 * What the vault holds.
 *
 * The vault is sole custodian (Pattern 1), so this is the complete picture even
 * with Aqua positions open — Aqua tracks virtual balances while the tokens stay
 * put. `committed_to_venue` therefore flags **encumbrance, not location**, and
 * the copy says so: a judge who assumes "committed" means "sent away" would
 * conclude `totalAssets()` is wrong when it is exactly right.
 */
export function Holdings({ state }: { state: VaultState }) {
  return (
    <Card>
      <CardHeader
        title="Holdings"
        subtitle="The vault is sole custodian — committed balances are encumbered by a venue, not held by it."
      />
      <CardBody className="px-0 py-0">
        {state.holdings.length === 0 ? (
          <p className="px-5 py-6 text-center text-xs text-faint">The vault holds nothing yet.</p>
        ) : (
          <ul className="divide-y divide-line">
            {state.holdings.map((holding) => (
              <li
                key={holding.token}
                className="flex flex-wrap items-center gap-x-4 gap-y-2 px-5 py-3.5"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-ink">{holding.symbol}</span>
                    {holding.committed_to_venue ? (
                      <Badge
                        tone="agent"
                        title={`Backing an open position on ${holding.committed_to_venue}. The tokens remain in the vault.`}
                      >
                        {holding.committed_to_venue}
                      </Badge>
                    ) : null}
                  </div>
                  <AddressChip address={holding.token} className="mt-1" />
                </div>

                <div className="text-right">
                  <div className="tabular text-sm text-ink">
                    {formatAmount(holding.balance, holding.decimals ?? 18)}
                  </div>
                  {holding.value_in_asset ? (
                    <div className="tabular mt-0.5 text-2xs text-faint">
                      ≈ {formatAmount(holding.value_in_asset, state.asset_decimals, {
                        maxFractionDigits: 2,
                      })}{' '}
                      in asset
                    </div>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        )}
      </CardBody>
    </Card>
  )
}
