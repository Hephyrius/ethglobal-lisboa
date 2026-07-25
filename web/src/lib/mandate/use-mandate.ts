'use client'

import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import type { Mandate } from '@curator/schema'
import { apiFetchStrict, FIXTURES_FORCED } from '@/lib/api/client'
import { routes, schemas } from '@/lib/api/routes'
import { FIXTURE_MANDATE } from '@/lib/api/fixtures'
import { getStoredMandate } from './store'

export type MandateProvenance = 'api' | 'local' | 'fixture'

export type ResolvedMandate = {
  mandate: Mandate
  provenance: MandateProvenance
}

/**
 * Resolve the mandate to show for a vault: **agent API → this browser's cache →
 * fixture.**
 *
 * `GET /vault/{addr}/mandate` now exists (cross-lane request #6, closed by Lane
 * B), so the authoritative copy comes from the harness that actually holds it.
 * The local cache written at `POST /genesis/finalize` is kept as the second
 * rung rather than deleted: it still covers a vault created in this browser
 * while the API happens to be down, which is exactly the demo-time failure the
 * whole app is built to survive. The fixture remains the last resort, and is
 * labelled as one in the UI.
 *
 * A 404 here is a normal answer, not a fault — it means no mandate is stored
 * for that vault, which is true of any vault another harness deployed.
 */
export function useVaultMandate(address: string): ResolvedMandate {
  const query = useQuery({
    queryKey: ['vault-mandate', address],
    enabled: Boolean(address) && !FIXTURES_FORCED,
    retry: false,
    staleTime: 60_000,
    queryFn: () =>
      apiFetchStrict({
        path: routes.vaultMandate(address),
        schema: schemas.vaultMandate.response,
      }),
  })

  // localStorage does not exist during the server render, so the cached copy is
  // read after mount; returning it on first paint would be a hydration mismatch.
  const [cached, setCached] = useState<Mandate | null>(null)
  useEffect(() => {
    setCached(getStoredMandate(address))
  }, [address])

  if (query.data) return { mandate: query.data, provenance: 'api' }
  if (cached) return { mandate: cached, provenance: 'local' }
  return { mandate: FIXTURE_MANDATE, provenance: 'fixture' }
}
