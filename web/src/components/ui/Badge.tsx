import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'

export type BadgeTone = 'neutral' | 'agent' | 'data' | 'ok' | 'warn' | 'bad'

const TONES: Record<BadgeTone, string> = {
  neutral: 'border-line-bright bg-raised text-muted',
  agent: 'border-agent/30 bg-agent/10 text-agent',
  data: 'border-data/30 bg-data/10 text-data',
  ok: 'border-ok/30 bg-ok/10 text-ok',
  warn: 'border-warn/30 bg-warn/10 text-warn',
  bad: 'border-bad/30 bg-bad/10 text-bad',
}

export function Badge({
  children,
  tone = 'neutral',
  className,
  title,
}: {
  children: ReactNode
  tone?: BadgeTone
  className?: string
  title?: string
}) {
  return (
    <span
      title={title}
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-2xs font-medium tracking-wide',
        TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  )
}

export function Dot({ tone = 'neutral', pulse }: { tone?: BadgeTone; pulse?: boolean }) {
  const colors: Record<BadgeTone, string> = {
    neutral: 'bg-muted',
    agent: 'bg-agent',
    data: 'bg-data',
    ok: 'bg-ok',
    warn: 'bg-warn',
    bad: 'bg-bad',
  }
  return (
    <span
      className={cn('h-1.5 w-1.5 shrink-0 rounded-full', colors[tone], pulse && 'animate-pulse-soft')}
    />
  )
}
