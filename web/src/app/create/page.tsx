'use client'

import { useState } from 'react'
import type { Mandate } from '@curator/schema'
import { ChatPanel } from '@/components/genesis/ChatPanel'
import { MandateDraft } from '@/components/genesis/MandateDraft'
import { DeployPanel } from '@/components/genesis/DeployPanel'
import { PresetCards } from '@/components/genesis/PresetCards'
import { UniverseStrip } from '@/components/genesis/UniverseStrip'
import { VenueStrip } from '@/components/venues/VenueStrip'
import { suggestionsFor } from '@/lib/mandate/suggestions'
import { ModeNotice } from '@/components/ui/ModeBadge'
import { useGenesisChat, useGenesisSources } from '@/lib/api/genesis-queries'
import { GENESIS_OPENING, type ChatMessage } from '@/lib/api/genesis-sim'

/**
 * Genesis: co-design a strategy in natural language, watch it become a mandate,
 * deploy it.
 *
 * The draft is accumulated here rather than re-derived from the reply each turn,
 * because `mandate_draft` is a *partial* — each turn contributes the fields it
 * learned about and leaves the rest alone. Merging on top of what we already
 * have is what lets the mandate build up across the conversation instead of
 * resetting to whatever the last turn happened to mention.
 */
export default function CreatePage() {
  const [messages, setMessages] = useState<ChatMessage[]>([
    { role: 'assistant', content: GENESIS_OPENING },
  ])
  const [draft, setDraft] = useState<Partial<Mandate>>({})
  const [presetKey, setPresetKey] = useState<string>()
  const chat = useGenesisChat()
  // What the data registry actually has registered — never a hard-coded list,
  // so a source Lane C adds becomes grantable here with no change. Request #19.
  const available = useGenesisSources()

  async function send(text: string) {
    const next: ChatMessage[] = [...messages, { role: 'user', content: text }]
    setMessages(next)

    const result = await chat.mutateAsync({ messages: next, draft, available }).catch(() => null)
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
      setDraft((previous) => ({ ...previous, ...result.data.mandate_draft }))
    }
  }

  /**
   * Load a whole archetype, then say so in the transcript.
   *
   * The announcement is not decoration: without it the mandate panel silently
   * fills with values the user did not type, which reads as the app deciding
   * for them. Saying it in the curator's own voice keeps the conversation the
   * place where the mandate is agreed.
   */
  function loadPreset(mandate: Mandate, key: string) {
    setDraft(mandate)
    setPresetKey(key)
    setMessages((previous) => [
      ...previous,
      {
        role: 'assistant',
        content: `Loaded **${mandate.name}** as a starting point — it is on the right, complete and deployable as it stands. Tell me what you would change: a different cash floor, another asset, a tighter slippage ceiling. Anything you do not mention stays as it is.`,
      },
    ])
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-xl font-semibold tracking-tight text-ink sm:text-2xl">
          Design a strategy, or deploy a template mandate.
        </h1>

        {/* The two paths, in the order they appear below: the preset cards, then
            the conversation. Numbered because they are alternatives a reader
            chooses between, not steps taken in sequence. */}
        <ol className="mt-5 grid gap-4 sm:grid-cols-2">
          <Path index={1} title="Deploy a standard mandate">
            Three preset risk profiles with parameters already configured. Conservative for tight
            exposure limits, Aggressive for wide ones, Randomised for allocations drawn at
            deployment. Every vault is a distinct instance, owned by the address that deploys it.
          </Path>
          <Path index={2} title="Deploy a Scipio Agent">
            Describe the vault&apos;s objective in plain language. Alesia translates it into an
            operating mandate: hard constraints, permitted data sources, permitted venues.
            Deployment locks the mandate on chain, and the agent executes against it with no further
            instruction.
          </Path>
        </ol>
      </header>

      <ModeNotice />

      <PresetCards onSelect={loadPreset} selectedKey={presetKey} />

      <UniverseStrip available={available} />

      <VenueStrip />

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]">
        <ChatPanel
          messages={messages}
          pending={chat.isPending}
          onSend={(text) => void send(text)}
          suggestions={suggestionsFor(messages, draft)}
        />

        <div className="space-y-4">
          <MandateDraft draft={draft} available={available} />
          <DeployPanel draft={draft} />
        </div>
      </div>
    </div>
  )
}

function Path({
  index,
  title,
  children,
}: {
  index: number
  title: string
  children: React.ReactNode
}) {
  return (
    <li className="rounded border border-line bg-raised/40 px-4 py-3">
      <div className="flex items-baseline gap-2">
        <span className="font-mono text-2xs font-semibold text-agent">{index}</span>
        <h2 className="text-sm font-semibold text-ink">{title}</h2>
      </div>
      <p className="mt-1.5 text-xs leading-relaxed text-muted">{children}</p>
    </li>
  )
}
