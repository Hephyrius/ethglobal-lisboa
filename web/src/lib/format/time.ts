/**
 * Timestamps cross the boundary as ISO 8601 strings. The decision feed shows
 * both a relative time (how fresh is this?) and an absolute one (what exactly
 * did the agent see?) — freshness is the interesting property for market data,
 * but a judge auditing the causal chain needs the exact instant.
 */

const UNITS: Array<[Intl.RelativeTimeFormatUnit, number]> = [
  ['second', 60],
  ['minute', 60],
  ['hour', 24],
  ['day', 7],
  ['week', 4.348],
  ['month', 12],
  ['year', Number.POSITIVE_INFINITY],
]

const rtf = new Intl.RelativeTimeFormat('en-US', { numeric: 'auto' })

/** "4 minutes ago". Pass `now` explicitly to keep server and client renders identical. */
export function relativeTime(iso: string, now: number = Date.now()): string {
  const then = Date.parse(iso)
  if (Number.isNaN(then)) return iso

  let delta = (then - now) / 1000
  for (const [unit, span] of UNITS) {
    if (Math.abs(delta) < span) return rtf.format(Math.round(delta), unit)
    delta /= span
  }
  return iso
}

/** "14:05:07" — the precise instant, in the viewer's zone. */
export function clockTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleTimeString('en-GB', { hour12: false })
}

/** "25 Jul 2026, 14:05:07" for tooltips and audit detail. */
export function fullTimestamp(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString('en-GB', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
}

/** "8.4s" / "420ms" — how long the agent took to think. */
export function formatDuration(ms: number | undefined): string | null {
  if (ms === undefined || ms === null) return null
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}
