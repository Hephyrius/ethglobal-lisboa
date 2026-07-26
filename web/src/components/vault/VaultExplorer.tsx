'use client'

import Link from 'next/link'
import { useMemo, useState } from 'react'
import { Badge } from '@/components/ui/Badge'
import { Card } from '@/components/ui/Card'
import { TokenMark } from '@/components/ui/TokenMark'
import { useKnownVaults, type KnownVault } from '@/lib/vault/known-vaults'
import { shortAddress, shortHash } from '@/lib/format/units'
import { relativeTime } from '@/lib/format/time'
import { cn } from '@/lib/cn'

/**
 * Browse and narrow the full set of vaults.
 *
 * ## Built for a list that does not exist yet
 *
 * There are a handful of vaults today and there could be hundreds. Three
 * choices here are for the hundreds rather than the handful:
 *
 * 1. **Facet values are derived from the data, never listed here.** A hard-coded
 *    set of postures or assets silently omits anything added later, and the
 *    omission looks identical to the feature not existing. That failure has
 *    already cost this project a wave, so the filter bar counts what is actually
 *    present and offers exactly that.
 * 2. **Filtering is client-side and memoised.** At hundreds of rows this is well
 *    inside what a single pass costs. It is the wrong answer at tens of
 *    thousands, at which point the search belongs behind an API and this
 *    component keeps its shape while `useKnownVaults` changes underneath.
 * 3. **Results are revealed in pages.** The DOM cost of a few hundred cards is
 *    real even when the filter is cheap, so the grid grows on demand instead of
 *    rendering everything nobody scrolled to.
 *
 * ## Unknown is not the same as no
 *
 * Only vaults this browser deployed carry a mandate, so most have no posture or
 * asset to filter on. Those are excluded by a posture filter but never silently:
 * the count line says how many were set aside for want of a mandate, because a
 * reader who filters and sees three of two hundred needs to know whether that is
 * a real answer or a data gap.
 */

type Sort = 'recent' | 'name'

const PAGE_SIZE = 24

const ORIGIN_LABEL: Record<string, string> = {
  local: 'Yours',
  deployed: 'Deployed',
  // Read from `VaultFactory.vaults()` rather than from anything this browser
  // recorded — which is how every genesis and one-click archetype vault gets
  // here. Labelled by what a reader can act on ("someone else made this"),
  // not by which source we happened to learn it from: `deployed` and `onchain`
  // differ only in our provenance, and both are equally real on chain.
  onchain: 'Others',
  sample: 'Sample',
}

