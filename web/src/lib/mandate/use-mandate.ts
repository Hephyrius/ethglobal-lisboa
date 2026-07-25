'use client'

import { useEffect, useState } from 'react'
import type { Mandate } from '@curator/schema'
import { FIXTURE_MANDATE } from '@/lib/api/fixtures'
import { getStoredMandate } from './store'

export type MandateProvenance = 'local' | 'fixture'

export type ResolvedMandate = {
  mandate: Mandate
  provenance: MandateProvenance
}

/**
 * Resolve the mandate to show for a vault.
 *
 * No frozen route returns a `Mandate` for an existing vault — `VaultState`
 * carries only `mandate_hash` (cross-lane request #6). So we read what this
 * browser saved at `POST /genesis/finalize`, and fall back to the golden
 * fixture, labelled as a fixture, so the mandate viewer is never simply blank.
 *
 * Reading happens after mount because `localStorage` does not exist during the
 * server render; returning the stored value on first paint would be a hydration
 * mismatch.
 */
export function useVaultMandate(address: string): ResolvedMandate {
  const [resolved, setResolved] = useState<ResolvedMandate>({
    mandate: FIXTURE_MANDATE,
    provenance: 'fixture',
  })

  useEffect(() => {
    const stored = getStoredMandate(address)
    setResolved(
      stored
        ? { mandate: stored, provenance: 'local' }
        : { mandate: FIXTURE_MANDATE, provenance: 'fixture' },
    )
  }, [address])

  return resolved
}
