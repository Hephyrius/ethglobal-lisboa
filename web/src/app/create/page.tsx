'use client'

import { useState } from 'react'
import type { Mandate } from '@curator/schema'
import { ChatPanel } from '@/components/genesis/ChatPanel'
import { MandateDraft } from '@/components/genesis/MandateDraft'
import { DeployPanel } from '@/components/genesis/DeployPanel'
import { ArchetypeCards } from '@/components/genesis/ArchetypeCards'
import { UniverseStrip } from '@/components/genesis/UniverseStrip'
import { AssetUniverse } from '@/components/genesis/AssetUniverse'
import { VenueStrip } from '@/components/venues/VenueStrip'
import { suggestionsFor } from '@/lib/mandate/suggestions'
import { ModeNotice } from '@/components/ui/ModeBadge'
import { useGenesisChat, useGenesisSources } from '@/lib/api/genesis-queries'
import { GENESIS_OPENING, type ChatMessage } from '@/lib/api/genesis-sim'
import { cn } from '@/lib/cn'

type Track = 'agent' | 'archetype'

/** The chooser's label for each track, in one place so the card and the
 *  `ChosenTrack` banner cannot drift apart. */
const TRACK_TITLES: Record<Track, string> = {
  agent: 'Deploy a Scipio Agent Created Vault',
  archetype: 'Deploy from an archetype',
}

/**
 * Create a vault by one of two mutually exclusive routes.
 *
 * ## The page is a chooser, not a menu of everything
 *
 * Every route used to be on screen at once, the universe strips and the
 * conversation stacked together, and a reader had no way to tell which controls
 * belonged to the path they had picked. Now nothing renders until a track is
 * chosen, and choosing one hides the other *including its description card*: an
 * option is not hidden by a dimmed card that still explains it.
 *
 * ## Why there are two routes and not three
 *
 * A standard-mandate track sat between these, loading a preset for the reader
 * to review and then deploy. That is the archetype track with the model swapped
 * for a fixed file: the same promise and the same click, distinguishable only by
 * holding both descriptions in mind at once. The archetype route is the one that
 * survives, because it is the only one of the two that produces a mandate
 * written for the vault rather than copied into it.
 *
 * `PresetCards` and the preset draft went with it. Nothing else consumed either,
 * so removing the track removed the reason for a second draft to exist.
 *
 * The agent draft accumulates rather than being re-derived each turn:
 * `mandate_draft` is a *partial*, each turn contributing the fields it learned
 * about and leaving the rest alone. Merging on top of what we have is what lets
 * the mandate build across a conversation instead of resetting to whatever the
 * last turn happened to mention.
 */
