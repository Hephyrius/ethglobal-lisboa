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
  aave: 'Aave V3 Base, on its own subgraph schema rather than the standardised one',
  chainlink: 'On-chain price feeds, the same oracle the vault values its holdings with',
  token_api: 'Prices derived from executed DEX swaps',
  defillama: 'Cross-protocol TVL and yield',
  peers: 'What comparable vaults are doing',
  feargreed: 'Market sentiment index',
  gas: 'Base gas price, what an action costs to take',
  morpho: "Base's largest lending market by TVL",
  prediction:
    'Implied odds from prediction markets, a forward-looking view unlike every rate beside it',
}

/**
 * Sources only. Venues moved to `VenueStrip`, which renders Lane D's capability
 * manifest — what each one does to the tokens, not just its name. Listing them
 * in both places put two different answers to the same question on one screen.
 */
export function UniverseStrip({ available }: { available: AvailableGrants }) {
  if (available.sources.length === 0) return null

  return (
    <section>
      {/* Headed like `AssetUniverse` and `VenueStrip` rather than as a tinted
          box, so the three selection parameters read as one sequence. */}
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 border-b border-line pb-2">
        <h2 className="text-sm font-semibold text-ink">Data sources</h2>
        <span className="text-2xs text-faint">{available.sources.length} registered</span>
      </div>

      <p className="mt-3 text-2xs leading-relaxed text-faint">
        The agent can only reason about markets it is granted. This list is exhaustive: anything
        absent from a mandate, it cannot see.
      </p>

      {/* One source per row on its own line, the badge above its description
          rather than beside it. Inline, the longer notes wrapped under the
          badge and the rows lost their left edge, so the list read as prose. */}
      <ul className="mt-4 grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
        {available.sources.map((key) => (
          <li key={key} className="rounded border border-line bg-surface p-3">
            <Badge tone="data">{key}</Badge>
            {SOURCE_NOTES[key] ? (
              <p className="mt-2 text-2xs leading-relaxed text-muted">{SOURCE_NOTES[key]}</p>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  )
}
