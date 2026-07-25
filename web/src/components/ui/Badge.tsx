import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'

export type BadgeTone = 'neutral' | 'agent' | 'data' | 'ok' | 'warn' | 'bad'

/**
 * Squared chips rather than pills. Pill-shaped tags read as consumer crypto;
 * a tight rectangle reads as a data label, which is what these are.
 */
const TONES: Record<BadgeTone, string> = {
  neutral: 'border-line-bright bg-raised text-muted',
  agent: 'border-agent/25 bg-agent/[0.07] text-agent',
  data: 'border-data/25 bg-data/[0.07] text-data',
  ok: 'border-ok/25 bg-ok/[0.07] text-ok',
  warn: 'border-warn/25 bg-warn/[0.07] text-warn',
  bad: 'border-bad/25 bg-bad/[0.07] text-bad',
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
        'inline-flex items-center gap-1.5 rounded border px-1.5 py-0.5 text-2xs font-medium tracking-wide',
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
