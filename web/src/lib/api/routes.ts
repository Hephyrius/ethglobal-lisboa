import { z } from 'zod'
import {
  AgentAction,
  GenesisChatRequest,
  GenesisChatResponse,
  GenesisFinalizeRequest,
  GenesisFinalizeResponse,
  Mandate,
  VaultPerformance,
  VaultState,
} from '@curator/schema'

/**
 * The five routes frozen in master build plan §8, implemented by Lane B
 * (`agent/api`) and consumed here. Paths are declared exactly once, in this
 * file, so a route change is a one-line diff rather than a grep.
 *
 * Response schemas come from the zod mirror in packages/schema — this lane
 * never redefines a shape that crosses a lane boundary.
 */

export const API_BASE = (process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000').replace(
  /\/$/,
  '',
)

/** GET /vault/{addr}/decisions returns a bare array. */
export const AgentActionList = z.array(AgentAction)

/**
 * `GET /health` is not part of the Wave 0 freeze — it is Lane B's own endpoint,
 * documented in `agent/README.md`. Declared with `.passthrough()` so fields
 * added on their side never break this one.
 */
export const AgentHealth = z
  .object({
    status: z.enum(['ok', 'degraded']),
    mode: z.enum(['live', 'fixture']),
    data_registry: z.string().optional(),
    venue_registry: z.string().optional(),
    model_backend: z.string().optional(),
    model_reachable: z.boolean().optional(),
  })
  .passthrough()

/**
 * `GET /genesis/sources` — what the data registry actually has registered.
 *
 * Reading this instead of hard-coding a source list is the point: granting a
 * source is a mandate edit, not a code change, so the genesis screen must offer
 * whatever Lane C has registered today. When their Aave adapter binds, `aave`
 * appears here and becomes grantable with no change on this side.
 */
export const GenesisSources = z
  .object({ sources: z.array(z.string()), venues: z.array(z.string()) })
  .passthrough()

/**
 * Lane D's venue capability manifest (cross-lane note #61), as it would arrive
 * over HTTP. `.passthrough()` because D owns the shape and may add fields.
 *
 * `custody` is the load-bearing one and D said so explicitly: `virtual` means
 * the tokens never leave the vault (that *is* the Pattern 1 claim), `claim`
 * means the underlying really moved and the vault holds a receipt token, and
 * `rotational` means no position is held at all. A reader who flattens those
 * three concludes `totalAssets()` is broken when it is exactly right.
 */
export const VenueManifestRow = z
  .object({
    key: z.string(),
    role: z.string().optional(),
    summary: z.string().optional(),
    intents: z.array(z.string()).default([]),
    tokens: z.array(z.string()).default([]),
    custody: z.enum(['virtual', 'claim', 'rotational']).optional(),
    custody_note: z.string().optional(),
    requires: z.array(z.string()).default([]),
    available: z.boolean().default(true),
    unavailable_reason: z.string().nullable().optional(),
  })
  .passthrough()

export const VenueManifest = z.array(VenueManifestRow)

/**
 * `POST /archetypes/{key}/deploy` — Lane B's §B1. Their own endpoint, not part
 * of the Wave 0 freeze, so `.passthrough()`.
 *
 * The only field this lane *needs* is the vault address; everything else makes
 * the result legible. `mandate` matters more than it looks: the whole claim of
 * the archetype flow is that a model wrote a fresh strategy rather than a
 * template being copied, and showing the mandate it actually produced is how a
 * viewer checks that two clicks really did diverge.
 *
 * `attempts` is requested rather than assumed to be 1. An envelope violation
 * means regenerate-never-deploy, so a deploy that took three tries is evidence
 * the gate is load-bearing — the same reason rejected decisions are rendered in
 * the feed instead of hidden.
 */
export const ArchetypeDeployResponse = z
  .object({
    vault: z.string(),
    mandate: Mandate.optional(),
    mandate_hash: z.string().optional(),
    tx_hash: z.string().optional(),
    attempts: z.number().int().min(1).optional(),
    /** Populated when a generation escaped the envelope and was regenerated. */
    rejected: z
      .array(z.object({ reason: z.string() }).passthrough())
      .default([]),
  })
  .passthrough()

export const routes = {
  genesisChat: () => '/genesis/chat',
  genesisFinalize: () => '/genesis/finalize',
  genesisSources: () => '/genesis/sources',
  /** Requested from Lane B in note #68; degrades cleanly until it exists. */
  venues: () => '/venues',
  /** Lane B §B1. One call generates, envelope-checks, regenerates and deploys. */
  archetypeDeploy: (key: string) => `/archetypes/${key}/deploy`,
  vaultState: (address: string) => `/vault/${address}/state`,
  vaultMandate: (address: string) => `/vault/${address}/mandate`,
  vaultDecisions: (address: string, limit = 20) => `/vault/${address}/decisions?limit=${limit}`,
  vaultTick: (address: string) => `/vault/${address}/tick`,
  vaultPerformance: (address: string, window = 'all') =>
    `/vault/${address}/performance?window=${window}`,
  health: () => '/health',
} as const

export const schemas = {
  genesisChat: { request: GenesisChatRequest, response: GenesisChatResponse },
  genesisFinalize: { request: GenesisFinalizeRequest, response: GenesisFinalizeResponse },
  vaultState: { response: VaultState },
  vaultMandate: { response: Mandate },
  vaultDecisions: { response: AgentActionList },
  vaultTick: { response: AgentAction },
  vaultPerformance: { response: VaultPerformance },
  health: { response: AgentHealth },
  genesisSources: { response: GenesisSources },
  venues: { response: VenueManifest },
  archetypeDeploy: { response: ArchetypeDeployResponse },
} as const
