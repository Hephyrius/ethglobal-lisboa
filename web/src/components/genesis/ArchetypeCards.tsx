'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { WalletButton } from '@/components/wallet/WalletButton'
import { useAccount } from '@/lib/chain/account'
import { ARCHETYPES, type ArchetypeCard } from '@/lib/mandate/archetypes'
import { useArchetypeDeploy, type ArchetypeDeployResult } from '@/lib/api/archetype-deploy'
import { shortHash } from '@/lib/format/units'
import { cn } from '@/lib/cn'

/**
 * One click, no form: the model writes a strategy inside the archetype's bounds
 * and it goes on-chain.
 *
 * ## The thing this UI has to communicate, or the feature does not land
 *
 * An archetype is **not a template**. Two clicks on the same card produce two
 * genuinely different vaults, because the model writes a fresh mandate each
 * time inside the same envelope. That is the whole feature — and it is
 * invisible unless the UI says so, because a card with a button looks exactly
 * like a template picker. So: the bounds are labelled as bounds, the copy says
 * the strategy is written per click, and after a deploy the card names the
 * mandate that was actually generated. Click twice and the two names differ on
 * screen, which is the demonstration rather than a claim about it.
 *
 * ## Where the bound text comes from
 *
 * `describeEnvelope()` in `packages/schema`, generated from the same JSON Lane
 * B's gate reads. Nothing on this card is a hand-typed number, so a card cannot
 * promise a limit the envelope does not enforce.
 */
export function ArchetypeCards() {
  const { address, isConnected } = useAccount()

  return (
    <section>
      <div className="border-b border-line pb-2">
        <h2 className="text-sm font-semibold text-ink">Deploy from an archetype</h2>
      </div>

      <p className="mt-3 max-w-2xl text-sm leading-relaxed text-muted">
        No conversation and no form. Each of these is a set of <em>bounds</em>, not a saved strategy.
        One click asks the model to write a fresh mandate inside them, checks it against those
        bounds, and deploys it. No party reviews it before deployment, which is why a mandate that
        escapes its envelope is regenerated rather than deployed.{' '}
        <span className="text-ink">
          Two selections of the same card produce two different vaults.
        </span>
      </p>

      {!isConnected ? (
        <div className="mt-4 flex flex-wrap items-center gap-3 rounded border border-line bg-raised px-3 py-2.5">
          <span className="text-xs text-muted">
            Connect a wallet first. The vault is recorded against the address that asked for it.
          </span>
          <WalletButton />
        </div>
      ) : null}

      <div className="mt-6 grid gap-4 lg:grid-cols-3">
        {ARCHETYPES.map((card) => (
          <ArchetypeTile
            key={card.archetype.key}
            card={card}
            deployer={isConnected ? address : undefined}
          />
        ))}
      </div>
    </section>
  )
}

function ArchetypeTile({
  card,
  deployer,
}: {
  card: ArchetypeCard
  deployer: `0x${string}` | undefined
}) {
  const router = useRouter()
  const deploy = useArchetypeDeploy()
  // Every vault this card has produced this session, newest first. Kept as a
  // list rather than a single "last result" precisely so the second click has
  // somewhere to land beside the first: two differently-named vaults from one
  // card, on screen at once, is the proof that it is not a template.
  const [produced, setProduced] = useState<ArchetypeDeployResult[]>([])

  const { archetype, bounds } = card

  async function run() {
    if (!deployer) return
    try {
      const result = await deploy.mutateAsync({ key: archetype.key, deployer })
      setProduced((previous) => [result, ...previous])
    } catch {
      // Rendered from deploy.error below. A write never falls back.
    }
  }

  return (
    <article className="flex flex-col rounded-lg border border-line bg-surface">
      <div className="border-b border-line px-4 py-3">
        <div className="flex items-baseline justify-between gap-2">
          <h3 className="font-serif text-base text-ink">{archetype.name}</h3>
          {produced.length > 1 ? <Badge tone="agent">{produced.length} deployed</Badge> : null}
        </div>
        <p className="mt-1.5 text-xs leading-relaxed text-muted">{archetype.headline}</p>
      </div>

      <div className="flex-1 space-y-3 px-4 py-3">
        <div>
          <p className="label">Bounds the model must write inside</p>
          <ul className="mt-1.5 space-y-1">
            {bounds.map((line) => (
              <li key={line} className="flex gap-1.5 text-2xs leading-relaxed text-muted">
                <span className="select-none text-faint">·</span>
                <span>{line}</span>
              </li>
            ))}
          </ul>
        </div>

        {/* Required by the schema, and shown for the same reason it is required:
            a menu where every option has only upsides helps nobody choose. */}
        <div className="rounded border border-line bg-raised px-2.5 py-2">
          <p className="label text-faint">Tradeoff</p>
          <p className="mt-1 text-2xs leading-relaxed text-muted">{archetype.tradeoff}</p>
        </div>
      </div>

      <div className="space-y-2.5 border-t border-line px-4 py-3">
        <Button
          variant="primary"
          className="w-full"
          loading={deploy.isPending}
          disabled={!deployer || deploy.isPending}
          onClick={() => void run()}
        >
          {deploy.isPending
            ? 'Writing a mandate…'
            : produced.length > 0
              ? 'Deploy another'
              : 'Generate and deploy'}
        </Button>

        {deploy.isPending ? <DeployStages /> : null}

        {deploy.error ? (
          <p className="text-2xs leading-relaxed text-bad/90">
            {deploy.error instanceof Error ? deploy.error.message : 'Deploy failed'}
          </p>
        ) : null}

        {produced.map((result) => (
          <ProducedVault
            key={result.vault + result.elapsedMs}
            result={result}
            onOpen={() => router.push(`/vault/${result.vault}`)}
          />
        ))}
      </div>
    </article>
  )
}

