'use client'

import { useState } from 'react'
import type { Mandate } from '@curator/schema'
import { ChatPanel } from '@/components/genesis/ChatPanel'
import { MandateDraft } from '@/components/genesis/MandateDraft'
import { DeployPanel } from '@/components/genesis/DeployPanel'
import { PresetCards } from '@/components/genesis/PresetCards'
import { ArchetypeCards } from '@/components/genesis/ArchetypeCards'
import { UniverseStrip } from '@/components/genesis/UniverseStrip'
import { AssetUniverse } from '@/components/genesis/AssetUniverse'
import { VenueStrip } from '@/components/venues/VenueStrip'
import { suggestionsFor } from '@/lib/mandate/suggestions'
import { ModeNotice } from '@/components/ui/ModeBadge'
import { useGenesisChat, useGenesisSources } from '@/lib/api/genesis-queries'
import { GENESIS_OPENING, type ChatMessage } from '@/lib/api/genesis-sim'
import { cn } from '@/lib/cn'

type Track = 'agent' | 'standard' | 'archetype'

/** The chooser's label for each track, in one place so the card and the
 *  `ChosenTrack` banner cannot drift apart. */
const TRACK_TITLES: Record<Track, string> = {
  agent: 'Deploy a Scipio Agent',
  standard: 'Deploy a standard mandate',
  archetype: 'Deploy from an archetype',
}

