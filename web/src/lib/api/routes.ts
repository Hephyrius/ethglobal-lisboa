import { z } from 'zod'
import {
  AgentAction,
  GenesisChatRequest,
  GenesisChatResponse,
  GenesisFinalizeRequest,
  GenesisFinalizeResponse,
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

export const routes = {
  genesisChat: () => '/genesis/chat',
  genesisFinalize: () => '/genesis/finalize',
  vaultState: (address: string) => `/vault/${address}/state`,
  vaultDecisions: (address: string, limit = 20) => `/vault/${address}/decisions?limit=${limit}`,
  vaultTick: (address: string) => `/vault/${address}/tick`,
} as const

export const schemas = {
  genesisChat: { request: GenesisChatRequest, response: GenesisChatResponse },
  genesisFinalize: { request: GenesisFinalizeRequest, response: GenesisFinalizeResponse },
  vaultState: { response: VaultState },
  vaultDecisions: { response: AgentActionList },
  vaultTick: { response: AgentAction },
} as const
