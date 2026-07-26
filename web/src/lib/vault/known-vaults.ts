'use client'

import { useEffect, useState } from 'react'
import type { Mandate as MandateT } from '@curator/schema'
import { FIXTURE_VAULT_STATE } from '@/lib/api/fixtures'
import { deployedVaults } from '@/lib/chain/deployments'
import { useAllVaults } from '@/lib/chain/all-vaults'
import { getStoredMandate, listLocalVaults } from '@/lib/mandate/store'

export type VaultOrigin = 'local' | 'deployed' | 'onchain' | 'sample'

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
 * Every vault this browser can see: the three local sources `VaultList` reads,
 * plus **every vault the factory has actually created**, plus the stored
 * mandate where one exists.
 *
 * Split out of `VaultList` so the explorer can filter on mandate parameters
 * without the landing page paying for the extra localStorage reads.
 *
 * The on-chain list is what makes this an explorer rather than a history of
 * this browser. localStorage sees only what *we* deployed and the deployments
 * file only what the deploy script recorded — but genesis and one-click
 * archetypes both mint through the factory without touching that file, so
 * without `vaults()` the two flows that create most vaults are invisible here.
 *
 * Precedence is deliberate: a locally-deployed vault wins over the same address
 * found on chain, because only the local record carries the mandate we held at
 * finalize time. The chain knows a vault exists; it does not hand back the
 * mandate text.
 */
export function useKnownVaults(): { vaults: KnownVault[]; ready: boolean } {
  const [vaults, setVaults] = useState<KnownVault[]>([])
  const [ready, setReady] = useState(false)
  const onchain = useAllVaults()

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

    deployed.forEach((entry) => known.add(entry.address.toLowerCase()))

    // Everything the factory created that the two local sources missed —
    // which is every vault from genesis and every one-click archetype.
    const chain: KnownVault[] = (onchain.data?.vaults ?? [])
      .filter((address) => !known.has(address.toLowerCase()))
      .map((address) => ({
        address,
        name: 'Vault',
        origin: 'onchain' as const,
        // The chain says a vault exists; it does not carry the mandate text.
        // `GET /vault/{addr}/mandate` does (cross-lane request #6, since
        // closed), so a detail view can fetch it — but a list of forty should
        // not fire forty requests to render. Null here means "not loaded",
        // never "has none", and filters must treat it as unknown rather than
        // as a non-match.
        mandate: getStoredMandate(address) ?? null,
      }))

    // A way in before anything is deployed, labelled as what it is.
    const sample: KnownVault[] =
      local.length > 0 || deployed.length > 0 || chain.length > 0
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

    setVaults([...local, ...deployed, ...chain, ...sample])
    setReady(true)
    // Re-runs when the on-chain read resolves, so a vault deployed seconds ago
    // in the archetype flow appears without a reload.
  }, [onchain.data])

  return { vaults, ready: ready && !onchain.isLoading }
}
