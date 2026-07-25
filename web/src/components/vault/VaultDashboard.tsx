'use client'

import type { VaultState } from '@curator/schema'
import { Badge } from '@/components/ui/Badge'
import { Card, CardBody } from '@/components/ui/Card'
import { ModeNotice } from '@/components/ui/ModeBadge'
import { DecisionFeed } from '@/components/decision/DecisionFeed'
import { MandateView } from '@/components/mandate/MandateView'
import { DepositWithdraw } from './DepositWithdraw'
import { Holdings } from './Holdings'
import { VaultHeader } from './VaultHeader'
import { VaultStats } from './VaultStats'
import { useVaultState } from '@/lib/api/vault-queries'
import { useVaultMandate } from '@/lib/mandate/use-mandate'
import { useShareDecimals } from '@/lib/chain/vault-contract'

export function VaultDashboard({ address }: { address: `0x${string}` }) {
  const { data, isPending } = useVaultState(address)
  const { mandate, provenance } = useVaultMandate(address)
  // Read rather than assumed — the share scale is what makes share price
  // correct or wrong by 1e12. See VaultStats.
  const shareDecimals = useShareDecimals(address)

  if (isPending || !data) {
    return <DashboardSkeleton />
  }

  const state = data.data

  return (
    <div className="space-y-8">
      <VaultHeader state={state} name={mandate.name} />

      <ModeNotice />

      <Card>
        <CardBody className="py-5">
          <VaultStats state={state} shareDecimals={shareDecimals.data} />
        </CardBody>
      </Card>

      <div className="grid gap-4 lg:grid-cols-3">
        <DepositWithdraw vault={address} />
        <div className="lg:col-span-2">
          <Holdings state={state} />
        </div>
      </div>

      <MandateView
        mandate={mandate}
        provenance={
          provenance === 'fixture' ? (
            <div className="rounded-lg border border-warn/25 bg-warn/[0.06] px-3 py-2.5">
              <div className="flex items-center gap-2">
                <Badge tone="warn">SAMPLE MANDATE</Badge>
              </div>
              <p className="mt-1.5 text-2xs leading-relaxed text-warn/90">
                The agent API has no mandate stored for this vault, and this browser did not create
                it. Showing the golden fixture so the viewer is not blank — it is{' '}
                <span className="font-medium">not</span> necessarily the mandate this vault was
                deployed with. Verify against <span className="font-mono">mandate_hash</span> above.
              </p>
            </div>
          ) : null
        }
      />

      <DecisionFeed address={address} tokenDecimals={tokenDecimals(state)} />
    </div>
  )
}

/**
 * symbol → decimals, from the vault's own holdings.
 *
 * `venue_intents` carry amounts as base-unit strings with no decimals attached,
 * and the vault is sole custodian, so its holdings are the authoritative place
 * to learn the scale of any token an intent can mention. Without this the
 * renderer shows raw base units rather than dividing by a guess.
 */
function tokenDecimals(state: VaultState): Record<string, number> {
  const map: Record<string, number> = {}
  for (const holding of state.holdings) {
    if (holding.decimals !== undefined) map[holding.symbol] = holding.decimals
  }
  return map
}

function DashboardSkeleton() {
  return (
    <div className="space-y-8">
      <div className="space-y-3">
        <div className="h-8 w-72 animate-pulse-soft rounded bg-line-bright/50" />
        <div className="h-4 w-96 animate-pulse-soft rounded bg-line-bright/30" />
      </div>
      <div className="card h-28 animate-pulse-soft" />
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="card h-64 animate-pulse-soft" />
        <div className="card h-64 animate-pulse-soft lg:col-span-2" />
      </div>
    </div>
  )
}
