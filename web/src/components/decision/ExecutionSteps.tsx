import type { ExecutionPlan } from '@curator/schema'
import { Badge } from '@/components/ui/Badge'
import { AddressChip, CopyButton } from '@/components/ui/AddressChip'
import { txUrl } from '@/lib/chain/explorer'
import { shortHash } from '@/lib/format/units'

/**
 * What actually reached the chain: the calldata the agent sent and the
 * transactions it landed.
 *
 * Steps and transaction hashes are paired **by index, and only when the counts
 * match**. They are separate fields in the schema with no declared
 * correspondence, so inventing a pairing when there are three steps and one
 * hash would be a guess presented as a fact. When they do not line up, both are
 * shown, unpaired.
 */
export function ExecutionSteps({
  plan,
  txHashes,
}: {
  plan?: ExecutionPlan
  txHashes: string[]
}) {
  const steps = plan?.steps ?? []
  const paired = steps.length > 0 && steps.length === txHashes.length

  if (steps.length === 0 && txHashes.length === 0) return null

  return (
    <div className="space-y-2.5">
      {plan?.expected_effect ? (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-ink">{plan.expected_effect}</span>
          {plan.expected_slippage_bps !== undefined ? (
            <Badge tone="neutral" title="Expected slippage on this plan">
              {plan.expected_slippage_bps} bps slip
            </Badge>
          ) : null}
        </div>
      ) : null}

      {steps.map((step, index) => (
        <div key={`${step.target}-${index}`} className="rounded-lg border border-line bg-raised/50 p-3">
          <div className="flex items-start gap-2">
            <span className="mt-0.5 font-mono text-2xs text-faint">{index + 1}</span>
            <div className="min-w-0 flex-1">
              <p className="text-xs leading-relaxed text-ink">{step.why}</p>

              <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1.5">
                <AddressChip address={step.target} label="to" />
                <span className="inline-flex items-center gap-1 text-2xs text-faint">
                  <span className="label">data</span>
                  <span className="font-mono" title={step.calldata}>
                    {step.calldata.slice(0, 10)}…
                  </span>
                  <CopyButton value={step.calldata} />
                </span>
              </div>

              {paired ? <TxLink hash={txHashes[index]} /> : null}
            </div>
          </div>
        </div>
      ))}

      {!paired && txHashes.length > 0 ? (
        <div className="rounded-lg border border-ok/25 bg-ok/[0.04] p-3">
          <div className="label text-ok/80">Transactions</div>
          <div className="mt-1.5 space-y-1">
            {txHashes.map((hash) => (
              <TxLink key={hash} hash={hash} />
            ))}
          </div>
        </div>
      ) : null}
    </div>
  )
}

function TxLink({ hash }: { hash: string }) {
  const href = txUrl(hash)

  return (
    <div className="mt-2 flex items-center gap-1.5">
      <span className="h-1.5 w-1.5 rounded-full bg-ok" />
      {href ? (
        <a
          href={href}
          target="_blank"
          rel="noreferrer"
          className="font-mono text-2xs text-ok underline decoration-ok/30 underline-offset-2 hover:decoration-ok"
          title={hash}
        >
          {shortHash(hash)}
        </a>
      ) : (
        <span className="font-mono text-2xs text-ok/90" title={`${hash} — local fork, not on BaseScan`}>
          {shortHash(hash)}
        </span>
      )}
      <CopyButton value={hash} />
      {href ? null : <span className="text-2xs text-faint">fork</span>}
    </div>
  )
}
