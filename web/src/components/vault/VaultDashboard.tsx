'use client'

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

export function VaultDashboard({ address }: { address: `0x${string}` }) {
  const { data, isPending } = useVaultState(address)
  const { mandate, provenance } = useVaultMandate(address)

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
          <VaultStats state={state} />
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
                This browser did not create this vault, and no API route returns the mandate for an
                existing one yet. Showing the golden fixture so the viewer is not blank — it is{' '}
                <span className="font-medium">not</span> necessarily the mandate this vault was
                deployed with. Verify against{' '}
                <span className="font-mono">mandate_hash</span> above.
              </p>
            </div>
          ) : null
        }
      />

      <DecisionFeed address={address} />
    </div>
  )
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
