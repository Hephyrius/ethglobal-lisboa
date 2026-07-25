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
 * permanent, sits in the header on every page, and reports the *worst* source
 * feeding the page.
 *
 * If it reads FIXTURES during the demo, stop and fix it.
 */
export function ModeBadge() {
  const { mode, notes } = useDataMode()

  // Nothing fetched yet (the landing page issues no API queries). Saying LIVE
  // here would be a claim about data that was never loaded.
  if (mode === 'unknown') return null

  // The label collapses to its dot below `sm`. The header is the tightest row
  // in the app at 375px, and a badge that will not shrink pushes the whole
  // page wider than the viewport — which centres every other section off to
  // one side, because `main` is `mx-auto` inside the wider scroll area. The
  // colour still carries the state, and the title still carries the detail.
  if (mode === 'live') {
    return (
      <Badge tone="ok" title={`Live data from the agent API at ${API_BASE}`}>
        <Dot tone="ok" pulse />
        <span className="hidden sm:inline">LIVE</span>
      </Badge>
    )
  }

  if (mode === 'chain') {
    return (
      <Badge
        tone="data"
        title={`Read directly from the vault contract — the agent API at ${API_BASE} is unreachable. These numbers are real.`}
      >
        <Dot tone="data" pulse />
        <span className="hidden sm:inline">ON-CHAIN</span>
      </Badge>
    )
  }

  return (
    <Badge
      tone="warn"
      title={
        notes.length > 0
          ? `Some data is from golden fixtures — ${notes.join(' · ')}`
          : 'Some data on this page comes from packages/schema/fixtures'
      }
    >
      <Dot tone="warn" />
      <span className="hidden sm:inline">FIXTURES</span>
    </Badge>
  )
}

/** Notes are written as clause fragments so they read inside a tooltip list. */
function sentence(note: string): string {
  return note.charAt(0).toUpperCase() + note.slice(1)
}

/** Expanded explanation, for pages that have room to say why. */
export function ModeNotice() {
  const { mode, notes } = useDataMode()
  if (mode !== 'fixture' && mode !== 'chain') return null

  if (mode === 'chain') {
    return (
      <div className="rounded border border-data/25 bg-data/[0.05] px-4 py-3 text-xs leading-relaxed text-data">
        <span className="font-semibold">Read directly from the vault contract.</span> The agent API
        at <span className="font-mono">{API_BASE}</span> is unreachable, so these figures come from
        the ERC-4626 contract itself rather than from the agent. They are real.
      </div>
    )
  }

  return (
    <div className="rounded border border-warn/25 bg-warn/[0.06] px-4 py-3 text-xs leading-relaxed text-warn">
      <span className="font-semibold">Some data on this page is a golden fixture.</span>{' '}
      {notes[0] ? `${sentence(notes[0])}.` : `The agent API at ${API_BASE} is unreachable.`} Anything not read
      from the chain comes from <span className="font-mono">packages/schema/fixtures</span>, not
      from a live source.
    </div>
  )
}
