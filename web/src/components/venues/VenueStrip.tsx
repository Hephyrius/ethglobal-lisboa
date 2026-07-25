'use client'

import { Badge, type BadgeTone } from '@/components/ui/Badge'
import { useVenueManifest, type VenueRow } from '@/lib/api/venue-queries'
import { cn } from '@/lib/cn'

/**
 * Where the agent can execute, and — the part that matters — **what happens to
 * the tokens when it does**.
 *
 * Lane D's manifest carries a `custody` field and asked for it to be rendered
 * specifically, because flattening its three values is how a reader concludes
 * the accounting is broken:
 *
 * - `virtual` — the tokens never leave the vault. This *is* the Pattern 1 claim,
 *   and it is why an open Aqua position does not move `totalAssets()`.
 * - `claim` — the underlying really moved and the vault holds a receipt token.
 * - `rotational` — no position is held at all; the venue only swaps one asset
 *   for another.
 *
 * **Unavailable venues are shown, not filtered.** D was explicit and the
 * reasoning is the same one that keeps recurring in this project: silence is
 * how a fully-built Aave venue stayed invisible for an entire wave. A venue
 * that is present but unusable, with the reason attached, is strictly more
 * informative than a shorter list.
 */

const CUSTODY: Record<string, { tone: BadgeTone; label: string; note: string }> = {
  virtual: {
    tone: 'agent',
    label: 'virtual',
    note: 'Tokens never leave the vault — only a virtual balance is tracked.',
  },
  claim: {
    tone: 'data',
    label: 'claim',
    note: 'The underlying moves; the vault holds a receipt token for it.',
  },
  rotational: {
    tone: 'neutral',
    label: 'rotational',
    note: 'No position is held — it swaps one asset for another.',
  },
}

export function VenueStrip({ className }: { className?: string }) {
  const { rows, enriched } = useVenueManifest()
  if (rows.length === 0) return null

  return (
    <section className={cn(className)}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 border-b border-line pb-2">
        <h2 className="text-sm font-semibold text-ink">Execution venues</h2>
        <span className="text-2xs text-faint">
          {rows.length} registered
          {enriched ? null : ' · capability detail unavailable'}
        </span>
      </div>

      {!enriched ? (
        <p className="mt-2 text-2xs leading-relaxed text-faint">
          These are the venues the registry reports. What each one does to the tokens — whether a
          position is held in the vault, as a receipt, or not at all — comes from the venue
          capability manifest, which is not yet served over HTTP (note #68). Deliberately not
          guessed here: a description written in the UI cannot know what the registry actually
          holds.
        </p>
      ) : null}

      <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {rows.map((row) => (
          <Venue key={row.key} row={row} />
        ))}
      </div>
    </section>
  )
}

function Venue({ row }: { row: VenueRow }) {
  const custody = row.custody ? CUSTODY[row.custody] : undefined

  return (
    <div
      className={cn(
        'rounded border bg-surface p-3',
        row.available ? 'border-line' : 'border-warn/30 bg-warn/[0.04]',
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium text-ink">{row.key}</span>
        {row.role ? <Badge tone="neutral">{row.role}</Badge> : null}
        {custody ? (
          <Badge tone={custody.tone} title={custody.note}>
            {custody.label}
          </Badge>
        ) : null}
        {!row.available ? <Badge tone="warn">unavailable</Badge> : null}
      </div>

      {row.summary ? (
        <p className="mt-2 text-2xs leading-relaxed text-muted">{row.summary}</p>
      ) : null}

      {custody ? (
        <p className="mt-1.5 text-2xs leading-relaxed text-faint">
          {row.custody_note ?? custody.note}
        </p>
      ) : null}

      {row.intents.length > 0 ? (
        <div className="mt-2 flex flex-wrap gap-1">
          {row.intents.map((intent) => (
            <span
              key={intent}
              className="rounded border border-line bg-raised px-1.5 py-0.5 font-mono text-2xs text-muted"
            >
              {intent}
            </span>
          ))}
        </div>
      ) : null}

      {!row.available && row.unavailable_reason ? (
        <p className="mt-2 border-t border-warn/20 pt-2 text-2xs leading-relaxed text-warn/90">
          {row.unavailable_reason}
        </p>
      ) : null}
    </div>
  )
}
