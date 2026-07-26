'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { AgentAction, VaultState } from '@curator/schema'
import { apiFetch, apiFetchStrict, postJson, FIXTURES_FORCED, type Sourced } from './client'
import { fixtureDecisions, fixtureTick, fixtureVaultState } from './fixtures'
import { routes, schemas } from './routes'
import { useReportMode } from './mode-context'
import { readChainVaultState } from '@/lib/chain/vault-state'

/**
 * React Query bindings for the three vault routes. Each returns a `Sourced<T>`
 * so the caller always knows whether it is looking at live data, and reports
 * that into the page-wide mode aggregate.
 */

const VAULT_STATE_REFETCH_MS = 12_000
const DECISIONS_REFETCH_MS = 15_000

/** A whole vault read is several round trips; generous, but never unbounded. */
const CHAIN_READ_TIMEOUT_MS = 8_000

/**
 * Reject rather than hang. Every rung of the fallback ladder has to be able to
 * *fail* for the next one to be reachable at all.
 */
function withTimeout<T>(promise: Promise<T>, ms: number): Promise<T> {
  return Promise.race([
    promise,
    new Promise<never>((_, reject) =>
      setTimeout(() => reject(new Error(`chain read exceeded ${ms}ms`)), ms),
    ),
  ])
}

/**
 * Vault state, down a three-rung ladder: **agent API → the chain → fixtures.**
 *
 * The middle rung matters. Lane B's `/vault/{addr}/state` is itself only
 * reading the ERC-4626 contract, so when that service is down there is no
 * reason to drop all the way to invented numbers — total assets, share price
 * and balances are one `eth_call` away and they are real. Only what the
 * contract cannot know (decision history, the mandate behind `mandate_hash`)
 * still needs a fixture.
 */
export function useVaultState(address: string) {
  const query = useQuery({
    queryKey: ['vault-state', address],
    queryFn: async (): Promise<Sourced<VaultState>> => {
      if (FIXTURES_FORCED) {
        return { data: fixtureVaultState(address), mode: 'fixture', note: 'NEXT_PUBLIC_FIXTURES=1' }
      }

      let apiFailure: string
      try {
        const data = await apiFetchStrict({
          path: routes.vaultState(address),
          schema: schemas.vaultState.response,
        })
        return { data, mode: 'live' }
      } catch (error) {
        apiFailure = error instanceof Error ? error.message : 'agent API unavailable'
      }

      try {
        // Re-validated through the frozen schema rather than trusted: the same
        // bar every other source has to clear.
        //
        // Bounded, because an unbounded read here is worse than no read: a
        // wedged or very slow RPC leaves this promise pending, the query never
        // settles, and the dashboard sits on its loading skeleton forever
        // rather than falling through to the fixtures that exist precisely for
        // this case. Found while rendering the page under a fast-forwarded
        // clock, which is exactly the shape of a hung node.
        const onChain = schemas.vaultState.response.parse(
          await withTimeout(readChainVaultState(address as `0x${string}`), CHAIN_READ_TIMEOUT_MS),
        )
        return {
          data: onChain,
          mode: 'chain',
          note: `${apiFailure}, vault state read directly from the contract instead`,
        }
      } catch {
        return { data: fixtureVaultState(address), mode: 'fixture', note: apiFailure }
      }
    },
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
