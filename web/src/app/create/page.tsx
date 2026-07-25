'use client'

import { useState } from 'react'
import type { Mandate } from '@curator/schema'
import { ChatPanel } from '@/components/genesis/ChatPanel'
import { MandateDraft } from '@/components/genesis/MandateDraft'
import { DeployPanel } from '@/components/genesis/DeployPanel'
import { ModeNotice } from '@/components/ui/ModeBadge'
import { useGenesisChat } from '@/lib/api/genesis-queries'
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
  const chat = useGenesisChat()

  async function send(text: string) {
    const next: ChatMessage[] = [...messages, { role: 'user', content: text }]
    setMessages(next)

    const result = await chat.mutateAsync({ messages: next, draft }).catch(() => null)
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

  return (
    <div className="space-y-6">
      <header>
        <p className="label">Genesis</p>
        <h1 className="mt-2 text-2xl font-semibold tracking-tight text-ink">
          Design the strategy, then hand it over
        </h1>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted">
          Describe what the vault should do. The curator turns it into a mandate — constraints, the
          data sources it may consult, the venues it may use. Deploying crystallises that mandate at
          genesis; from then on the agent runs it alone.
        </p>
      </header>

      <ModeNotice />

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]">
        <ChatPanel messages={messages} pending={chat.isPending} onSend={(text) => void send(text)} />

        <div className="space-y-4">
          <MandateDraft draft={draft} />
          <DeployPanel draft={draft} />
        </div>
      </div>
    </div>
  )
}
