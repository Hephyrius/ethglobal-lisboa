'use client'

import { useEffect, useState } from 'react'
import type { Mandate as MandateT } from '@curator/schema'
import { FIXTURE_VAULT_STATE } from '@/lib/api/fixtures'
import { deployedVaults } from '@/lib/chain/deployments'
import { getStoredMandate, listLocalVaults } from '@/lib/mandate/store'

export type VaultOrigin = 'local' | 'deployed' | 'sample'

export type KnownVault = {
  address: string
  name: string
  origin: VaultOrigin
  createdAt?: string
  mandateHash?: string
  /**
   * Only present for vaults this browser deployed. `store.ts` explains why:
   * `VaultState` carries `mandate_hash` but no route returns the mandate
   * itself (cross-lane request #6), so the parameters below can only be known
   * for vaults we happened to have in hand at finalize time. Filters that read
   * this have to treat absence as "unknown", never as "does not match".
   */
  mandate: MandateT | null
}

/**
 * Every vault this browser can see, from the same three places `VaultList`
 * reads, plus the stored mandate where one exists.
 *
 * Split out of `VaultList` so the explorer can filter on mandate parameters
 * without the landing page paying for the extra localStorage reads.
 */
export function useKnownVaults(): { vaults: KnownVault[]; ready: boolean } {
  const [vaults, setVaults] = useState<KnownVault[]>([])
  const [ready, setReady] = useState(false)

  // localStorage is client-only, so this runs after mount. Reading it during
  // SSR would produce a hydration mismatch.
  useEffect(() => {
    const local: KnownVault[] = listLocalVaults().map((vault) => ({
      address: vault.address,
      name: vault.name,
      origin: 'local',
      createdAt: vault.createdAt,
      mandateHash: vault.mandateHash,
      mandate: getStoredMandate(vault.address),
    }))

    const known = new Set(local.map((entry) => entry.address.toLowerCase()))

    const deployed: KnownVault[] = deployedVaults()
      .filter((vault) => !known.has(vault.address.toLowerCase()))
      .map((vault) => ({
        address: vault.address,
        name: vault.name ?? 'Deployed vault',
        origin: 'deployed',
        mandate: getStoredMandate(vault.address),
      }))

    // A way in before anything is deployed, labelled as what it is.
    const sample: KnownVault[] =
      local.length > 0 || deployed.length > 0
        ? []
        : [
            {
              address: FIXTURE_VAULT_STATE.address,
              name: 'Conservative Base Yield',
              origin: 'sample',
              mandateHash: FIXTURE_VAULT_STATE.mandate_hash,
              mandate: null,
            },
          ]

    setVaults([...local, ...deployed, ...sample])
    setReady(true)
  }, [])

  return { vaults, ready }
}
