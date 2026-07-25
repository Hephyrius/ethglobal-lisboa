import { Archetype, ArchetypeIndex, describeEnvelope, type Archetype as ArchetypeT } from '@curator/schema'

import archetypeIndex from '../../../../packages/schema/archetypes/index.json'
import balancedGrowth from '../../../../packages/schema/archetypes/balanced-growth.json'
import conservativeIncome from '../../../../packages/schema/archetypes/conservative-income.json'
import opportunistic from '../../../../packages/schema/archetypes/opportunistic.json'

/**
 * The archetype envelopes, read from Lane F's `packages/schema/archetypes/`.
 *
 * ## An archetype is not a preset, and the difference is the whole feature
 *
 * `presets/` are fixed mandates that seed the curator conversation — same file
 * every time, a starting point a human then edits. An archetype is **bounds**:
 * one click asks the model for a fresh mandate inside them, no chat and no user
 * input, and two clicks on the same card must produce two different vaults.
 * Both live in this lane and they must never be presented as the same thing.
 *
 * ## Nothing here validates a mandate, on purpose
 *
 * The gate is Lane B's, through `curator_schema.archetypes.check_envelope()`.
 * This module only *describes* an envelope, and the description comes from
 * F's `describeEnvelope()` rather than from sentences typed here — so the bound
 * on the card is generated from the same JSON the gate reads and cannot drift
 * away from what is actually enforced. A card promising a number nobody
 * enforces is exactly the failure that survives until a judge asks.
 */

export type ArchetypeCard = {
  archetype: ArchetypeT
  /** Bound lines, generated from the envelope. Never hand-written. */
  bounds: string[]
}

const BY_KEY: Record<string, unknown> = {
  'conservative-income': conservativeIncome,
  'balanced-growth': balancedGrowth,
  opportunistic,
}

/**
 * Parsed at module load, like the presets and the fixtures: an envelope that is
 * not a valid `Archetype` fails `pnpm build` rather than producing a card that
 * throws when someone clicks it during the demo.
 */
export const ARCHETYPES: ArchetypeCard[] = ArchetypeIndex.parse(archetypeIndex).archetypes.flatMap(
  (entry) => {
    const raw = BY_KEY[entry.key]
    // Listed in the index with no file is a packaging mistake on F's side, not
    // a reason to take the whole page down — the remaining cards still deploy.
    if (!raw) return []
    const archetype = Archetype.parse(raw)
    return [{ archetype, bounds: describeEnvelope(archetype) }]
  },
)

export function archetypeByKey(key: string): ArchetypeCard | undefined {
  return ARCHETYPES.find((card) => card.archetype.key === key)
}
