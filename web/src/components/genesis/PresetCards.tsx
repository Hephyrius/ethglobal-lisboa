'use client'

import type { Mandate } from '@curator/schema'
import { Badge } from '@/components/ui/Badge'
import { MANDATE_PRESETS } from '@/lib/mandate/presets'
import { cn } from '@/lib/cn'

/**
 * Three presets to start from, instead of an empty box.
 *
 * Genesis asks a first-time reader to invent an investment mandate from
 * nothing, in a vocabulary they may not have. A preset answers "what does one
 * of these even look like" in one click, and the conversation then becomes
 * *amendment* — which is a far easier thing to do well than composition.
 *
 * **Every card leads with what the preset gives up.** A picker that only lists
 * upside is a sales page; the tradeoff line is the part that makes this a real
 * choice, and it comes from the preset's own metadata rather than from
 * copywriting here, so it cannot go stale when the limits change.
 *
 * ⚠️ These were called "archetypes" until Wave 3, when that word acquired a
 * different and incompatible meaning: an *archetype* is now a set of bounds the
 * model writes a new mandate inside on every click (`ArchetypeCards`), while a
 * *preset* is one fixed mandate loaded verbatim, every time, to be edited by
 * hand. Both appear on this page. One word for two things — one generative and
 * one not — would make the distinction the feature depends on unreadable.
 */
export function PresetCards({
  onSelect,
  selectedKey,
}: {
  onSelect: (mandate: Mandate, key: string) => void
  selectedKey?: string
}) {
  if (MANDATE_PRESETS.length === 0) return null

  return (
    <section>
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 border-b border-line pb-2">
        <h2 className="text-sm font-semibold text-ink">Start from a preset</h2>
        <p className="text-2xs text-faint">
          Loads one fixed mandate, the same every time — then amend it by talking
        </p>
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-3">
        {MANDATE_PRESETS.map((preset) => {
          const isSelected = preset.key === selectedKey
          return (
            <button
              key={preset.key}
              type="button"
              onClick={() => onSelect(preset.mandate, preset.key)}
              aria-pressed={isSelected}
              className={cn(
                'flex flex-col rounded border bg-surface p-4 text-left transition-colors',
                'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-agent/50',
                isSelected
                  ? 'border-agent/50 ring-1 ring-agent/25'
                  : 'border-line hover:border-line-bright hover:bg-raised',
              )}
            >
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-semibold text-ink">{preset.mandate.name}</span>
                {isSelected ? <Badge tone="agent">LOADED</Badge> : null}
              </div>

              <p className="mt-2 text-xs leading-relaxed text-muted">{preset.headline}</p>

              <p className="mt-3 border-t border-line pt-2 text-2xs leading-relaxed text-warn/90">
                <span className="font-medium">Gives up:</span> {preset.tradeoff}
              </p>

              <div className="mt-3 flex flex-wrap items-center gap-1.5">
                <Badge tone="neutral">{preset.mandate.risk_posture}</Badge>
                <Badge tone="neutral">
                  {Math.round(preset.mandate.constraints.min_cash_pct * 100)}% cash floor
                </Badge>
                <Badge tone="neutral">{preset.mandate.constraints.max_slippage_bps} bps</Badge>
                {preset.persona ? <Badge tone="agent">{preset.persona}</Badge> : null}
              </div>
            </button>
          )
        })}
      </div>
    </section>
  )
}
