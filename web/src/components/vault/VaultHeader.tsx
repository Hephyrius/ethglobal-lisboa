import Link from 'next/link'
import type { VaultState } from '@curator/schema'
import { Badge } from '@/components/ui/Badge'
import { AddressChip } from '@/components/ui/AddressChip'
import { networkLabel } from '@/lib/chain/explorer'
import { shortHash } from '@/lib/format/units'

export function VaultHeader({ state, name }: { state: VaultState; name?: string }) {
  return (
    <header>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <h1 className="text-xl font-semibold tracking-tight text-ink sm:text-2xl">
          {name ?? 'Curated vault'}
        </h1>
        {/* "ACTIVE", not "LIVE" — the header already carries a LIVE/FIXTURES
            data-provenance badge, and two differently-scoped "LIVE"s on one
            screen is the kind of ambiguity a judge resolves the wrong way. */}
        {state.paused ? <Badge tone="bad">PAUSED</Badge> : <Badge tone="ok">ACTIVE</Badge>}
        <Badge tone="neutral">{networkLabel}</Badge>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 sm:gap-x-6">
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

      {/* The full "AGENT_ROLE / no human override / where the mandate lives"
          text moved to /docs (Wave 2 §E7). It was competing with the numbers a
          reader came to this page for, and it is the passage most worth being
          able to link someone to. One line stays, because a reader who never
          opens the docs should still know the vault has no human override. */}
      <p className="mt-4 max-w-3xl text-xs leading-relaxed text-muted">
        No human override after genesis. The mandate is the only thing constraining the agent.{' '}
        <Link href="/docs" className="text-agent underline-offset-2 hover:underline">
          How this works
        </Link>
      </p>
    </header>
  )
}
