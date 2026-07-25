'use client'

import { useEffect, useRef, useState } from 'react'
import type { ChatMessage } from '@/lib/api/genesis-sim'
import { Button, Spinner } from '@/components/ui/Button'
import { cn } from '@/lib/cn'

/**
 * The genesis conversation.
 *
 * Kept as one continuous chat rather than a multi-step form on purpose: the
 * narrative beat is *a conversation produces a mandate*, and watching the
 * mandate assemble itself beside the chat is the whole point. A wizard would
 * make the same data collection feel like filling in a form, which is exactly
 * the experience this replaces.
 */
export function ChatPanel({
  messages,
  pending,
  onSend,
}: {
  messages: ChatMessage[]
  pending: boolean
  onSend: (text: string) => void
}) {
  const [draft, setDraft] = useState('')
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages.length, pending])

  function submit() {
    const text = draft.trim()
    if (!text || pending) return
    onSend(text)
    setDraft('')
  }

  return (
    <div className="card flex h-[calc(100vh-11rem)] min-h-[32rem] flex-col">
      <div className="scroll-slim flex-1 space-y-5 overflow-y-auto px-5 py-5">
        {messages.map((message, index) => (
          <Message key={index} message={message} />
        ))}

        {pending ? (
          <div className="flex items-center gap-2 text-xs text-faint">
            <Spinner className="text-agent" />
            The curator is thinking…
          </div>
        ) : null}

        <div ref={endRef} />
      </div>

      <div className="border-t border-line p-3">
        <div className="flex items-end gap-2">
          <textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault()
                submit()
              }
            }}
            rows={2}
            placeholder="Describe what this vault should do…"
            className="scroll-slim max-h-40 flex-1 resize-none rounded-lg border border-line bg-base px-3 py-2 text-sm leading-relaxed text-ink outline-none transition-colors placeholder:text-faint focus:border-agent/50"
          />
          <Button variant="primary" onClick={submit} disabled={!draft.trim() || pending}>
            Send
          </Button>
        </div>
        <p className="mt-2 text-2xs text-faint">
          Enter to send · Shift+Enter for a new line
        </p>
      </div>
    </div>
  )
}

function Message({ message }: { message: ChatMessage }) {
  const isUser = message.role === 'user'

  return (
    <div className={cn('flex gap-3', isUser && 'flex-row-reverse')}>
      <div
        className={cn(
          'mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-sm text-2xs font-medium',
          isUser
            ? 'border border-line-bright bg-raised text-muted'
            : 'bg-agent font-serif font-semibold text-white',
        )}
      >
        {isUser ? 'You' : 'C'}
      </div>
      <div
        className={cn(
          'max-w-[85%] rounded-xl px-3.5 py-2.5 text-sm leading-relaxed',
          isUser ? 'bg-raised text-ink' : 'border border-line bg-surface text-ink/90',
        )}
      >
        <p className="whitespace-pre-line">{message.content}</p>
      </div>
    </div>
  )
}