export function VaultExplorer() {
  const { vaults, ready } = useKnownVaults()

  const [query, setQuery] = useState('')
  const [postures, setPostures] = useState<Set<string>>(new Set())
  const [assets, setAssets] = useState<Set<string>>(new Set())
  const [venues, setVenues] = useState<Set<string>>(new Set())
  const [origins, setOrigins] = useState<Set<string>>(new Set())
  const [sort, setSort] = useState<Sort>('recent')
  const [shown, setShown] = useState(PAGE_SIZE)

  // Every facet is counted off the real set, so a value only appears once a
  // vault actually has it.
  const facets = useMemo(() => {
    const count = (pick: (v: KnownVault) => string[]) => {
      const tally = new Map<string, number>()
      for (const vault of vaults) {
        for (const value of pick(vault)) tally.set(value, (tally.get(value) ?? 0) + 1)
      }
      return [...tally.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    }
    return {
      postures: count((v) => (v.mandate?.risk_posture ? [v.mandate.risk_posture] : [])),
      assets: count((v) =>
        v.mandate ? [...new Set([v.mandate.base_asset, ...(v.mandate.constraints.allowed_assets ?? [])])] : [],
      ),
      venues: count((v) => v.mandate?.permitted_venues ?? []),
      origins: count((v) => [v.origin]),
    }
  }, [vaults])

  const { results, withoutMandate } = useMemo(() => {
    const needle = query.trim().toLowerCase()
    const parameterFiltered = postures.size > 0 || assets.size > 0 || venues.size > 0

    let skipped = 0
    const matched = vaults.filter((vault) => {
      if (needle) {
        const haystack = [
          vault.name,
          vault.address,
          vault.mandateHash ?? '',
          vault.mandate?.objective ?? '',
        ]
          .join(' ')
          .toLowerCase()
        if (!haystack.includes(needle)) return false
      }

      if (origins.size > 0 && !origins.has(vault.origin)) return false

      if (parameterFiltered && !vault.mandate) {
        skipped += 1
        return false
      }

      if (postures.size > 0 && !postures.has(vault.mandate?.risk_posture ?? '')) return false

      if (assets.size > 0) {
        const held = new Set([
          vault.mandate?.base_asset ?? '',
          ...(vault.mandate?.constraints.allowed_assets ?? []),
        ])
        if (![...assets].some((asset) => held.has(asset))) return false
      }

      if (venues.size > 0) {
        // Widened to `string`: `permitted_venues` is a closed enum in the
        // schema, but the facet values arrive as plain strings from the UI.
        const permitted = new Set<string>(vault.mandate?.permitted_venues ?? [])
        if (![...venues].some((venue) => permitted.has(venue))) return false
      }

      return true
    })

    matched.sort((a, b) => {
      if (sort === 'name') return a.name.localeCompare(b.name)
      return (b.createdAt ?? '').localeCompare(a.createdAt ?? '')
    })

    return { results: matched, withoutMandate: skipped }
  }, [vaults, query, postures, assets, venues, origins, sort])

  const active = postures.size + assets.size + venues.size + origins.size + (query ? 1 : 0)

  function toggle(set: Set<string>, update: (next: Set<string>) => void, value: string) {
    const next = new Set(set)
    if (next.has(value)) next.delete(value)
    else next.add(value)
    update(next)
    setShown(PAGE_SIZE)
  }

  function clearAll() {
    setQuery('')
    setPostures(new Set())
    setAssets(new Set())
    setVenues(new Set())
    setOrigins(new Set())
    setShown(PAGE_SIZE)
  }

  if (ready && vaults.length === 0) {
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
    <div>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <label className="relative min-w-0 flex-1">
          <span className="sr-only">Search vaults</span>
          <input
            type="search"
            value={query}
            onChange={(event) => {
              setQuery(event.target.value)
              setShown(PAGE_SIZE)
            }}
            placeholder="Search by name, address, mandate hash or objective"
            className="h-9 w-full rounded border border-line bg-surface px-3 text-sm text-ink placeholder:text-faint focus:border-agent/50 focus:outline-none focus:ring-1 focus:ring-agent/25"
          />
        </label>

        <label className="flex shrink-0 items-center gap-2 text-xs text-muted">
          Sort
          <select
            value={sort}
            onChange={(event) => setSort(event.target.value as Sort)}
            className="h-9 rounded border border-line bg-surface px-2 text-xs text-ink focus:border-agent/50 focus:outline-none"
          >
            <option value="recent">Newest first</option>
            <option value="name">Name</option>
          </select>
        </label>
      </div>

      <div className="mt-3 space-y-2">
        <Facet label="Posture" values={facets.postures} selected={postures} onToggle={(v) => toggle(postures, setPostures, v)} />
        <Facet label="Asset" values={facets.assets} selected={assets} onToggle={(v) => toggle(assets, setAssets, v)} tokens />
        <Facet label="Venue" values={facets.venues} selected={venues} onToggle={(v) => toggle(venues, setVenues, v)} />
        <Facet
          label="Origin"
          values={facets.origins}
          selected={origins}
          onToggle={(v) => toggle(origins, setOrigins, v)}
          rename={ORIGIN_LABEL}
        />
      </div>

      <div className="mt-4 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-line pb-2">
        <p className="text-xs text-muted">
          {results.length === vaults.length
            ? `${vaults.length} ${vaults.length === 1 ? 'vault' : 'vaults'}`
            : `${results.length} of ${vaults.length} vaults`}
          {withoutMandate > 0 ? (
            <span className="text-faint">
              {' '}
              · {withoutMandate} set aside, no mandate stored in this browser to filter on
            </span>
          ) : null}
        </p>
        {active > 0 ? (
          <button
            type="button"
            onClick={clearAll}
            className="text-xs text-agent underline-offset-4 hover:underline"
          >
            Clear filters
          </button>
        ) : null}
      </div>

      {results.length === 0 ? (
        <Card className="mt-4 border-dashed px-5 py-8 text-center">
          <p className="text-sm text-muted">No vault matches those filters.</p>
          <button
            type="button"
            onClick={clearAll}
            className="mt-2 text-sm text-agent underline-offset-4 hover:underline"
          >
            Clear filters
          </button>
        </Card>
      ) : (
        <>
          <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {results.slice(0, shown).map((vault) => (
              <VaultCard key={vault.address} vault={vault} />
            ))}
          </div>

          {results.length > shown ? (
            <div className="mt-5 flex justify-center">
              <button
                type="button"
                onClick={() => setShown((current) => current + PAGE_SIZE)}
                className="h-9 rounded border border-line bg-surface px-4 text-sm text-muted transition-colors hover:border-line-bright hover:text-ink"
              >
                Show {Math.min(PAGE_SIZE, results.length - shown)} more
              </button>
            </div>
          ) : null}
        </>
      )}
    </div>
  )
}

function Facet({
  label,
  values,
  selected,
  onToggle,
  rename,
  tokens = false,
}: {
  label: string
  values: Array<[string, number]>
  selected: Set<string>
  onToggle: (value: string) => void
  rename?: Record<string, string>
  tokens?: boolean
}) {
  if (values.length === 0) return null

  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5">
      <span className="w-14 shrink-0 text-2xs font-semibold uppercase tracking-[0.09em] text-faint">
        {label}
      </span>
      {values.map(([value, count]) => {
        const isOn = selected.has(value)
        return (
          <button
            key={value}
            type="button"
            aria-pressed={isOn}
            onClick={() => onToggle(value)}
            className={cn(
              'flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-2xs transition-colors',
              isOn
                ? 'border-agent/50 bg-agent/[0.08] text-ink'
                : 'border-line bg-surface text-muted hover:border-line-bright hover:text-ink',
            )}
          >
            {tokens ? <TokenMark symbol={value} /> : null}
            {rename?.[value] ?? value}
            <span className="text-faint">{count}</span>
          </button>
        )
      })}
    </div>
  )
}

