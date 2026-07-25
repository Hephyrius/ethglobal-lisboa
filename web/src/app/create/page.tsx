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
        <p className="label">Genesis</p>
        <h1 className="mt-2 text-xl font-semibold tracking-tight text-ink sm:text-2xl">
          Design the strategy, then hand it over
        </h1>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted">
          Describe what the vault should do. The curator turns it into a mandate — constraints, the
          data sources it may consult, the venues it may use. Deploying crystallises that mandate at
          genesis; from then on the agent runs it alone.
        </p>
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
