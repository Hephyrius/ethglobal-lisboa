import type { Fact } from '@curator/schema'
import { Badge } from '@/components/ui/Badge'
import { factSubject, factValue, kindLabel } from '@/lib/format/facts'
import { clockTime, fullTimestamp } from '@/lib/format/time'
import { cn } from '@/lib/cn'

/**
 * One observation the agent read, with the source that reported it.
 *
 * Provenance is not decoration here — `Fact.source` is the registry key of the
 * adapter that produced the number, and showing it is what lets a judge trace a
 * claim in the reasoning back to a specific data provider.
 */
export function FactCard({ fact, cited = true }: { fact: Fact; cited?: boolean }) {
  return (
    <div
      className={cn(
        'rounded-lg border px-3 py-2.5 transition-colors',
        cited ? 'border-data/25 bg-data/[0.04]' : 'border-line bg-raised/40',
      )}
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className="label truncate">{kindLabel(fact.kind)}</span>
        <span
          className="shrink-0 font-mono text-2xs text-faint"
          title={fullTimestamp(fact.observed_at)}
        >
          {clockTime(fact.observed_at)}
        </span>
      </div>

      <div className="mt-1 truncate text-xs text-muted" title={factSubject(fact)}>
        {factSubject(fact)}
      </div>

      <div className="mt-1.5 flex items-center justify-between gap-2">
        <span className={cn('tabular text-lg font-semibold', cited ? 'text-ink' : 'text-muted')}>
          {factValue(fact)}
        </span>
        <Badge tone={cited ? 'data' : 'neutral'} title={`Reported by the "${fact.source}" source`}>
          {fact.source}
        </Badge>
      </div>

      {fact.confidence !== undefined ? (
        <div className="mt-1.5 text-2xs text-faint">confidence {Math.round(fact.confidence * 100)}%</div>
      ) : null}
    </div>
  )
}

/**
 * A fact id the decision cited that is not in the snapshot it was given.
 *
 * The schema calls this out explicitly: `facts_used` must reference real
 * `Fact.id`s, and it is how we catch a model inventing numbers. Dropping these
 * silently would throw away the only signal that it happened, so they render.
 */
export function UnresolvedFactCard({ id }: { id: string }) {
  return (
    <div className="rounded-lg border border-bad/30 bg-bad/[0.05] px-3 py-2.5">
      <div className="label text-bad/80">Unresolved</div>
      <div className="mt-1 font-mono text-xs text-bad">{id}</div>
      <p className="mt-1.5 text-2xs leading-relaxed text-bad/70">
        Cited by the decision but absent from the snapshot the agent was given.
      </p>
    </div>
  )
}