/**
 * What the one call is doing, stated as description rather than as progress.
 *
 * The three stages happen server-side inside a single request, so the browser
 * cannot know which one is running. A stepper that lit each in turn on a timer
 * would be animating a guess dressed as telemetry — and this is a product whose
 * entire pitch is that you can check what it claims. So all three are shown at
 * once, as *what this does*, and the evidence of what actually happened arrives
 * with the response.
 */
function DeployStages() {
  const stages = [
    'Writing a mandate inside the archetype',
    'Checking it against those bounds',
    'Deploying, and recording the mandate hash on-chain',
  ]

  return (
    <ol className="space-y-1">
      {stages.map((stage) => (
        <li key={stage} className="flex items-start gap-1.5 text-2xs leading-relaxed text-faint">
          <span className="mt-[0.3rem] h-1 w-1 shrink-0 animate-pulse-soft rounded-full bg-agent" />
          <span>{stage}</span>
        </li>
      ))}
    </ol>
  )
}

/**
 * A vault this card produced, named by the mandate the model actually wrote.
 *
 * The name is the load-bearing detail. Two clicks yielding *Prime Cash Ladder*
 * and *Utilisation-Weighted Reserve* is the difference between a generative
 * archetype and a template, shown rather than asserted — so it is rendered
 * even though the address alone would be enough to navigate.
 */
function ProducedVault({ result, onOpen }: { result: ArchetypeDeployResult; onOpen: () => void }) {
  return (
    <div className="rounded border border-agent/25 bg-agent/[0.05] px-2.5 py-2">
      <button
        type="button"
        onClick={onOpen}
        className="block w-full text-left text-xs font-medium text-agent hover:underline"
      >
        {result.mandateName ?? 'New vault'} →
      </button>

      {/* The emphasis this generation was given, from the envelope's own
          `emphases[]`. This is the mechanism that makes two clicks differ, so
          showing it turns structural uniqueness from a claim into something a
          reader can see varying between two cards. */}
      {result.emphasis ? (
        <p className="mt-1 text-2xs leading-relaxed text-muted">
          <span className="text-faint">asked to emphasise: </span>
          {result.emphasis}
        </p>
      ) : null}

      <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-2xs text-faint">
        <span className="font-mono">{shortHash(result.vault)}</span>
        <span>·</span>
        <span>{(result.elapsedMs / 1000).toFixed(1)}s</span>
        {/* Attempts above one means a generation was discarded and rewritten —
            an envelope escape, or a strategy too close to one this archetype
            already deployed. Either way the gate is working, so it is reported
            as evidence rather than buried as a retry. Labelled "regenerated"
            rather than "rejected by the envelope" because the live route
            rejects duplicates far more often than escapes, and naming the wrong
            cause would be a confident guess about someone else's code. */}
        {result.attempts > 1 ? (
          <>
            <span>·</span>
            <span className={cn('text-warn/90')} title={result.rejections.join('\n\n') || undefined}>
              {result.attempts - 1} regenerated
            </span>
          </>
        ) : null}
      </div>
    </div>
  )
}
