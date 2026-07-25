'use client'

import { Badge } from '@/components/ui/Badge'
import type { AvailableGrants } from '@/lib/api/genesis-queries'

/**
 * What the agent could be granted, shown *before* the first question.
 *
 * Genesis previously asked "which data sources may I consult?" without ever
 * saying what the options were. This renders the menu first, so the choice is
 * informed rather than a guess at vocabulary.
 *
 * **Every key the registry reports is rendered, including ones this file has
 * never heard of.** The descriptions below are an enrichment keyed off whatever
 * comes back — never a filter, and never the list itself. That distinction is
 * the whole bug behind Aave being invisible for an entire wave: a hardcoded
 * list silently omits anything added since it was written, and the omission
 * looks exactly like the feature not existing.
 */

const SOURCE_NOTES: Record<string, string> = {
  messari: 'Standardised lending and DEX metrics across protocols, via The Graph',
  aave: 'Aave V3 Base — its own subgraph schema, not the standardised one',
  chainlink: 'On-chain price feeds — the same oracle the vault values holdings with',
  token_api: 'Prices derived from executed DEX swaps',
  defillama: 'Cross-protocol TVL and yield',
  peers: 'What comparable vaults are doing',
  feargreed: 'Market sentiment index',
  gas: 'Base gas price — what an action costs to take',
}

const VENUE_NOTES: Record<string, string> = {
  uniswap: 'Swap execution — rotates what the vault holds',
  aqua: 'Market-making as a maker. Tokens never leave the vault',
  aave: 'Lending supply — puts idle capital to work',
  morpho: 'Lending supply',
}

export function UniverseStrip({ available }: { available: AvailableGrants }) {
  if (available.sources.length === 0 && available.venues.length === 0) return null

  return (
    <section className="rounded border border-line bg-raised/40 p-4">
      <div className="grid gap-5 md:grid-cols-2">
        <Group
          title="Data it could consult"
          caption="The agent can only reason about markets it is granted. This list is exhaustive."
          keys={available.sources}
          notes={SOURCE_NOTES}
          tone="data"
        />
        <Group
          title="Venues it could use"
          caption="Where it may execute. A venue not granted here is one it can never reach."
          keys={available.venues}
          notes={VENUE_NOTES}
          tone="agent"
        />
      </div>
    </section>
  )
}

function Group({
  title,
  caption,
  keys,
  notes,
  tone,
}: {
  title: string
  caption: string
  keys: string[]
  notes: Record<string, string>
  tone: 'data' | 'agent'
}) {
  return (
    <div>
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="label">{title}</h3>
        <span className="text-2xs text-faint">{keys.length} registered</span>
      </div>
      <p className="mt-1 text-2xs leading-relaxed text-faint">{caption}</p>

      <ul className="mt-2.5 space-y-1.5">
        {keys.map((key) => (
          <li key={key} className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
            <Badge tone={tone}>{key}</Badge>
            {notes[key] ? (
              <span className="text-2xs leading-relaxed text-muted">{notes[key]}</span>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  )
}
