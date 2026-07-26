'use client'

import { useQuery } from '@tanstack/react-query'
import { z } from 'zod'
import { API_BASE } from '@/lib/api/routes'

/**
 * What the vault earns **now**, as opposed to what it has earned.
 *
 * Deliberately separate from `usePerformance`. That one reports the *realised*
 * return, and `annualized_return_pct` there is null until the series spans a
 * day — which is correct (annualising forty minutes of a two-point series is a
 * meaningless number, not a small one) and means that on a fresh deployment,
 * and for the whole of a demo, every yield figure on the page is blank while
 * the vault is visibly earning.
 *
 * This is the forward-looking rate on what is held right now, from the same
 * live yield facts the agent reads to decide. It is populated from the first
 * tick, so the page has a real number to show immediately.
 *
 * ## Two conventions the UI must not collapse
 *
 * * **Idle capital is `0`, not null** — it genuinely earns nothing, and that is
 *   the most decision-relevant number on the page.
 * * **A position with no rate found is `null`, never `0`** — "earns nothing"
 *   and "we do not know what this earns" are different claims. Render the
 *   second as a dash, never as 0%.
 */

const PositionYield = z
  .object({
    token: z.string(),
    symbol: z.string(),
    represents: z.string(),
    venue: z.string().nullable().optional(),
    value_in_asset: z.string(),
    apy: z.number().nullable().optional(),
    source: z.string().nullable().optional(),
    fact_id: z.string().nullable().optional(),
  })
  .passthrough()

const VaultYield = z
  .object({
    vault: z.string(),
    positions: z.array(PositionYield).default([]),
    weighted_apy: z.number().nullable().optional(),
    coverage: z.number().default(0),
  })
  .passthrough()

export type VaultYieldData = z.infer<typeof VaultYield>
export type PositionYieldData = z.infer<typeof PositionYield>

export function useVaultYield(address: string) {
  return useQuery({
    queryKey: ['vault-yield', address],
    queryFn: async (): Promise<VaultYieldData> => {
      const response = await fetch(`${API_BASE}/vault/${address}/yield`, {
        // A yield read fans out to the same live sources a tick uses, so it is
        // seconds rather than milliseconds. The default read timeout would
        // abort a healthy request and render as "no yield data".
        signal: AbortSignal.timeout(30_000),
      })
      if (!response.ok) throw new Error(`yield unavailable (${response.status})`)
      return VaultYield.parse(await response.json())
    },
    // Rates move on the underlying protocols' own schedule, not ours.
    refetchInterval: 60_000,
    staleTime: 30_000,
    // One retry: a rate is worth showing but never worth a spinner the reader
    // watches, and the holdings are already on screen without it.
    retry: 1,
  })
}
