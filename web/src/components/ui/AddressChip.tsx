'use client'

import { useState } from 'react'
import { addressUrl } from '@/lib/chain/explorer'
import { shortAddress } from '@/lib/format/units'
import { cn } from '@/lib/cn'

/**
 * An address, truncated, copyable, and linked to the explorer only when the
 * explorer actually has it (see lib/chain/explorer.ts — on the fork it does
 * not, and a dead link is worse than none).
 */
export function AddressChip({
  address,
  label,
  className,
  full,
}: {
  address: string
  label?: string
  className?: string
  full?: boolean
}) {
  const href = addressUrl(address)
  const text = full ? address : shortAddress(address)

  return (
    <span className={cn('inline-flex items-center gap-1.5', className)}>
      {label ? <span className="label">{label}</span> : null}
      {href ? (
        <a
          href={href}
          target="_blank"
          rel="noreferrer"
          className="font-mono text-xs text-ink underline decoration-line-bright underline-offset-2 transition-colors hover:decoration-agent"
          title={address}
        >
          {text}
        </a>
      ) : (
        <span className="font-mono text-xs text-ink" title={address}>
          {text}
        </span>
      )}
      <CopyButton value={address} />
    </span>
  )
}

export function CopyButton({ value, className }: { value: string; className?: string }) {
  const [copied, setCopied] = useState(false)

  return (
    <button
      type="button"
      onClick={() => {
        void navigator.clipboard?.writeText(value).then(() => {
          setCopied(true)
          setTimeout(() => setCopied(false), 1200)
        })
      }}
      aria-label={copied ? 'Copied' : 'Copy to clipboard'}
      className={cn(
        'rounded p-0.5 text-faint transition-colors hover:text-ink',
        copied && 'text-ok',
        className,
      )}
    >
      {copied ? (
        <svg width="12" height="12" viewBox="0 0 16 16" fill="none" aria-hidden="true">
          <path
            d="M3 8.5 6.2 11.7 13 5"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      ) : (
        <svg width="12" height="12" viewBox="0 0 16 16" fill="none" aria-hidden="true">
          <rect x="5.6" y="5.6" width="8" height="8" rx="1.6" stroke="currentColor" strokeWidth="1.4" />
          <path
            d="M10.4 3.4a1.6 1.6 0 0 0-1.6-1.6H4a1.6 1.6 0 0 0-1.6 1.6v4.8a1.6 1.6 0 0 0 1.6 1.6"
            stroke="currentColor"
            strokeWidth="1.4"
            strokeLinecap="round"
          />
        </svg>
      )}
    </button>
  )
}
