import type { Mandate } from '@curator/schema'
import { Badge } from '@/components/ui/Badge'
import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { DataSourceGrants } from './DataSourceGrants'

/**
 * The mandate, read-only.
 *
 * This is the contract the agent operates under and the thing a depositor is
 * actually trusting, so it renders in full rather than as a summary — including
 * the update rules, which are the only stated limit on the agent amending its
 * own mandate after genesis.
 */
export function MandateView({
  mandate,
  provenance,
}: {
  mandate: Mandate
  provenance?: React.ReactNode
}) {
  const { constraints } = mandate

  return (
    <Card>
      <CardHeader
        // "Mandate", not the mandate's name: the page heading is already the
        // name, and printing it twice reads as a duplicated section.
        title="Mandate"
        subtitle={`${mandate.name} · version ${mandate.version} · crystallised at genesis · only the agent may amend it`}
        right={<Badge tone="agent">{mandate.risk_posture}</Badge>}
      />
      <CardBody className="space-y-5">
        {provenance}

        <div>
          <div className="label">Objective</div>
          <p className="mt-1.5 whitespace-pre-line text-sm leading-relaxed text-ink/90">
            {mandate.objective}
          </p>
        </div>

        <div>
          <div className="label">Constraints</div>
          <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-2.5 sm:grid-cols-3">
            <Constraint label="Base asset" value={mandate.base_asset} />
            <Constraint label="Allowed assets" value={constraints.allowed_assets.join(', ')} />
            <Constraint label="Max position" value={pct(constraints.max_position_pct)} />
            <Constraint label="Min cash" value={pct(constraints.min_cash_pct)} />
            <Constraint label="Max slippage" value={`${constraints.max_slippage_bps} bps`} />
            <Constraint
              label="Rebalance cooldown"
              value={formatCooldown(constraints.rebalance_cooldown_seconds)}
            />
            <Constraint label="Actions per tick" value={String(constraints.max_actions_per_tick)} />
          </dl>
        </div>

        <div className="grid gap-5 sm:grid-cols-2">
          <div>
            <div className="label">Permitted data sources</div>
            <div className="mt-2">
              <DataSourceGrants sources={mandate.permitted_data_sources} />
            </div>
          </div>
          <div>
            <div className="label">Permitted venues</div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {mandate.permitted_venues.map((venue) => (
                <Badge key={venue} tone="neutral">
                  {venue}
                </Badge>
              ))}
            </div>
          </div>
        </div>

        {mandate.update_rules ? (
          <div>
            <div className="label">Update rules</div>
            <p className="mt-1.5 text-xs leading-relaxed text-muted">{mandate.update_rules}</p>
          </div>
        ) : null}
      </CardBody>
    </Card>
  )
}

function Constraint({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-2xs text-faint">{label}</dt>
      <dd className="tabular mt-0.5 truncate text-xs text-ink" title={value}>
        {value}
      </dd>
    </div>
  )
}

function pct(fraction: number): string {
  return `${Math.round(fraction * 100)}%`
}

function formatCooldown(seconds: number): string {
  if (seconds >= 3600) return `${(seconds / 3600).toFixed(seconds % 3600 === 0 ? 0 : 1)}h`
  if (seconds >= 60) return `${Math.round(seconds / 60)}m`
  return `${seconds}s`
}
