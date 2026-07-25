import { Mandate, type Mandate as MandateT } from '@curator/schema'

import presetIndex from '../../../../packages/schema/presets/index.json'
import balancedTwoAsset from '../../../../packages/schema/presets/balanced-two-asset.json'
import conservativeIncome from '../../../../packages/schema/presets/conservative-income.json'
import opportunistic from '../../../../packages/schema/presets/opportunistic.json'

/**
 * The mandate archetypes, read from Lane F's frozen preset set.
 *
 * Both the genesis chat (Lane B, in its prompt) and these buttons read the
 * *same* files, which is the point: the mandate the model recommends and the
 * one a click loads cannot drift apart. Nothing here restates a preset's
 * contents — the headline and tradeoff come from `index.json` too, so a preset
 * whose limits change does not leave a stale description on a card.
 *
 * Parsed through the zod mirror at module load, like the fixtures. The
 * conformance test already validates them on the Python side; doing it here
 * means a preset that is not a deployable `Mandate` fails `pnpm build` rather
 * than producing a button that errors when clicked.
 */

export type MandatePreset = {
  key: string
  headline: string
  tradeoff: string
  /** Named persona, when the archetype ships with one. */
  persona?: string
  mandate: MandateT
}

const BY_KEY: Record<string, unknown> = {
  'balanced-two-asset': balancedTwoAsset,
  'conservative-income': conservativeIncome,
  opportunistic,
}

type IndexEntry = { key: string; headline: string; tradeoff: string; persona?: string }

export const MANDATE_PRESETS: MandatePreset[] = (presetIndex.presets as IndexEntry[]).flatMap(
  (entry) => {
    const raw = BY_KEY[entry.key]
    // A preset listed in the index with no file is a packaging mistake, not a
    // reason to crash the genesis page — the chat still works without buttons.
    if (!raw) return []
    return [
      {
        key: entry.key,
        headline: entry.headline,
        tradeoff: entry.tradeoff,
        persona: entry.persona,
        mandate: Mandate.parse(raw),
      },
    ]
  },
)
