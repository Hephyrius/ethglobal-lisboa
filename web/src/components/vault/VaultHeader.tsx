import type { VaultState } from '@curator/schema'
import { Badge } from '@/components/ui/Badge'
import { AddressChip } from '@/components/ui/AddressChip'
import { networkLabel } from '@/lib/chain/explorer'
import { shortHash } from '@/lib/format/units'

export function VaultHeader({ state, name }: { state: VaultState; name?: string }) {
  return (
    <header>
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-semibold tracking-tight text-ink">
          {name ?? 'Curated vault'}
        </h1>
        {state.paused ? <Badge tone="bad">PAUSED</Badge> : <Badge tone="ok">LIVE</Badge>}
        <Badge tone="neutral">{networkLabel}</Badge>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-x-6 gap-y-2">
        <AddressChip address={state.address} label="vault" />
        {state.agent ? <AddressChip address={state.agent} label="agent" /> : null}
        {state.mandate_hash ? (
          <span className="inline-flex items-center gap-1.5">
            <span className="label">mandate</span>
            <span
              className="font-mono text-xs text-ink"
              title={`keccak256 of the canonical mandate: ${state.mandate_hash}`}
            >
              {shortHash(state.mandate_hash)}
            </span>
          </span>
        ) : null}
        {state.block_number !== undefined ? (
          <span className="inline-flex items-center gap-1.5">
            <span className="label">block</span>
            <span className="tabular font-mono text-xs text-muted">
              {state.block_number.toLocaleString('en-US')}
            </span>
          </span>
        ) : null}
      </div>

      <p className="mt-4 max-w-3xl text-xs leading-relaxed text-muted">
        The agent holds{' '}
        <code className="rounded bg-raised px-1 py-0.5 font-mono text-2xs text-agent">AGENT_ROLE</code>{' '}
        and executes directly. There is no human override after genesis — the mandate below is the
        only thing constraining it, and only the agent may amend it.
      </p>
    </header>
  )
}
