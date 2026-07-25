'use client'

import { useQuery } from '@tanstack/react-query'
import { z } from 'zod'
// This app mounts no WagmiProvider — it drives the wallet through @wagmi/core
// imperatively (see app/providers.tsx). Importing the React-hooks `useAccount`
// from 'wagmi' therefore threw WagmiProviderNotFoundError and took the whole
// page down. `@/lib/chain/account` exposes the same {address, isConnected}
// shape over the core API, which is what every other component here uses.
import { useAccount } from '@/lib/chain/account'
import { Card, CardBody } from '@/components/ui/Card'
import { Stat, StatRow } from '@/components/ui/Stat'
import { API_BASE } from '@/lib/api/routes'
import { formatAmount } from '@/lib/format/units'

/**
 * "How am *I* doing?" — the one question that spans vaults.
 *
 * Shown on the home page only when a wallet is connected. Disconnected is not a
 * degraded state and gets no placeholder: an empty panel captioned "connect a
 * wallet" is worse than no panel, because it occupies the space a reader is
 * scanning for content.
 *
 * ## What it deliberately does not show
 *
 * **No P&L.** That needs a cost basis — replaying Deposit/Withdraw events per
 * vault per wallet, through partial withdrawals and share transfers between
 * addresses. Every one of those is a way to be quietly wrong about someone's
 * money. What is shown is exact: shares, current worth from the vault's own
 * `convertToAssets`, and the *vault's* return since inception, labelled as the
 * vault's so a depositor who entered later cannot read it as theirs.
 */

const Position = z
  .object({
    vault: z.string(),
    symbol: z.string(),
    shares: z.string(),
    value_in_asset: z.string(),
    asset_decimals: z.number(),
    vault_return_pct: z.number().nullable().optional(),
  })
  .passthrough()

const PortfolioResponse = z
  .object({
    owner: z.string(),
    positions: z.array(Position).default([]),
    total_value: z.string(),
    asset_decimals: z.number(),
  })
  .passthrough()

const REFETCH_MS = 20_000

export function PortfolioStrip() {
  const { address, isConnected } = useAccount()

  const { data, isPending } = useQuery({
    queryKey: ['portfolio', address],
    queryFn: async () => {
      const response = await fetch(`${API_BASE}/portfolio/${address}`, {
        signal: AbortSignal.timeout(15_000),
      })
      if (!response.ok) throw new Error(`portfolio unavailable (${response.status})`)
      return PortfolioResponse.parse(await response.json())
    },
    enabled: Boolean(address) && isConnected,
    refetchInterval: REFETCH_MS,
    // A portfolio read walks every vault on the deployment, so a transient
    // failure is not worth three retries and a spinner the user watches.
    retry: 1,
  })

  if (!isConnected || !address) return null

  if (isPending) {
    return (
      <Card>
        <CardBody>
          <div className="h-16 animate-pulse-soft rounded bg-line-bright/30" />
        </CardBody>
      </Card>
    )
  }

  // An error or an empty portfolio are the same thing to a reader who has not
  // deposited: nothing to show. Saying "no positions yet" is true in both cases
  // and does not blame the reader for an outage.
  if (!data || data.positions.length === 0) {
    return (
      <Card>
        <CardBody className="py-5">
          <div className="label">Your positions</div>
          <p className="mt-1.5 text-sm text-muted">
            No positions yet. Deposit into a vault below and it will appear here.
          </p>
          {/* Said explicitly because the archetype flow produces exactly this
              state: a vault you deployed, holding nothing, so this panel is
              empty while the one below is not. Without the sentence that pair
              reads as the deployment having failed. */}
          <p className="mt-1 text-2xs text-faint">
            Deploying a vault does not create a position — that is tracked separately below.
          </p>
        </CardBody>
      </Card>
    )
  }

  return (
    <Card as="section">
      <CardBody className="space-y-4 py-5">
        <StatRow className="sm:grid-cols-2">
          <Stat
            label="Your total"
            value={formatAmount(data.total_value, data.asset_decimals, {
              maxFractionDigits: 2,
            })}
            sub="USDC across every vault you hold"
            tone="agent"
          />
          <Stat
            label="Vaults"
            value={String(data.positions.length)}
            sub={data.positions.length === 1 ? 'one position' : 'positions'}
          />
        </StatRow>

        <ul className="divide-y divide-line border-t border-line">
          {data.positions.map((position) => (
            <li key={position.vault} className="flex items-baseline gap-3 py-2">
              <a
                href={`/vault/${position.vault}`}
                className="min-w-0 flex-1 truncate text-sm font-medium text-agent hover:underline"
              >
                {position.symbol}
                <span className="ml-2 font-mono text-2xs text-faint">
                  {position.vault.slice(0, 10)}…
                </span>
              </a>
              <span className="tabular text-sm text-ink">
                {formatAmount(position.value_in_asset, position.asset_decimals, {
                  maxFractionDigits: 2,
                })}
              </span>
              <span
                className="tabular w-24 text-right text-2xs text-muted"
                // Labelled on the element, not just in the header: this is the
                // vault's record, and a depositor who entered later has not
                // earned it.
                title="the vault's return since inception, not your own"
              >
                {position.vault_return_pct === null || position.vault_return_pct === undefined
                  ? '—'
                  : `${position.vault_return_pct >= 0 ? '+' : ''}${(
                      position.vault_return_pct * 100
                    ).toFixed(3)}% vault`}
              </span>
            </li>
          ))}
        </ul>
      </CardBody>
    </Card>
  )
}
