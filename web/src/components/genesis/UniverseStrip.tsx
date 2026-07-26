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

/**
 * Two or three words each, because they sit on the same line as the key rather
 * than under it. A note long enough to wrap pushes its row taller than its
 * neighbours and the grid stops reading as a list.
 *
 * These name the *kind* of fact a source supplies, which is all the choice
 * needs: a reader picking sources is asking "what would this let it see", not
 * "how is it implemented". The implementation detail each of these used to
 * carry — Aave's own subgraph schema, Chainlink being the same oracle the vault
 * values with — belongs in the docs, not in a picker.
 */
const SOURCE_NOTES: Record<string, string> = {
  messari: 'Cross-protocol metrics',
  aave: 'Aave V3 rates',
  chainlink: 'Oracle prices',
  token_api: 'DEX swap prices',
  defillama: 'TVL and yields',
  peers: 'Comparable vaults',
  feargreed: 'Sentiment index',
  gas: 'Base gas price',
  morpho: 'Morpho rates',
  prediction: 'Market-implied odds',
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
        The agent may consult only the sources granted to it. This list is exhaustive: anything
        absent from the mandate is unavailable to it.
      </p>

      {/* Key and note on one line. This was tried once before and reverted,
          because the notes were a sentence long and wrapped under the badge
          until the rows lost their left edge and the list read as prose. It
          works now because the notes are two words, not because the layout
          changed — shorten one of these back to a sentence and it breaks again.

          Five across from `xl` (1280) rather than from `2xl`. The page container
          is capped at 1400px, so the grid is within a few pixels of the same
          width at 1440 as at 1920 — gating five columns on the viewport instead
          of the content width meant the widest laptops still saw three. At 1280
          each cell is about 234px, which a badge and three words clear. */}
      <ul className="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
        {available.sources.map((key) => (
          <li
            key={key}
            className="flex min-w-0 items-center gap-2 rounded border border-line bg-surface px-2.5 py-2"
          >
            <Badge tone="data">{key}</Badge>
            {SOURCE_NOTES[key] ? (
              <span className="truncate text-2xs text-muted" title={SOURCE_NOTES[key]}>
                {SOURCE_NOTES[key]}
              </span>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  )
}