function VaultCard({ vault }: { vault: KnownVault }) {
  const assets = vault.mandate
    ? [...new Set([vault.mandate.base_asset, ...(vault.mandate.constraints.allowed_assets ?? [])])]
    : []

  return (
    <Link
      href={`/vault/${vault.address}`}
      className="group rounded-xl border border-line bg-surface p-4 transition-colors hover:border-line-bright hover:bg-raised"
    >
      <div className="flex items-start justify-between gap-3">
        <h3 className="truncate text-sm font-semibold text-ink">{vault.name}</h3>
        {vault.origin === 'sample' ? (
          <Badge tone="warn">SAMPLE</Badge>
        ) : vault.origin === 'local' ? (
          <Badge tone="agent">YOURS</Badge>
        ) : (
          <Badge tone="data">DEPLOYED</Badge>
        )}
      </div>

      {vault.mandate ? (
        <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
          <Badge tone="neutral">{vault.mandate.risk_posture}</Badge>
          {assets.map((asset) => (
            <span key={asset} className="flex items-center gap-1 text-2xs text-muted">
              <TokenMark symbol={asset} />
              {asset}
            </span>
          ))}
        </div>
      ) : null}

      <p className="mt-3 font-mono text-xs text-muted">{shortAddress(vault.address, 6)}</p>

      <div className="mt-3 flex items-center gap-3 text-2xs text-faint">
        {vault.mandateHash ? <span>mandate {shortHash(vault.mandateHash)}</span> : null}
        {vault.createdAt ? <span>{relativeTime(vault.createdAt)}</span> : null}
      </div>
    </Link>
  )
}
