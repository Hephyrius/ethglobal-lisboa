'use client'

import { useState } from 'react'
import type { AgentAction, Fact } from '@curator/schema'
import { Badge, type BadgeTone } from '@/components/ui/Badge'
import { FactCard, UnresolvedFactCard } from './FactCard'
import { BlindSpots } from './BlindSpots'
import { SourceNotes } from './SourceNotes'
import { InjectionFindings } from './InjectionFindings'
import { ExecutionSteps } from './ExecutionSteps'
import { VenueIntents } from './VenueIntents'
import { YieldComparison } from './YieldComparison'
import { BandedWarnings } from './BandedWarnings'
import type { FeedContext } from './feed-context'
import { clockTime, formatDuration, fullTimestamp, relativeTime } from '@/lib/format/time'
import { cn } from '@/lib/cn'

/**
 * One decision cycle, drawn as the causal chain it actually is:
 *
 *   ① what the agent read  →  ② what it concluded  →  ③ what it did
 *
 * This component is the product. Everything else in the app exists to get a
 * judge to this card and make it legible. The three stages are laid out as
 * three columns precisely so the causality is spatial rather than something the
 * viewer has to reconstruct from a log.
 */

const STATUS: Record<AgentAction['status'], { tone: BadgeTone; label: string }> = {
  executed: { tone: 'ok', label: 'EXECUTED' },
  held: { tone: 'warn', label: 'HELD' },
  rejected: { tone: 'bad', label: 'REJECTED' },
  failed: { tone: 'bad', label: 'FAILED' },
  pending: { tone: 'neutral', label: 'PENDING' },
}

/** DOM id for one decision's card. One definition, used by both sides. */
export function decisionAnchor(actionId: string): string {
  return `decision-${actionId}`
}

export function DecisionCard({
  action,
  isLatest,
  isHighlighted,
  context,
}: {
  action: AgentAction
  isLatest?: boolean
  /** Highlighted because the chart above was clicked on this decision. */
  isHighlighted?: boolean
  context?: FeedContext
}) {
  const status = STATUS[action.status]
  const facts = action.snapshot?.facts ?? []
  const factsById = new Map(facts.map((fact) => [fact.id, fact]))

  const citedIds = action.decision?.facts_used ?? []
  const cited: Fact[] = []
  const unresolved: string[] = []
  for (const id of citedIds) {
    const fact = factsById.get(id)
    if (fact) cited.push(fact)
    else unresolved.push(id)
  }

  const uncited = facts.filter((fact) => !citedIds.includes(fact.id))

  return (
    <article
      // Stable anchor so the track-record chart can scroll a marker's decision
      // into view. The whole point of marking executed decisions on the curve
      // is that a step in the price leads to the reasoning that caused it.
      id={decisionAnchor(action.id)}
      className={cn(
        'card overflow-hidden animate-fade-up scroll-mt-24',
        isLatest && 'ring-1 ring-agent/20',
        isHighlighted && 'ring-2 ring-agent/60',
      )}
    >
      <header className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-line px-4 py-3">
        <Badge tone={status.tone}>{status.label}</Badge>
        <span className="font-mono text-xs text-muted">{action.id}</span>

        <span className="text-xs text-faint" title={fullTimestamp(action.timestamp)}>
          {clockTime(action.timestamp)} · {relativeTime(action.timestamp)}
        </span>

        <div className="ml-auto flex flex-wrap items-center gap-2">
          {action.duration_ms !== undefined ? (
            <span className="text-2xs text-faint" title="Time to complete the cycle">
              {formatDuration(action.duration_ms)}
            </span>
          ) : null}
          {action.model?.name ? (
            <Badge tone="neutral" title={`Model backend: ${action.model.backend ?? 'unknown'}`}>
              {action.model.name}
            </Badge>
          ) : null}
          {action.model && action.model.validation_retries > 0 ? (
            <Badge
              tone={action.status === 'rejected' ? 'bad' : 'warn'}
              title="Malformed model outputs rejected by schema validation before a valid one was accepted"
            >
              {action.model.validation_retries} retr{action.model.validation_retries === 1 ? 'y' : 'ies'}
            </Badge>
          ) : null}
        </div>
      </header>

      <div className="grid gap-px bg-line lg:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)_minmax(0,1fr)]">
        <Stage index="01" title="Data consulted" accent="text-data">
          {/* The relationship between the facts, which a list of cards cannot
              show — and the comparison the mandate actually asks the agent to
              make. Renders only when there are two or more yields. */}
          <YieldComparison facts={facts} citedIds={citedIds} />

          {cited.length === 0 && unresolved.length === 0 ? (
            <p className="text-xs text-faint">
              {facts.length > 0
                ? 'The decision cited no specific facts.'
                : 'No snapshot recorded for this cycle.'}
            </p>
          ) : (
            <div className="space-y-2">
              {cited.map((fact) => (
                <FactCard key={fact.id} fact={fact} />
              ))}
              {unresolved.map((id) => (
                <UnresolvedFactCard key={id} id={id} />
              ))}
            </div>
          )}

          {uncited.length > 0 ? <UncitedFacts facts={uncited} /> : null}
          {action.snapshot ? <BlindSpots snapshot={action.snapshot} /> : null}
          {action.snapshot ? <SourceNotes snapshot={action.snapshot} /> : null}
          {/* Last in the column, directly above the reasoning it was trying to
              influence. The adjacency is the argument: here is what the feed
              was carrying, and here is what the agent decided anyway. */}
          <InjectionFindings action={action} />
        </Stage>

        <Stage
          index="02"
          title={action.decision ? 'Reasoning' : 'Model output rejected'}
          accent="text-agent"
        >
          {action.decision ? (
            <>
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone="agent">{action.decision.action}</Badge>
                {action.decision.confidence !== undefined ? (
                  <span className="text-2xs text-faint">
                    confidence {Math.round(action.decision.confidence * 100)}%
                  </span>
                ) : null}
              </div>

              <p className="mt-3 whitespace-pre-line text-sm leading-relaxed text-ink/90">
                {action.decision.reasoning}
              </p>

              {action.decision.target_allocations?.length ? (
                <TargetAllocations allocations={action.decision.target_allocations} />
              ) : null}

              {action.decision.venue_intents?.length ? (
                <VenueIntents
                  intents={action.decision.venue_intents}
                  tokenDecimals={context?.tokenDecimals}
                />
              ) : null}

              {/* Beside the reasoning, not tucked in a corner: a band that is
                  invisible is the same as no rule, and the drift it enables is
                  silent by construction. */}
              <BandedWarnings warnings={action.warnings} />
            </>
          ) : (
            <p className="whitespace-pre-line text-sm leading-relaxed text-bad/90">
              {action.error ?? 'The model produced no usable decision this cycle.'}
            </p>
          )}
        </Stage>

        <Stage
          index="03"
          title={action.status === 'executed' ? 'Executed' : 'Outcome'}
          accent={action.status === 'executed' ? 'text-ok' : 'text-muted'}
        >
          <Outcome action={action} maxSlippageBps={context?.maxSlippageBps} />
        </Stage>
      </div>
    </article>
  )
}

