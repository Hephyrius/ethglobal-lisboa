'use client'

import { useEffect, useRef, useState } from 'react'
import type { ChatMessage } from '@/lib/api/genesis-sim'
import { ScipioMark } from '@/components/brand/ScipioMark'
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
  suggestions = [],
}: {
  messages: ChatMessage[]
  pending: boolean
  onSend: (text: string) => void
  /** One-tap replies, so a reader who does not know the vocabulary is never
   *  facing an empty box. See lib/mandate/suggestions.ts. */
  suggestions?: string[]
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
    // On a phone the panel stacks above the mandate draft, so pinning it to
    // viewport height would push the draft — the thing the conversation is
    // producing — entirely below the fold. It takes a bounded height there and
    // only fills the viewport once the two sit side by side.
    <div className="card flex h-[26rem] flex-col sm:h-[32rem] lg:h-[calc(100vh-13rem)] lg:min-h-[32rem]">
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
        {suggestions.length > 0 && !pending ? (
          <div className="scroll-slim -mx-1 mb-2 flex gap-1.5 overflow-x-auto px-1 pb-1">
            {suggestions.map((suggestion) => (
              <button
                key={suggestion}
                type="button"
                onClick={() => onSend(suggestion)}
                title={suggestion}
                className="shrink-0 rounded border border-line bg-raised px-2.5 py-1 text-2xs text-muted transition-colors hover:border-agent/40 hover:text-ink"
              >
                {/* Truncated on a phone, full text on a laptop — the whole
                    sentence is the example, but three of them stacked would
                    push the input off a 375px screen. */}
                <span className="sm:hidden">{truncate(suggestion, 34)}</span>
                <span className="hidden sm:inline">{truncate(suggestion, 64)}</span>
              </button>
            ))}
          </div>
        ) : null}

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
            className="scroll-slim max-h-40 flex-1 resize-none rounded-lg border border-line bg-canvas px-3 py-2 text-sm leading-relaxed text-ink outline-none transition-colors placeholder:text-faint focus:border-agent/50"
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
      {/* The curator gets the mark; the depositor stays a text chip. Giving both
          sides an avatar would flatten the one distinction this transcript has
          to keep obvious — which turns are the agent's own words. */}
      {isUser ? (
        <div className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-sm border border-line-bright bg-raised text-2xs font-medium text-muted">
          You
        </div>
      ) : (
        <ScipioMark className="mt-0.5" />
      )}
      <div
        className={cn(
          'min-w-0 max-w-[88%] break-words rounded-xl px-3.5 py-2.5 text-sm leading-relaxed sm:max-w-[85%]',
          isUser ? 'bg-raised text-ink' : 'border border-line bg-surface text-ink/90',
        )}
      >
        <p className="whitespace-pre-line">{message.content}</p>
      </div>
    </div>
  )
}

/** Suggested replies are whole sentences; the button is not. */
function truncate(text: string, max: number): string {
  return text.length <= max ? text : `${text.slice(0, max - 1).trimEnd()}…`
}
