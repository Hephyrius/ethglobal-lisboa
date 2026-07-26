'use client'

import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { DecisionCard } from './DecisionCard'
import { useVaultDecisions, useVaultTick } from '@/lib/api/vault-queries'
import type { FeedContext } from './feed-context'

/**
 * The decision feed — newest first.
 *
 * The "run agent tick" button is here rather than in some settings panel
 * because triggering a cycle and watching the resulting card appear at the top
 * is the demo: it turns an audit log into something a judge sees happen.
 */
export function DecisionFeed({
  address,
  context,
  highlightId,
}: {
  address: string
  /** Vault/mandate facts an AgentAction does not carry. See feed-context.ts. */
  context?: FeedContext
  /** Action id the track-record chart last pointed at, ringed here. */
  highlightId?: string | null
}) {
  const { data, isPending } = useVaultDecisions(address)
  const tick = useVaultTick(address)

  const actions = data?.data ?? []

  return (
    <section>
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-ink">Agent decision feed</h2>
          <p className="mt-1 text-xs text-muted">
            Every cycle the curator has run: the data it consulted, the reasoning it produced, and
            what reached the chain.
          </p>
        </div>

        <Button
          variant="primary"
          size="sm"
          loading={tick.isPending}
          onClick={() => tick.mutate()}
          title="Ask the agent to run one decision cycle now"
        >
          {tick.isPending ? 'Agent thinking…' : 'Run agent tick'}
        </Button>
      </div>

      {tick.isError ? (
        <div className="mb-4 rounded-lg border border-bad/25 bg-bad/[0.05] px-4 py-3 text-xs text-bad/90">
          {tick.error instanceof Error ? tick.error.message : 'The tick request failed.'}
        </div>
      ) : null}

      {isPending ? (
        <FeedSkeleton />
      ) : actions.length === 0 ? (
        <Card className="border-dashed px-5 py-10 text-center">
          <p className="text-sm text-muted">The agent has not run a cycle yet.</p>
          <p className="mt-1 text-xs text-faint">
            Run a tick to have it consult its data sources and decide.
          </p>
        </Card>
      ) : (
        <div className="space-y-4">
          {actions.map((action, index) => (
            <DecisionCard
              key={action.id}
              action={action}
              isLatest={index === 0}
              isHighlighted={action.id === highlightId}
              context={context}
            />
          ))}
        </div>
      )}
    </section>
  )
}

function FeedSkeleton() {
  return (
    <div className="space-y-4">
      {[0, 1].map((row) => (
        <div key={row} className="card overflow-hidden">
          <div className="h-12 border-b border-line bg-raised/30" />
          <div className="grid gap-px bg-line lg:grid-cols-3">
            {[0, 1, 2].map((column) => (
              <div key={column} className="space-y-2 bg-surface p-4">
                <div className="h-2.5 w-24 animate-pulse-soft rounded bg-line-bright" />
                <div className="h-16 animate-pulse-soft rounded bg-line-bright/60" />
                <div className="h-16 animate-pulse-soft rounded bg-line-bright/40" />
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}