function Stage({
  index,
  title,
  accent,
  children,
}: {
  index: string
  title: string
  accent: string
  children: React.ReactNode
}) {
  return (
    <section className="bg-surface p-4">
      <div className="mb-3 flex items-baseline gap-2">
        <span className={cn('font-mono text-2xs', accent)}>{index}</span>
        <h3 className="label">{title}</h3>
      </div>
      {children}
    </section>
  )
}

function Outcome({ action, maxSlippageBps }: { action: AgentAction; maxSlippageBps?: number }) {
  if (action.status === 'executed' || action.tx_hashes.length > 0) {
    return (
      <ExecutionSteps
        plan={action.plan}
        txHashes={action.tx_hashes}
        maxSlippageBps={maxSlippageBps}
      />
    )
  }

  if (action.status === 'held') {
    return (
      <div className="rounded-lg border border-line bg-raised/50 p-3">
        <p className="text-xs leading-relaxed text-muted">
          No transaction. The agent held the current position, a first-class answer under the
          mandate, and the cheaper expression of an unchanged view.
        </p>
      </div>
    )
  }

  if (action.status === 'rejected') {
    return (
      <div className="space-y-2.5">
        <div className="rounded-lg border border-bad/25 bg-bad/[0.05] p-3">
          <p className="text-xs leading-relaxed text-bad/90">
            Nothing reached the chain. Validation rejected the decision before it could be
            submitted. The agent holds a key, so a plan that breaches the mandate is discarded
            rather than trimmed to fit.
          </p>
        </div>

        {/* A plan rejected on slippage still has a plan, and the numbers that
            caused the rejection are in it. Showing them turns "rejected" from
            an assertion into something the reader can check. */}
        {action.plan ? (
          <ExecutionSteps plan={action.plan} txHashes={[]} maxSlippageBps={maxSlippageBps} />
        ) : null}
      </div>
    )
  }

  if (action.status === 'failed') {
    return (
      <div className="space-y-2.5">
        <div className="rounded-lg border border-bad/25 bg-bad/[0.05] p-3">
          <p className="break-words text-xs leading-relaxed text-bad/90">
            {action.error ?? 'Execution failed.'}
          </p>
        </div>

        {/* A plan that reverted on-chain is still the plan that was built, and
            its steps and slippage are what a reader needs to see why. */}
        {action.plan ? (
          <ExecutionSteps
            plan={action.plan}
            txHashes={action.tx_hashes}
            maxSlippageBps={maxSlippageBps}
          />
        ) : null}
      </div>
    )
  }

  return <p className="text-xs text-faint">Cycle in progress…</p>
}

function TargetAllocations({
  allocations,
}: {
  allocations: NonNullable<AgentAction['decision']>['target_allocations']
}) {
  if (!allocations) return null

  return (
    <div className="mt-4">
      <div className="label">Target allocation</div>
      <div className="mt-2 space-y-1.5">
        {allocations.map((allocation) => (
          <div key={allocation.asset} className="flex items-center gap-2.5">
            <span className="w-14 shrink-0 font-mono text-2xs text-muted">{allocation.asset}</span>
            <div className="h-1.5 flex-1 overflow-hidden rounded-sm bg-raised">
              <div
                className="h-full rounded-sm bg-agent/75"
                style={{ width: `${Math.round(allocation.weight * 100)}%` }}
              />
            </div>
            <span className="tabular w-9 shrink-0 text-right text-2xs text-muted">
              {Math.round(allocation.weight * 100)}%
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

/**
 * Facts the snapshot contained but the decision did not cite. Collapsed by
 * default: the cited ones are the causal chain, but "read 6, cited 4" is itself
 * informative — it shows the agent selecting, not just consuming.
 */
function UncitedFacts({ facts }: { facts: Fact[] }) {
  const [open, setOpen] = useState(false)

  return (
    <div className="mt-3">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="text-2xs text-faint transition-colors hover:text-muted"
      >
        {open ? '−' : '+'} {facts.length} more fact{facts.length === 1 ? '' : 's'} consulted, not
        cited
      </button>
      {open ? (
        <div className="mt-2 space-y-2">
          {facts.map((fact) => (
            <FactCard key={fact.id} fact={fact} cited={false} />
          ))}
        </div>
      ) : null}
    </div>
  )
}
