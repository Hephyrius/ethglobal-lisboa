'use client'

import { useDataMode } from '@/lib/api/mode-context'
import { API_BASE } from '@/lib/api/routes'
import { Badge, Dot } from './Badge'

/**
 * The honesty rail.
 *
 * The Graph disqualifies mocked data on the demo path, and the realistic way
 * that goes wrong is not deliberate — it is not noticing that the agent API
 * fell over and that the numbers on screen came from a fixture. This badge is
 * permanent, sits in the header on every page, and reads FIXTURES the moment
 * any query on the page falls back.
 *
 * If it is amber during the demo, stop and fix it.
 */
export function ModeBadge() {
  const { mode, notes } = useDataMode()

  if (mode === 'live') {
    return (
      <Badge tone="ok" title={`Live data from the agent API at ${API_BASE}`}>
        <Dot tone="ok" pulse />
        LIVE
      </Badge>
    )
  }

  return (
    <Badge
      tone="warn"
      title={
        notes.length > 0
          ? `Showing golden fixtures — ${notes.join(' · ')}`
          : 'Showing golden fixtures from packages/schema/fixtures'
      }
    >
      <Dot tone="warn" />
      FIXTURES
    </Badge>
  )
}

/** Expanded explanation, for pages that have room to say why. */
export function ModeNotice() {
  const { mode, notes } = useDataMode()
  if (mode === 'live') return null

  return (
    <div className="rounded-lg border border-warn/25 bg-warn/[0.06] px-4 py-3 text-xs leading-relaxed text-warn/90">
      <span className="font-semibold">Showing golden fixtures.</span>{' '}
      {notes[0] ?? `The agent API at ${API_BASE} is unreachable.`} Every number on this page comes
      from <span className="font-mono">packages/schema/fixtures</span>, not from a live source.
    </div>
  )
}
