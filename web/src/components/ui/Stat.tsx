import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'

export function Stat({
  label,
  value,
  sub,
  tone,
  className,
}: {
  label: string
  value: ReactNode
  sub?: ReactNode
  tone?: 'default' | 'agent' | 'ok'
  className?: string
}) {
  return (
    <div className={cn('min-w-0', className)}>
      <div className="label">{label}</div>
      <div
        className={cn(
          'tabular mt-1.5 truncate text-xl font-semibold',
          tone === 'agent' ? 'text-agent' : tone === 'ok' ? 'text-ok' : 'text-ink',
        )}
      >
        {value}
      </div>
      {sub ? <div className="mt-0.5 truncate text-xs text-muted">{sub}</div> : null}
    </div>
  )
}

export function StatRow({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cn('grid grid-cols-2 gap-x-6 gap-y-5 sm:grid-cols-4', className)}>{children}</div>
  )
}
