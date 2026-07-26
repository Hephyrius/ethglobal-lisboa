'use client'

import type { Mandate } from '@curator/schema'
import { MANDATE_PRESETS } from '@/lib/mandate/presets'
import { cn } from '@/lib/cn'

/**
 * Three broad risk tiers to start from.
 *
 * ## Why this shows tiers rather than the presets themselves
 *
 * The cards used to render each preset's own name, headline and tradeoff
 * straight out of `packages/schema/presets/index.json`, which is why they read
 * "Lend USDC only" and "Gives up every source of return except lending". That
 * is the right level of detail for a mandate you are about to amend by talking,
 * and the wrong level for picking a risk posture in one click.
 *
 * So the surface is now a risk framework: Conservative, Aggressive, Randomized.
 * It is deliberately broad because the framework behind it does not exist yet,
 * and a placeholder that promises three tiers is more honest than three
 * specific strategies presented as if they were tiers.
 *
 * ## The mapping, and the one that is not wired
 *
 * A tier resolves to a preset by `risk_posture`, never by index, so this cannot
 * silently bind to the wrong mandate if the preset set changes. Two of the three
 * resolve today: `conservative` and `aggressive` both exist and deploy real,
 * schema-valid mandates.
 *
 * **Randomized resolves to no preset, and now routes to the archetype track
 * instead of sitting disabled.** The original reasoning still stands and is
 * why it is *not* bound to a posture: no mandate in the preset set draws its
 * allocations at deployment, and pointing the label at the nearest available
 * one would deploy a vault that is nothing of the sort — a false claim about
 * on-chain behaviour, not a copy imprecision.
 *
 * What changed is that something now genuinely does what the label says. An
 * *archetype* asks the model to write a fresh mandate inside a set of bounds on
 * every click, so "allocations drawn at deployment" is a description of it
 * rather than a promise nothing keeps. The tier hands off to that track rather
 * than loading anything here, which is why it takes a separate callback and not
 * a preset.
 *
 * `onRandomized` is optional: without it the tier stays disabled and reads
 * "Coming soon" exactly as before, so this component remains correct on a page
 * with no archetype track to reach.
 *
 * Nothing here is edited in `packages/schema/`: that package is Lane F's under
 * the Wave 2 rules, and none of this needs it. The presets are read exactly as
 * they ship; only the presentation changed.
 */

type Tier = {
  key: string
  label: string
  blurb: string
  /** Matched against a preset's `risk_posture`. Null means no preset backs it. */
  posture: 'conservative' | 'aggressive' | null
  /**
   * Handed to the archetype track instead of loading a preset.
   *
   * Only `randomized` sets this, and it is what turned that tier from a
   * placeholder into a working control — see the note at the top of the file.
   */
  routesToArchetype?: true
}

const TIERS: Tier[] = [
  {
    key: 'conservative',
    label: 'Conservative',
    blurb: 'The tightest exposure limits. Least room to move, and least to lose by moving.',
    posture: 'conservative',
  },
  {
    key: 'aggressive',
    label: 'Aggressive',
    blurb: 'The widest exposure limits. More room to act on a thesis, and more to lose acting on it.',
    posture: 'aggressive',
  },
  {
    key: 'randomized',
    label: 'Randomized',
    blurb: 'Allocations drawn at deployment rather than chosen.',
    posture: null,
    routesToArchetype: true,
  },
]

export function PresetCards({
  onSelect,
  selectedKey,
  onRandomized,
}: {
  onSelect: (mandate: Mandate, key: string) => void
  selectedKey?: string
  /**
   * Where the Randomized tier goes. Omitted, the tier stays disabled and reads
   * "Coming soon" exactly as before — so this component is still correct on a
   * page that has no archetype track to send anyone to.
   */
  onRandomized?: () => void
}) {
  return (
    <div className="grid gap-3 md:grid-cols-3">
      {TIERS.map((tier) => {
        const preset = tier.posture
          ? MANDATE_PRESETS.find((entry) => entry.mandate.risk_posture === tier.posture)
          : undefined
        const routes = tier.routesToArchetype === true && onRandomized !== undefined
        const isSelected = preset !== undefined && preset.key === selectedKey
        const isReady = preset !== undefined || routes

        return (
          <button
            key={tier.key}
            type="button"
            disabled={!isReady}
            onClick={() => {
              if (routes) return onRandomized?.()
              if (preset) return onSelect(preset.mandate, preset.key)
            }}
            aria-pressed={preset !== undefined ? isSelected : undefined}
            className={cn(
              'flex flex-col rounded border bg-surface p-4 text-left transition-colors',
              'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-agent/50',
              !isReady
                ? 'cursor-not-allowed border-dashed border-line text-faint'
                : isSelected
                  ? 'border-agent/50 ring-1 ring-agent/25'
                  : 'border-line hover:border-line-bright hover:bg-raised',
            )}
          >
            <span
              className={cn('text-sm font-semibold', isReady ? 'text-ink' : 'text-muted')}
            >
              {tier.label}
            </span>

            <span className="mt-2 text-xs leading-relaxed text-muted">{tier.blurb}</span>

            {/* Plain text rather than a badge: the tiers carry no tags, and the
                one thing worth saying is where the click goes — or that it does
                not go anywhere yet. */}
            {!isReady ? (
              <span className="mt-3 text-2xs text-faint">Coming soon</span>
            ) : routes ? (
              <span className="mt-3 text-2xs text-agent">Deploy from an archetype →</span>
            ) : isSelected ? (
              <span className="mt-3 text-2xs text-agent">Loaded</span>
            ) : null}
          </button>
        )
      })}
    </div>
  )
}
