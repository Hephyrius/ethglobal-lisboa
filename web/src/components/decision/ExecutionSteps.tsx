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
  maxSlippageBps,
}: {
  plan?: ExecutionPlan
  txHashes: string[]
  /** The mandate's ceiling, so an over-limit plan explains its own rejection. */
  maxSlippageBps?: number
}) {
  const steps = plan?.steps ?? []
  const paired = steps.length > 0 && steps.length === txHashes.length

  if (steps.length === 0 && txHashes.length === 0) return null

  return (
    <div className="space-y-2.5">
      {plan?.expected_effect || plan?.expected_slippage_bps !== undefined ? (
        <div className="flex flex-wrap items-center gap-2">
          {plan?.expected_effect ? (
            <span className="text-xs text-ink">{plan.expected_effect}</span>
          ) : null}
          <Slippage bps={plan?.expected_slippage_bps} maxSlippageBps={maxSlippageBps} />
        </div>
      ) : null}

      {steps.map((step, index) => (
        <div
          key={`${step.target}-${index}`}
          className="overflow-hidden rounded-lg border border-line bg-raised/50 p-3"
        >
          <div className="flex items-start gap-2">
            <span className="mt-0.5 font-mono text-2xs text-faint">{index + 1}</span>
            <div className="min-w-0 flex-1">
              <p className="text-xs leading-relaxed text-ink">{step.why}</p>

              {/* min-w-0 lets the flex children actually shrink: without it a
                  long mono address refuses to wrap and pushes the card wider
                  than the viewport at 375px. */}
              <div className="mt-2 flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1.5">
                <AddressChip address={step.target} label="to" />
                <span className="inline-flex min-w-0 items-center gap-1 text-2xs text-faint">
                  <span className="label">data</span>
                  <span className="truncate font-mono" title={step.calldata}>
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

/**
 * `ExecutionPlan.expected_slippage_bps` is a **ceiling, not an estimate.**
 *
 * The field name says "expected", but Lane D populates it from the Uniswap
 * API's slippage *tolerance* — 250 bps by default, where the realised fill was
 * 0.035% (cross-lane request #26). Rendering that as "250 bps slip" claims a
 * low-drawdown vault just took a 2.5% hit, which is both wrong and precisely
 * the number a judge would stop on. So it reads as a limit.
 *
 * When it exceeds the mandate's own ceiling the badge turns red, because that
 * is exactly why the harness refuses to execute — the reader should not have to
 * infer the cause of a rejection that is sitting right there in the numbers.
 */
function Slippage({ bps, maxSlippageBps }: { bps?: number; maxSlippageBps?: number }) {
  if (bps === undefined) return null

  const overLimit = maxSlippageBps !== undefined && bps > maxSlippageBps

  return (
    <Badge
      tone={overLimit ? 'bad' : 'neutral'}
      title={
        `Slippage tolerance the venue quoted, not a prediction of impact.` +
        (maxSlippageBps !== undefined
          ? overLimit
            ? ` It exceeds the mandate ceiling of ${maxSlippageBps} bps, so the harness refuses to execute this plan.`
            : ` Inside the mandate ceiling of ${maxSlippageBps} bps.`
          : '')
      }
    >
      ≤ {bps} bps slippage
      {overLimit ? ` · over the ${maxSlippageBps} bps mandate limit` : null}
    </Badge>
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
        <span className="font-mono text-2xs text-ok/90" title={`${hash} · local fork, not on BaseScan`}>
          {shortHash(hash)}
        </span>
      )}
      <CopyButton value={hash} />
      {href ? null : <span className="text-2xs text-faint">fork</span>}
    </div>
  )
}
