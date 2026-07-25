import type { MarketSnapshot } from '@curator/schema'

/**
 * What the agent could *not* see this tick.
 *
 * A failing data source degrades the snapshot rather than crashing the loop
 * (packages/schema/README.md), which means the agent routinely decides on
 * incomplete information. Hiding that would be the easy choice and the wrong
 * one: an agent that reasons openly about the limits of its own inputs is more
 * trustworthy than one that appears omniscient, and the golden fixture's own
 * reasoning cites a missing volatility series as a reason to size down.
 */
export function BlindSpots({ snapshot }: { snapshot: MarketSnapshot }) {
  if (snapshot.errors.length === 0) return null

  return (
    <div className="mt-3 rounded-lg border border-warn/25 bg-warn/[0.05] px-3 py-2.5">
      <div className="label text-warn/80">Could not see</div>
      <ul className="mt-1.5 space-y-1">
        {snapshot.errors.map((error, index) => (
          <li key={`${error.source}-${index}`} className="text-2xs leading-relaxed text-warn/90">
            <span className="font-mono font-medium">{error.source}</span>
            <span className="text-warn/60"> — </span>
            {error.message}
          </li>
        ))}
      </ul>
    </div>
  )
}
