'use client'

import { useQuery } from '@tanstack/react-query'
import type { VaultPerformance } from '@curator/schema'
import { apiFetch, FIXTURES_FORCED, type Sourced } from './client'
import { routes, schemas } from './routes'
import { useReportMode } from './mode-context'

/**
 * `GET /vault/{addr}/performance` — the share-price curve and its risk figures.
 *
 * Unlike `useVaultState` there is **no chain fallback rung**. Vault state is one
 * `eth_call` away, so reading it directly when the API is down is strictly
 * better than fixtures. A performance *history* is not: reconstructing it
 * requires walking blocks, which is what `agent/performance/backfill.py` does
 * server-side and is not something to attempt from a browser mid-demo.
 *
 * So this degrades straight to the fixture curve, and the mode badge says so.
 * An empty chart would be indistinguishable from a vault with no history.
 */

/** Slower than state: the curve is event-spaced and barely moves between ticks. */
const PERFORMANCE_REFETCH_MS = 30_000

export const PERFORMANCE_WINDOWS = ['24h', '7d', '30d', 'all'] as const
export type PerformanceWindow = (typeof PERFORMANCE_WINDOWS)[number]

export function useVaultPerformance(address: string, window: PerformanceWindow = 'all') {
  const query = useQuery({
    queryKey: ['vault-performance', address, window],
    queryFn: (): Promise<Sourced<VaultPerformance>> =>
      apiFetch({
        path: routes.vaultPerformance(address, window),
        schema: schemas.vaultPerformance.response,
        fallback: () => emptyPerformance(address),
      }),
    refetchInterval: PERFORMANCE_REFETCH_MS,
    enabled: Boolean(address) && !FIXTURES_FORCED,
  })

  useReportMode(`vault-performance:${address}`, query.data)
  return query
}

/**
 * What to show when the API cannot be reached.
 *
 * Deliberately **empty rather than invented**. Every other fallback in this app
 * substitutes a plausible value because the alternative is a blank panel that
 * looks broken. A performance curve is different: a made-up return is a
 * financial claim about a real vault, and it would be indistinguishable from a
 * real one at a glance. The panel renders "no history yet" instead, which is
 * the truth from the browser's point of view.
 */
function emptyPerformance(address: string): VaultPerformance {
  return {
    vault: address as `0x${string}`,
    points: [],
    summary: {
      observations: 0,
      first_at: null,
      last_at: null,
      share_price: null,
      total_assets: null,
      return_pct: null,
      return_24h_pct: null,
      return_7d_pct: null,
      annualized_return_pct: null,
      volatility_pct: null,
      max_drawdown_pct: null,
      risk_adjusted_return: null,
    },
  }
}
