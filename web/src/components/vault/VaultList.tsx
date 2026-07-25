'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'
import { Badge } from '@/components/ui/Badge'
import { Card } from '@/components/ui/Card'
import { FIXTURE_VAULT_STATE } from '@/lib/api/fixtures'
import { deployedVaults } from '@/lib/chain/deployments'
import { listLocalVaults } from '@/lib/mandate/store'
import { shortAddress, shortHash } from '@/lib/format/units'
import { relativeTime } from '@/lib/format/time'

type Entry = {
  address: string
  name: string
  origin: 'local' | 'deployed' | 'sample'
  createdAt?: string
  mandateHash?: string
}

/**
 * Vaults this browser knows about, from three places:
 *   - created here (localStorage — see lib/mandate/store.ts)
 *   - deployed by Lane A (deployments/base-fork.json)
 *   - the golden fixture, so the app is explorable before anything is deployed
 *
 * The sample entry is labelled as a sample. It is a way in, not a claim that a
 * vault exists.
 */
export function VaultList() {
  const [entries, setEntries] = useState<Entry[]>([])

  // localStorage is client-only, so the list is read after mount. Rendering it
  // during SSR would produce a hydration mismatch.
  useEffect(() => {
    const local: Entry[] = listLocalVaults().map((vault) => ({
      address: vault.address,
      name: vault.name,
      origin: 'local',
      createdAt: vault.createdAt,
      mandateHash: vault.mandateHash,
    }))

    const known = new Set(local.map((entry) => entry.address.toLowerCase()))

    const deployed: Entry[] = deployedVaults()
      .filter((vault) => !known.has(vault.address.toLowerCase()))
      .map((vault) => ({
        address: vault.address,
        name: vault.name ?? 'Deployed vault',
        origin: 'deployed',
      }))

    const sample: Entry[] =
      local.length > 0 || deployed.length > 0
        ? []
        : [
            {
              address: FIXTURE_VAULT_STATE.address,
              name: 'Conservative Base Yield',
              origin: 'sample',
              mandateHash: FIXTURE_VAULT_STATE.mandate_hash,
            },
          ]

    setEntries([...local, ...deployed, ...sample])
  }, [])

  if (entries.length === 0) {
    return (
      <Card className="border-dashed px-5 py-8 text-center">
        <p className="text-sm text-muted">No vaults yet.</p>
        <Link
          href="/create"
          className="mt-2 inline-block text-sm text-agent underline-offset-4 hover:underline"
        >
          Create one →
        </Link>
      </Card>
    )
  }

  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {entries.map((entry) => (
        <Link
          key={entry.address}
          href={`/vault/${entry.address}`}
          className="group rounded-xl border border-line bg-surface p-4 transition-colors hover:border-line-bright hover:bg-raised"
        >
          <div className="flex items-start justify-between gap-3">
            <h3 className="truncate text-sm font-semibold text-ink">{entry.name}</h3>
            {entry.origin === 'sample' ? (
              <Badge tone="warn">SAMPLE</Badge>
            ) : entry.origin === 'local' ? (
              <Badge tone="agent">YOURS</Badge>
            ) : (
              <Badge tone="data">DEPLOYED</Badge>
            )}
          </div>

          <p className="mt-3 font-mono text-xs text-muted">{shortAddress(entry.address, 6)}</p>

          <div className="mt-3 flex items-center gap-3 text-2xs text-faint">
            {entry.mandateHash ? <span>mandate {shortHash(entry.mandateHash)}</span> : null}
            {entry.createdAt ? <span>{relativeTime(entry.createdAt)}</span> : null}
          </div>
        </Link>
      ))}
    </div>
  )
}