/**
 * Create a vault by one of two mutually exclusive routes.
 *
 * ## The page is a chooser, not a menu of everything
 *
 * Both routes used to be on screen at once — preset cards, the universe strips
 * and the conversation, stacked. A reader had no way to tell which controls
 * belonged to the path they had picked. Now nothing renders until a track is
 * chosen, and choosing one hides the other *including its description card*:
 * "nothing about the standard mandate is viewable" is not satisfied by a
 * dimmed card that still explains the standard mandate.
 *
 * ## Why each track owns its own draft
 *
 * A single shared `draft` was survivable when both routes were visible and a
 * preset was framed as a starting point you then amended by talking. With the
 * tracks exclusive it is a trap: load "Conservative", switch across, and the
 * conversation would open on top of a mandate the user cannot see the origin
 * of — or worse, deploy carrying fields from a route they abandoned. Separate
 * drafts mean switching tracks is free and neither one loses its work.
 *
 * The agent draft still accumulates rather than being re-derived each turn:
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
  const [presetDraft, setPresetDraft] = useState<Partial<Mandate>>({})
  const [presetKey, setPresetKey] = useState<string>()
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
          content: 'I could not reach the model just now. Say that again and I will retry.',
        },
      ])
      return
    }

    setMessages([...next, { role: 'assistant', content: result.data.reply }])
    if (result.data.mandate_draft) {
      setAgentDraft((previous) => ({ ...previous, ...result.data.mandate_draft }))
    }
  }

  /**
   * Load a whole archetype into the standard-mandate track.
   *
   * This used to announce itself in the chat transcript, so that the mandate
   * panel filling with values nobody typed did not read as the app deciding for
   * them. That instrument no longer works: on this track the transcript is not
   * on screen at all, so the announcement would be written somewhere the reader
   * cannot see. The mandate panel appears directly beneath the cards instead,
   * which shows the fill where the click happened.
   */
  function loadPreset(mandate: Mandate, key: string) {
    setPresetDraft(mandate)
    setPresetKey(key)
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-xl font-semibold tracking-tight text-ink sm:text-2xl">Create a vault</h1>

        {track === null ? (
          <ol className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <TrackCard index={1} title={TRACK_TITLES.agent} onSelect={() => setTrack('agent')}>
              Describe the vault&apos;s objective in plain language. Alesia translates it into an
              operating mandate: hard constraints, permitted data sources, permitted venues.
              Deployment locks the mandate on chain, and the agent executes against it with no
              further instruction.
            </TrackCard>
            <TrackCard
              index={2}
              title={TRACK_TITLES.standard}
              onSelect={() => setTrack('standard')}
            >
              Preset risk profiles with every parameter already configured. Conservative for tight
              exposure limits, Aggressive for wide ones. You review the finished mandate before it
              deploys. Every vault is a distinct instance, owned by the address that deploys it.
            </TrackCard>
            {/* The third route is neither of the other two, which is why it is
                its own track rather than a button inside the standard one. The
                others load or compose a mandate you then read; this one asks
                the model to write a fresh one and deploys it in the same click.
                Mixing "review, then deploy" with "deploys on click" inside one
                track is exactly the ambiguity the chooser exists to remove. */}
            <TrackCard
              index={3}
              title={TRACK_TITLES.archetype}
              onSelect={() => setTrack('archetype')}
            >
              Not a template: each archetype is a set of <em>bounds</em>. One click asks the model
              to write a fresh mandate inside them, checks it against those bounds, and deploys.
              Click the same card twice and you get two genuinely different vaults.
            </TrackCard>
          </ol>
        ) : (
          <ChosenTrack title={TRACK_TITLES[track]} onClear={() => setTrack(null)} />
        )}
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
              How to create your Scipio agent-curated vault
            </h2>
            <p className="mt-1.5 text-xs leading-relaxed text-muted">
              You build the mandate by talking. Name what you want in the conversation and it
              becomes part of the mandate. Anything you do not grant, the agent cannot use, and once
              deployed none of it can be revisited.
            </p>

            <p className="mt-2.5 text-xs leading-relaxed text-muted">These three are required:</p>

            <ul className="mt-1.5 space-y-1 text-xs leading-relaxed text-muted">
              <li>
                <strong className="text-ink">Asset universe.</strong> Which tokens the vault is
                allowed to hold at all.
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
              Then define your strategy parameters, for example:
            </p>

            {/* The six are the actual fields of `constraints` on the mandate, so
                the examples cannot drift from what the schema will accept. */}
            <ul className="mt-1.5 space-y-1 text-xs leading-relaxed text-muted">
              <li>a cash floor held back in reserve</li>
              <li>a ceiling on how much may sit in any one position</li>
              <li>a slippage limit in basis points</li>
              <li>a cooldown between rebalances</li>
              <li>a cap on actions per cycle</li>
              <li>the drift band a holding has to breach before it is rebalanced</li>
            </ul>

            <p className="mt-2.5 text-xs leading-relaxed text-muted">Get creative.</p>
          </section>

          {/* The three selection parameters, in the order a mandate is built:
              what it may hold, then what it may read, then where it may trade. */}
          <AssetUniverse />

          <UniverseStrip available={available} />

          <VenueStrip />

          <div className="grid gap-4 lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]">
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
        </>
      ) : null}

      {track === 'standard' ? (
        <>
          {/* The counterpart to the agent guide, and it carries more weight than
              a mirror image would suggest: choosing this track replaces the pair
              of chooser cards, so the description that used to introduce the
              presets is no longer on screen. This is now the only place that
              says what the track is. Deliberately does not restate the profiles
              themselves, for the reason `presets.ts` gives: their headlines come
              from `index.json` so a preset whose limits change cannot leave a
              stale description behind. Naming them here would reintroduce that. */}
          <section className="rounded border border-agent/20 bg-agent/[0.03] px-4 py-3.5">
            <h2 className="text-sm font-semibold text-ink">How to deploy a standard mandate</h2>
            <p className="mt-1.5 text-xs leading-relaxed text-muted">
              Every parameter is already configured. You are choosing a finished mandate rather than
              writing one, so there is no conversation and nothing to grant. What you pick is what
              deploys.
            </p>

            <p className="mt-2.5 text-xs leading-relaxed text-muted">Three steps:</p>

            <ul className="mt-1.5 space-y-1 text-xs leading-relaxed text-muted">
              <li>
                <strong className="text-ink">Pick a risk tier below.</strong> Conservative and
                Aggressive set how much room the agent has to move.
              </li>
              <li>
                <strong className="text-ink">Check the mandate underneath.</strong> It carries the
                same fields an agent-built vault would, filled in for you.
              </li>
              <li>
                <strong className="text-ink">Click Deploy vault.</strong>
              </li>
            </ul>

            <p className="mt-2.5 text-xs leading-relaxed text-muted">
              Every vault is a distinct instance, owned by the address that deploys it. Once
              deployed the mandate is locked and only the agent may amend it.
            </p>
          </section>

          {/* The Randomized tier is not backed by a preset and never will be —
              it describes drawing allocations at deploy, which is what the
              archetype track actually does. Handing it the track switch turns a
              "Coming soon" placeholder into the route it was always describing. */}
          <PresetCards
            onSelect={loadPreset}
            selectedKey={presetKey}
            onRandomized={() => setTrack('archetype')}
          />

          {/* Held back until a card is chosen. An empty mandate panel and a
              dead deploy button occupy the space a reader is scanning for the
              result of their click. */}
          {presetKey ? (
            <div className="grid gap-4 lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]">
              <MandateDraft draft={presetDraft} available={available} />
              <DeployPanel draft={presetDraft} />
            </div>
          ) : null}
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
                escapes them is regenerated, never deployed — nobody reads it first, so the check is
                what stands in for review.
              </li>
              <li>
                <strong className="text-ink">It deploys</strong> and is recorded against your
                address, so it appears under your vaults on the home page straight away.
              </li>
            </ul>

            <p className="mt-2.5 text-xs leading-relaxed text-muted">
              Two clicks on one card give two different vaults. Once deployed the mandate is locked
              and only the agent may amend it.
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

/**
 * What stands in for the pair once a track is chosen. It names the route the
 * reader is on and offers the way back — without restating the other option,
 * which is the whole reason the cards were replaced rather than dimmed.
 */
function ChosenTrack({ title, onClear }: { title: string; onClear: () => void }) {
  return (
    <div className="mt-5 flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-line pb-2">
      <h2 className="text-sm font-semibold text-ink">{title}</h2>
      <button
        type="button"
        onClick={onClear}
        className="text-xs text-muted underline-offset-4 transition-colors hover:text-ink hover:underline"
      >
        ← Choose a different route
      </button>
    </div>
  )
}