export default function CreatePage() {
  const [track, setTrack] = useState<Track | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([
    { role: 'assistant', content: GENESIS_OPENING },
  ])
  const [agentDraft, setAgentDraft] = useState<Partial<Mandate>>({})
  const chat = useGenesisChat()
  // What the data registry actually has registered — never a hard-coded list,
  // so a source Lane C adds becomes grantable here with no change. Request #19.
  const available = useGenesisSources()

  async function send(text: string) {
    const next: ChatMessage[] = [...messages, { role: 'user', content: text }]
    setMessages(next)

    const result = await chat
      .mutateAsync({ messages: next, draft: agentDraft, available })
      .catch(() => null)
    if (!result) {
      setMessages([
        ...next,
        {
          role: 'assistant',
          content: 'The model is currently unreachable. Resend that message to retry.',
        },
      ])
      return
    }

    setMessages([...next, { role: 'assistant', content: result.data.reply }])
    if (result.data.mandate_draft) {
      setAgentDraft((previous) => ({ ...previous, ...result.data.mandate_draft }))
    }
  }

  return (
    <div className="space-y-6">
      <header>
        {/* The chosen route becomes the page title rather than sitting under a
            generic one. "Create a vault" is what the chooser is for, and once a
            route is picked it is answered — leaving it above the route name put
            two headings on the page competing to say where the reader is, and
            the more specific one was the smaller of the two. The nav still says
            "Create a vault", which is where that label belongs. */}
        <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-2">
          <h1 className="text-xl font-semibold tracking-tight text-ink sm:text-2xl">
            {track === null ? 'Create a vault' : TRACK_TITLES[track]}
          </h1>
          {track !== null ? (
            <button
              type="button"
              onClick={() => setTrack(null)}
              className="text-xs text-muted underline-offset-4 transition-colors hover:text-ink hover:underline"
            >
              ← Choose a different route
            </button>
          ) : null}
        </div>

        {/* Two routes, not three. The standard-mandate track loaded a preset
            for you to read and then deploy, which is the archetype track with
            the model swapped out for a fixed file: same promise, same click,
            and a reader had to hold both descriptions in mind to tell them
            apart. The archetype route is the one that survives, since it is the
            only one of the two that produces a mandate written for the vault
            rather than copied into it. */}
        {track === null ? (
          <ol className="mt-5 grid gap-4 sm:grid-cols-2">
            <TrackCard index={1} title={TRACK_TITLES.agent} onSelect={() => setTrack('agent')}>
              Describe the vault&apos;s objective in plain language. Scipio translates it into an
              operating mandate: hard constraints, permitted data sources, permitted venues.
              Deployment locks the mandate on chain, and the agent executes against it with no
              further instruction.
            </TrackCard>
            <TrackCard
              index={2}
              title={TRACK_TITLES.archetype}
              onSelect={() => setTrack('archetype')}
            >
              Not a template: each archetype is a set of <em>bounds</em>. One click asks the model
              to write a fresh mandate inside them, checks it against those bounds, and deploys.
              Two selections of the same card produce two genuinely different vaults.
            </TrackCard>
          </ol>
        ) : null}
      </header>

      {track !== null ? <ModeNotice /> : null}

      {track === 'agent' ? (
        <>
          {/* The guide the agent track opens on. Every strip below is a menu of
              what exists, not a control. Saying so here is the point: a reader
              who does not know the grants are made in the chat will hunt for
              checkboxes that were never there. */}
          <section className="rounded border border-agent/20 bg-agent/[0.03] px-4 py-3.5">
            <h2 className="text-sm font-semibold text-ink">
              How to create your Scipio Agent Curated Vault
            </h2>
            <p className="mt-1.5 text-xs leading-relaxed text-muted">
              You build the mandate by talking or typing. Name what you want in the conversation and
              it becomes part of the mandate. Anything you do not grant, the agent cannot use, and
              once deployed none of it can be revisited.
            </p>

            <p className="mt-2.5 text-xs leading-relaxed text-muted">These three are required:</p>

            <ul className="mt-1.5 space-y-1 text-xs leading-relaxed text-muted">
              <li>
                <strong className="text-ink">Asset universe.</strong> Which tokens the vault is
                permitted to hold.
              </li>
              <li>
                <strong className="text-ink">Data sources.</strong> What it may consult to form a
                thesis.
              </li>
              <li>
                <strong className="text-ink">Execution venues.</strong> Where a trade is actually
                placed.
              </li>
            </ul>

            <p className="mt-2.5 text-xs leading-relaxed text-muted">
              <strong className="text-ink">Then define your strategy parameters</strong>, for
              example:
            </p>

            {/* The six are the actual fields of `constraints` on the mandate, so
                the examples cannot drift from what the schema will accept. */}
            <ul className="mt-1.5 space-y-1 text-xs leading-relaxed text-muted">
              <li>a cash floor held in reserve</li>
              <li>a ceiling on the share of the book held in any one position</li>
              <li>a slippage limit in basis points</li>
              <li>a cooldown between rebalances</li>
              <li>a cap on actions per cycle</li>
              <li>the drift band a holding must breach before it is rebalanced</li>
            </ul>

            <p className="mt-2.5 text-xs leading-relaxed text-muted">
              Any further parameter may be specified in the conversation.
            </p>
          </section>

          {/* The three selection parameters, in the order a mandate is built:
              what it may hold, then what it may read, then where it may trade. */}
          <AssetUniverse />

          <UniverseStrip available={available} />

          <VenueStrip />

          {/* The three strips above are menus of what exists; this is where the
              mandate is actually written. It was the only part of the page
              without a heading, so the conversation read as a continuation of
              the venue list rather than as the step that consumes all three.
              Same rule and weight as `AssetUniverse`, `UniverseStrip` and
              `VenueStrip`, so the four read as one sequence. */}
          <section>
            <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 border-b border-line pb-2">
              <h2 className="text-sm font-semibold text-ink">Curation Agent Genesis</h2>
              <span className="text-2xs text-faint">the mandate is written here</span>
            </div>

            <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]">
              <ChatPanel
                messages={messages}
                pending={chat.isPending}
                onSend={(text) => void send(text)}
                suggestions={suggestionsFor(messages, agentDraft)}
              />

              <div className="space-y-4">
                <MandateDraft draft={agentDraft} available={available} />
                <DeployPanel draft={agentDraft} />
              </div>
            </div>
          </section>
        </>
      ) : null}

      {track === 'archetype' ? (
        <>
          {/* The guide the archetype track opens on. It has one job the other
              two guides do not: saying that nobody reads the mandate before it
              goes on chain. That is the honest description of a one-click
              deploy, and the reason the envelope check is not optional. */}
          <section className="rounded border border-agent/20 bg-agent/[0.03] px-4 py-3.5">
            <h2 className="text-sm font-semibold text-ink">How an archetype deploy works</h2>
            <p className="mt-1.5 text-xs leading-relaxed text-muted">
              There is no conversation and no form. An archetype is a set of bounds, not a saved
              strategy, and the model writes a new mandate inside those bounds on every click.
            </p>

            <p className="mt-2.5 text-xs leading-relaxed text-muted">What happens when you click:</p>

            <ul className="mt-1.5 space-y-1 text-xs leading-relaxed text-muted">
              <li>
                <strong className="text-ink">The model writes a mandate</strong> inside the
                archetype&apos;s asset, venue and parameter bounds.
              </li>
              <li>
                <strong className="text-ink">It is checked against those bounds.</strong> One that
                escapes them is regenerated, never deployed. No party reviews it before deployment,
                so this check stands in for review.
              </li>
              <li>
                <strong className="text-ink">It deploys</strong> and is recorded against your
                address, so it appears under your vaults on the home page immediately.
              </li>
            </ul>

            <p className="mt-2.5 text-xs leading-relaxed text-muted">
              Two selections of the same card produce two different vaults. Once deployed the
              mandate is locked and only the agent may amend it.
            </p>
          </section>

          <ArchetypeCards />
        </>
      ) : null}
    </div>
  )
}

function TrackCard({
  index,
  title,
  onSelect,
  children,
}: {
  index: number
  title: string
  onSelect: () => void
  children: React.ReactNode
}) {
  return (
    <li>
      <button
        type="button"
        onClick={onSelect}
        className={cn(
          'flex h-full w-full flex-col rounded border border-line bg-raised/40 px-4 py-3 text-left transition-colors',
          'hover:border-agent/40 hover:bg-agent/[0.04]',
          'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-agent/50',
        )}
      >
        <div className="flex items-baseline gap-2">
          <span className="font-mono text-2xs font-semibold text-agent">{index}</span>
          <h2 className="text-sm font-semibold text-ink">{title}</h2>
        </div>
        <p className="mt-1.5 text-xs leading-relaxed text-muted">{children}</p>
        <span className="mt-3 text-2xs font-medium text-agent">Choose this →</span>
      </button>
    </li>
  )
}

