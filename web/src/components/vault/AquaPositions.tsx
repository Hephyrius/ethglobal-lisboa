'use client'

import type { AgentAction, VaultState } from '@curator/schema'
import { Badge } from '@/components/ui/Badge'
import { Card, CardBody, CardHeader } from '@/components/ui/Card'
import { CopyButton } from '@/components/ui/AddressChip'
import { TokenMark } from '@/components/ui/TokenMark'
import { useVaultDecisions } from '@/lib/api/vault-queries'
import { fullTimestamp, relativeTime } from '@/lib/format/time'
import { shortHash } from '@/lib/format/units'

/**
 * Open Aqua positions, and the one sentence that makes them mean anything.
 *
 * An Aqua strategy is the least self-explanatory thing on this page: the vault
 * is quoting as a market maker, yet `totalAssets()` has not moved and the
 * tokens are still in the holdings list. Read without explanation that looks
 * like double-counting. It is not — Aqua tracks a **virtual balance** and the
 * tokens only move when a taker actually fills. That is precisely why the
 * integration is compatible with the vault being sole custodian, and it is the
 * strongest claim the 1inch work makes, so it is stated rather than implied.
 *
 * ## The program parameters come from the decision, not the vault
 *
 * `VaultState.aqua_strategies` records *that* a strategy is open — hash,
 * tokens, when. Which curve the agent chose and what maker fee it set live in
 * the `AllocationDecision` that shipped it, because they were a decision rather
 * than a piece of chain state. Matching them up is what turns "there is a
 * position" into "the agent chose these terms", so this reaches into the
 * decision feed to find the ship that opened each strategy. When no matching
 * decision is in the loaded window the position still renders — without
 * inventing terms for it.
 */
export function AquaPositions({ state }: { state: VaultState }) {
  const { data } = useVaultDecisions(state.address)

  if (state.aqua_strategies.length === 0) return null

  const program = latestShipProgram(data?.data ?? [])

  return (
    <Card>
      <CardHeader
        title="Aqua positions"
        subtitle="Quoting as a maker on 1inch Aqua. The tokens never leave the vault."
        right={<Badge tone="agent">{state.aqua_strategies.length} open</Badge>}
      />
      <CardBody className="space-y-3">
        {state.aqua_strategies.map((strategy) => (
          <div key={strategy.strategy_hash} className="rounded border border-line bg-raised/40 p-3">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
              <div className="flex items-center gap-1.5">
                {strategy.tokens.map((token, index) => (
                  <TokenMark
                    key={token}
                    symbol={symbolFor(state, token)}
                    className={index > 0 ? '-ml-2' : undefined}
                  />
                ))}
                <span className="ml-1 text-sm font-medium text-ink">
                  {strategy.tokens.map((token) => symbolFor(state, token)).join(' / ')}
                </span>
              </div>

              {strategy.shipped_at ? (
                <span className="text-2xs text-faint" title={fullTimestamp(strategy.shipped_at)}>
                  shipped {relativeTime(strategy.shipped_at)}
                </span>
              ) : null}
            </div>

            {program ? (
              <div className="mt-2.5 flex flex-wrap items-center gap-x-2 gap-y-1 rounded border border-agent/20 bg-agent/[0.05] px-2 py-1.5">
                <span className="text-2xs font-semibold uppercase tracking-[0.09em] text-agent">
                  SwapVM
                </span>
                <span className="text-2xs text-muted">
                  {program.shape === 'xyc' ? 'constant-product (xyc) curve' : 'pegged curve'}
                  {program.fee_bps !== undefined ? ` · ${program.fee_bps} bps maker fee` : null}
                </span>
              </div>
            ) : null}

            <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1">
              <span className="inline-flex min-w-0 items-center gap-1">
                <span className="label">strategy</span>
                <span className="font-mono text-2xs text-muted" title={strategy.strategy_hash}>
                  {shortHash(strategy.strategy_hash)}
                </span>
                <CopyButton value={strategy.strategy_hash} />
              </span>
            </div>
          </div>
        ))}

        <p className="text-2xs leading-relaxed text-muted">
          These balances still appear in holdings because they have not moved. Aqua tracks a virtual
          balance against tokens the vault continues to custody, and a transfer happens only when a
          taker fills — which is what lets the vault post a quote without{' '}
          <span className="font-mono">totalAssets()</span> ever misstating what it holds.
        </p>
      </CardBody>
    </Card>
  )
}

/**
 * The program from the most recent ship in the loaded decision window that
 * actually recorded one.
 *
 * Ships whose intent omitted `program` are skipped rather than defaulted: a
 * model-authored ship did exactly that, and substituting `xyc` would put a
 * curve on the page that no decision ever chose.
 */
function latestShipProgram(actions: AgentAction[]) {
  for (const action of actions) {
    for (const intent of action.decision?.venue_intents ?? []) {
      if (intent.kind === 'ship' && intent.program) return intent.program
    }
  }
  return undefined
}

/** Strategies carry addresses; holdings carry the symbols a reader recognises. */
function symbolFor(state: VaultState, token: string): string {
  const match = state.holdings.find(
    (holding) => holding.token.toLowerCase() === token.toLowerCase(),
  )
  return match?.symbol ?? `${token.slice(0, 6)}…`
}
