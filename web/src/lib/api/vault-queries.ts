'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { AgentAction, VaultState } from '@curator/schema'
import { apiFetch, postJson, type Sourced } from './client'
import { fixtureDecisions, fixtureTick, fixtureVaultState } from './fixtures'
import { routes, schemas } from './routes'
import { useReportMode } from './mode-context'

/**
 * React Query bindings for the three vault routes. Each returns a `Sourced<T>`
 * so the caller always knows whether it is looking at live data, and reports
 * that into the page-wide mode aggregate.
 */

const VAULT_STATE_REFETCH_MS = 12_000
const DECISIONS_REFETCH_MS = 15_000

export function useVaultState(address: string) {
  const query = useQuery({
    queryKey: ['vault-state', address],
    queryFn: (): Promise<Sourced<VaultState>> =>
      apiFetch({
        path: routes.vaultState(address),
        schema: schemas.vaultState.response,
        fallback: () => fixtureVaultState(address),
      }),
    refetchInterval: VAULT_STATE_REFETCH_MS,
    enabled: Boolean(address),
  })

  useReportMode(`vault-state:${address}`, query.data)
  return query
}

export function useVaultDecisions(address: string, limit = 20) {
  const query = useQuery({
    queryKey: ['vault-decisions', address, limit],
    queryFn: (): Promise<Sourced<AgentAction[]>> =>
      apiFetch({
        path: routes.vaultDecisions(address, limit),
        schema: schemas.vaultDecisions.response,
        fallback: () => fixtureDecisions(address),
      }),
    refetchInterval: DECISIONS_REFETCH_MS,
    enabled: Boolean(address),
  })

  useReportMode(`vault-decisions:${address}`, query.data)
  return query
}

/**
 * `POST /vault/{addr}/tick` — asks the agent to run one decision cycle now.
 *
 * This is the demo's trigger, so it falls back like a read rather than failing
 * like a write: a tick does not move user funds, it asks the curator to think.
 * The fallback is still visible through the mode badge, and the new action is
 * prepended to the feed so the causal chain animates in front of the judge.
 */
export function useVaultTick(address: string) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (): Promise<Sourced<AgentAction>> =>
      apiFetch({
        path: routes.vaultTick(address),
        schema: schemas.vaultTick.response,
        init: postJson({}),
        fallback: () => fixtureTick(address),
        // A real tick queries live data sources and runs a local model. That is
        // slow by nature — several seconds at minimum — so the read timeout
        // would abort a perfectly healthy cycle.
        timeoutMs: 120_000,
      }),
    onSuccess: (result) => {
      queryClient.setQueryData(
        ['vault-decisions', address, 20],
        (previous: Sourced<AgentAction[]> | undefined) => {
          if (!previous) return previous
          const withoutDuplicate = previous.data.filter((action) => action.id !== result.data.id)
          return { ...previous, mode: result.mode, note: result.note, data: [result.data, ...withoutDuplicate] }
        },
      )
      void queryClient.invalidateQueries({ queryKey: ['vault-state', address] })
    },
  })
}
