'use client'

import type { VaultState } from '@curator/schema'
import { Badge } from '@/components/ui/Badge'

/**
 * The vault is paused, and the first thing a depositor needs to know is what
 * that does *not* mean.
 *
 * ## Why this is worded so insistently
 *
 * "Paused" is a word depositors have learned to read as *your money is stuck*,
 * because in most of DeFi it is — a pause that halts withdrawals is the
 * standard shape. Here it is the opposite by construction: Lane A's §A2 pauses
 * `execute`/`executeBatch` and is forbidden from touching `withdraw`/`redeem`,
 * pinned by a test that pauses and then withdraws successfully. So a bare
 * PAUSED chip on this page would communicate the exact inverse of the truth,
 * and it would do it at the worst possible moment.
 *
 * Hence the layout: the halt and the exit get equal weight, side by side, with
 * the withdrawal side stated in plain words rather than left to be inferred
 * from the deposit panel still being enabled.
 *
 * ## Why the guardian's limits are on the banner rather than in the docs
 *
 * The obvious objection to any pause is that it re-introduces the human
 * override this vault's entire pitch is built on not having. The answer is
 * specific and checkable — the guardian can stop trading and cannot direct it,
 * cannot reach depositor exits, and could already halt trading before §A2 by
 * flipping every target off one at a time — so it belongs where the objection
 * is raised, not three clicks away in a drawer nobody opens during a demo.
 */
export function PausedBanner({ state }: { state: VaultState }) {
  if (!state.paused) return null

  return (
    <section className="overflow-hidden rounded-lg border border-warn/35 bg-warn/[0.06]">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-warn/20 px-4 py-3">
        <Badge tone="warn">PAUSED BY GUARDIAN</Badge>
        <h2 className="text-sm font-medium text-ink">Trading is halted. Withdrawals are not.</h2>
      </div>

      <div className="grid gap-px bg-warn/15 sm:grid-cols-2">
        <div className="bg-surface px-4 py-3">
          <p className="label text-warn/90">What is stopped</p>
          <p className="mt-1.5 text-xs leading-relaxed text-muted">
            The agent cannot open or increase a position. While paused it may still trade{' '}
            <span className="font-medium text-ink">towards the base asset only</span> — the contract
            checks the balances after every batch and reverts anything that increases a non-base
            holding, so a paused vault can convert to cash and do nothing else.
          </p>
        </div>

        <div className="bg-surface px-4 py-3">
          <p className="label text-ok/90">What still works</p>
          <p className="mt-1.5 text-xs leading-relaxed text-muted">
            <span className="font-medium text-ink">Your withdrawal.</span> The pause cannot reach{' '}
            <span className="font-mono text-2xs">withdraw</span> or{' '}
            <span className="font-mono text-2xs">redeem</span> — that boundary is the feature, not an
            oversight, because a guardian who could freeze exits would hold more power than the agent
            it exists to guard against.
          </p>
        </div>
      </div>

      <p className="border-t border-warn/20 px-4 py-2.5 text-2xs leading-relaxed text-faint">
        The guardian can pause; it <span className="font-medium text-muted">cannot choose the
        trade</span>. Route and size stay with the agent, under the same allowlist and the same
        mandate. This narrows a power the guardian already had — it could halt trading before this
        existed by revoking every execution target one at a time.
      </p>
    </section>
  )
}
