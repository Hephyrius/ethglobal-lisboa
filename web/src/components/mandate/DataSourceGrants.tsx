import { Badge } from '@/components/ui/Badge'

/**
 * The data sources the agent is permitted to consult.
 *
 * Shared between genesis (where the user grants them) and the vault page (where
 * a depositor audits them) on purpose: it is the same concept at both ends, and
 * the user should recognise it as the same thing.
 *
 * These are registry keys, resolved by the data layer at runtime — so granting a
 * source is a mandate edit rather than a code change, and this list is
 * *exhaustive*. Anything not named here, the agent cannot see.
 */
export function DataSourceGrants({
  sources,
  emptyHint = 'No sources granted yet.',
}: {
  sources?: string[]
  emptyHint?: string
}) {
  if (!sources || sources.length === 0) {
    return <p className="text-xs text-faint">{emptyHint}</p>
  }

  return (
    <div className="flex flex-wrap gap-1.5">
      {sources.map((source) => (
        <Badge key={source} tone="data" title={`Registry key "${source}"`}>
          {source}
        </Badge>
      ))}
    </div>
  )
}
