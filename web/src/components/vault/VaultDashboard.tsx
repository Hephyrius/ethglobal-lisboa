'use client'

import { useCallback, useState } from 'react'
import type { VaultState } from '@curator/schema'
import { Badge } from '@/components/ui/Badge'
import { Card, CardBody } from '@/components/ui/Card'
import { ModeNotice } from '@/components/ui/ModeBadge'
import { DecisionFeed } from '@/components/decision/DecisionFeed'
import { decisionAnchor } from '@/components/decision/DecisionCard'
import { PerformancePanel } from '@/components/performance/PerformancePanel'
import { MandateView } from '@/components/mandate/MandateView'
import { DepositWithdraw } from './DepositWithdraw'
import { HoldingsDonut } from './HoldingsDonut'
import { AquaPositions } from './AquaPositions'
import { PausedBanner } from './PausedBanner'
import { VaultHeader } from './VaultHeader'
import { VaultStats } from './VaultStats'
import { useVaultDecisions, useVaultState } from '@/lib/api/vault-queries'
import { useVaultMandate } from '@/lib/mandate/use-mandate'
import { useShareDecimals, useVaultExists } from '@/lib/chain/vault-contract'
import { networkLabel } from '@/lib/chain/explorer'

export function VaultDashboard({ address }: { address: `0x${string}` }) {
  const { data, isPending } = useVaultState(address)
  // Fetched here rather than only inside the feed so the track-record chart can
  // mark executed decisions on the curve. React Query dedupes the two callers
  // onto one request.
  const decisions = useVaultDecisions(address)
  const [highlighted, setHighlighted] = useState<string | null>(null)

  // Clicking a point on the price curve scrolls to the decision that caused
  // that step. Curve -> reasoning -> transaction is the argument the whole
  // project is making, and it only lands if the two are actually connected.
  const focusDecision = useCallback((id: string) => {
    setHighlighted(id)
    document.getElementById(decisionAnchor(id))?.scrollIntoView({
      behavior: 'smooth',
      block: 'center',
    })
  }, [])
  const { mandate, provenance } = useVaultMandate(address)
  // Read rather than assumed — the share scale is what makes share price
  // correct or wrong by 1e12. See VaultStats.
  const shareDecimals = useShareDecimals(address)
  // Anvil keeps fork state in memory: a restart destroys deployed vaults while
  // their addresses survive in localStorage, in deployments/base-fork.json and
  // in bookmarks. Catch that explicitly rather than leaving a silent fallback.
  const vaultExists = useVaultExists(address)

  if (isPending || !data) {
    return <DashboardSkeleton />
  }

  const state = data.data

  return (
    <div className="space-y-8">
      <VaultHeader state={state} name={mandate.name} />

      {vaultExists.data === false ? <MissingVaultNotice address={address} /> : null}

      {/* Above the stats on purpose. A halt changes how every number below it
          should be read, so it cannot sit further down the page than the
          figures it qualifies. */}
      <PausedBanner state={state} />

      <ModeNotice />

      <Card>
        <CardBody className="py-5">
          <VaultStats state={state} shareDecimals={shareDecimals.data} />
        </CardBody>
      </Card>

      <div className="grid gap-4 lg:grid-cols-3">
        <DepositWithdraw vault={address} paused={state.paused} />
        <div className="lg:col-span-2">
          <HoldingsDonut state={state} />
          <AquaPositions state={state} />
        </div>
      </div>

      <PerformancePanel
        address={address}
        state={state}
        decisions={decisions.data?.data ?? []}
        onSelectDecision={focusDecision}
      />

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

      <DecisionFeed
        address={address}
        highlightId={highlighted}
        context={{
          tokenDecimals: tokenDecimals(state),
          maxSlippageBps: mandate.constraints.max_slippage_bps,
        }}
      />
    </div>
  )
}

/**
 * The vault address resolves to nothing on the configured RPC.
 *
 * Almost always means anvil was restarted: fork state lives in memory, so the
 * deployed vault is gone while its address survives everywhere it was written
 * down. Anything else on this page is therefore describing a contract that no
 * longer exists, which is worth saying loudly rather than leaving the reader to
 * work out from an amber badge.
 */
function MissingVaultNotice({ address }: { address: string }) {
  return (
    <div className="rounded border border-bad/25 bg-bad/[0.05] px-4 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="bad">NO CONTRACT AT THIS ADDRESS</Badge>
        <span className="font-mono text-2xs text-bad/80">{address}</span>
      </div>
      <p className="mt-2 text-xs leading-relaxed text-bad/90">
        Nothing is deployed here on <span className="font-medium">{networkLabel}</span>. If anvil was
        restarted, its fork state was in memory and every vault deployed into it is gone — the
        address survives only in this browser and in{' '}
        <span className="font-mono">deployments/base-fork.json</span>. Re-run the deploy and seed
        scripts; the file will have the new address and this page will follow it.
      </p>
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
