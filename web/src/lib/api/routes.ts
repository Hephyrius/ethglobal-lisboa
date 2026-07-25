import { z } from 'zod'
import {
  AgentAction,
  GenesisChatRequest,
  GenesisChatResponse,
  GenesisFinalizeRequest,
  GenesisFinalizeResponse,
  Mandate,
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

export const routes = {
  genesisChat: () => '/genesis/chat',
  genesisFinalize: () => '/genesis/finalize',
  genesisSources: () => '/genesis/sources',
  vaultState: (address: string) => `/vault/${address}/state`,
  vaultMandate: (address: string) => `/vault/${address}/mandate`,
  vaultDecisions: (address: string, limit = 20) => `/vault/${address}/decisions?limit=${limit}`,
  vaultTick: (address: string) => `/vault/${address}/tick`,
  health: () => '/health',
} as const

export const schemas = {
  genesisChat: { request: GenesisChatRequest, response: GenesisChatResponse },
  genesisFinalize: { request: GenesisFinalizeRequest, response: GenesisFinalizeResponse },
  vaultState: { response: VaultState },
  vaultMandate: { response: Mandate },
  vaultDecisions: { response: AgentActionList },
  vaultTick: { response: AgentAction },
  health: { response: AgentHealth },
} as const
