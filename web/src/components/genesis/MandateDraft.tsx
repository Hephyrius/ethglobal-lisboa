'use client'

import type { Mandate } from '@curator/schema'
import { Badge } from '@/components/ui/Badge'
import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { DataSourceGrants } from '@/components/mandate/DataSourceGrants'
import { cn } from '@/lib/cn'

/**
 * The mandate assembling itself as the conversation proceeds.
 *
 * Every field is listed from the start, including the ones still empty, so the
 * user can see what remains — and, more importantly, sees the *shape* of what
 * they are about to hand an autonomous agent. Progressive disclosure would hide
 * exactly the thing that deserves scrutiny.
 */
export function MandateDraft({
  draft,
  available,
}: {
  draft: Partial<Mandate>
  available?: { sources: string[]; venues: string[] }
}) {
  const constraints = draft.constraints
  const granted = draft.permitted_data_sources ?? []
  const ungranted = (available?.sources ?? []).filter((source) => !granted.includes(source))

  return (
    <Card>
      <CardHeader
        title={draft.name ?? 'Mandate draft'}
        subtitle="Crystallised at genesis. After deployment only the agent may amend it. You cannot."
        right={draft.risk_posture ? <Badge tone="agent">{draft.risk_posture}</Badge> : null}
      />
      <CardBody className="space-y-4">
        <Field label="Objective" filled={Boolean(draft.objective)}>
          {draft.objective ? (
            <p className="whitespace-pre-line text-xs leading-relaxed text-ink/90">
              {draft.objective}
            </p>
          ) : (
            <Pending>What should this vault try to achieve?</Pending>
          )}
        </Field>

        <Field label="Risk limits" filled={Boolean(constraints)}>
          {constraints ? (
            <dl className="grid grid-cols-2 gap-x-4 gap-y-2">
              <Pair label="Base asset" value={draft.base_asset ?? '—'} />
              <Pair label="Allowed" value={constraints.allowed_assets.join(', ')} />
              <Pair label="Max position" value={`${Math.round(constraints.max_position_pct * 100)}%`} />
              <Pair label="Min cash" value={`${Math.round(constraints.min_cash_pct * 100)}%`} />
              <Pair label="Max slippage" value={`${constraints.max_slippage_bps} bps`} />
              <Pair label="Actions / tick" value={String(constraints.max_actions_per_tick)} />
            </dl>
          ) : (
            <Pending>Position caps, cash floor and slippage ceiling.</Pending>
          )}
        </Field>

        <Field
          label="Data sources granted"
          filled={Boolean(draft.permitted_data_sources?.length)}
          hint="The agent can only reason about markets it is allowed to see. This list is exhaustive."
        >
          <DataSourceGrants
            sources={draft.permitted_data_sources}
            emptyHint="No sources granted. The agent would be blind."
          />
          {ungranted.length > 0 ? (
            <p className="mt-1.5 text-2xs text-faint">
              Registered but not granted: {ungranted.join(', ')}. The agent will not see these.
            </p>
          ) : null}
        </Field>

        <Field label="Execution venues" filled={Boolean(draft.permitted_venues?.length)}>
          {draft.permitted_venues?.length ? (
            <div className="flex flex-wrap gap-1.5">
              {draft.permitted_venues.map((venue) => (
                <Badge key={venue} tone="neutral">
                  {venue}
                </Badge>
              ))}
            </div>
          ) : (
            <Pending>Where the agent may execute.</Pending>
          )}
        </Field>

        {draft.update_rules ? (
          <Field label="Update rules" filled hint="The only stated limit on the agent amending its own mandate.">
            <p className="text-2xs leading-relaxed text-muted">{draft.update_rules}</p>
          </Field>
        ) : null}
      </CardBody>
    </Card>
  )
}

function Field({
  label,
  filled,
  hint,
  children,
}: {
  label: string
  filled: boolean
  hint?: string
  children: React.ReactNode
}) {
  return (
    <div>
      <div className="flex items-center gap-2">
        <span
          className={cn(
            'h-1.5 w-1.5 shrink-0 rounded-full transition-colors',
            filled ? 'bg-ok' : 'bg-line-bright',
          )}
        />
        <span className="label">{label}</span>
      </div>
      <div className="mt-1.5 pl-3.5">{children}</div>
      {hint ? <p className="mt-1 pl-3.5 text-2xs text-faint">{hint}</p> : null}
    </div>
  )
}

function Pending({ children }: { children: React.ReactNode }) {
  return <p className="text-xs italic text-faint">{children}</p>
}

function Pair({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-2xs text-faint">{label}</dt>
      <dd className="tabular truncate text-xs text-ink" title={value}>
        {value}
      </dd>
    </div>
  )
}
