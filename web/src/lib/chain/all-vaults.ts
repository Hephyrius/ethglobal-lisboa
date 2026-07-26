'use client'

import { useQuery } from '@tanstack/react-query'
import { readContract, readContracts } from '@wagmi/core'
import { vaultFactoryAddress } from './deployments'
import { wagmiConfig } from './wagmi'

/**
 * Every vault the factory has ever created, read from the chain.
 *
 * ## Why the explorer needs this and the other three sources are not enough
 *
 * `useKnownVaults` assembles its list from localStorage (vaults *this browser*
 * deployed), `deployments/base-fork.json` (whatever the deploy script happened
 * to record) and a fixture. None of those can see a vault created by anyone
 * else — and the two flows that now create most vaults, genesis and one-click
 * archetypes, both mint through the factory without touching that JSON file.
 * So a browse page built on those three shows a reader their own vaults and
 * calls it an explorer.
 *
 * `VaultFactory.vaults()` is the authoritative list: the factory records every
 * clone it creates, so this is the only source that answers "what exists"
 * rather than "what did I happen to hear about".
 *
 * ## Why a view rather than scanning logs
 *
 * Same reasoning as `deployed-by.ts`: one `eth_call` against a log scan whose
 * block-range limits differ per provider — and this fork already refuses
 * `eth_getLogs` over more than 10,000 blocks, which is what drove the chunking
 * in the performance backfill. The view cannot disagree with the events; both
 * are written by the same transaction.
 *
 * ## Failure is not emptiness
 *
 * A factory too old to expose `vaults()`, or an unreachable node, must not read
 * as "no vaults exist" — that would tell someone looking at a populated
 * deployment that it is empty. The two outcomes stay distinct to the caller,
 * which is the same distinction `deployed-by.ts` preserves for `vaultsOf`.
 */

const factoryAbi = [
  {
    type: 'function',
    name: 'vaults',
    stateMutability: 'view',
    inputs: [],
    outputs: [{ type: 'address[]' }],
  },
] as const

export type AllVaultsResult =
  /** The factory answered. An empty list is a real answer. */
  | { supported: true; vaults: readonly `0x${string}`[]; names?: readonly (string | null)[] }
  /** No factory address, an unreachable node, or a factory without the view. */
  | { supported: false; vaults: readonly []; names?: readonly [] }

/** Minimal ERC-20 `name()` — the vault's own, written at genesis from the mandate. */
const nameAbi = [
  { type: 'function', name: 'name', stateMutability: 'view', inputs: [], outputs: [{ type: 'string' }] },
] as const

export function useAllVaults() {
  const factory = vaultFactoryAddress()

  return useQuery<AllVaultsResult>({
    queryKey: ['all-vaults', factory],
    enabled: Boolean(factory),
    // A browse page is worth re-reading fairly often: a vault deployed in
    // another tab, or by the archetype flow moments ago, should appear.
    staleTime: 15_000,
    retry: false,
    queryFn: async () => {
      if (!factory) return { supported: false, vaults: [] }
      try {
        const vaults = await readContract(wagmiConfig, {
          address: factory,
          abi: factoryAbi,
          functionName: 'vaults',
        })

        // Every vault's own `name()`, in ONE multicall rather than N requests.
        //
        // The list previously rendered every chain-discovered vault as the
        // literal string "Vault", on the reasoning that the chain does not
        // carry the mandate text. True, but beside the point: `createVault`
        // writes the mandate's name into the ERC-20 `name()`, so the chain has
        // "Curated Split-Yield USDC Allocator" and the UI was showing "Vault".
        //
        // Batched because the alternative is one request per vault, and a
        // public RPC rate-limits a fan-out like that — the same shape that made
        // the API return placeholder token symbols earlier today. A failed name
        // degrades to null and the caller falls back; it never fails the list.
        let names: readonly (string | null)[] = []
        try {
          const results = await readContracts(wagmiConfig, {
            allowFailure: true,
            contracts: vaults.map((address) => ({
              address,
              abi: nameAbi,
              functionName: 'name' as const,
            })),
          })
          names = results.map((r) => (r.status === 'success' ? (r.result as string) : null))
        } catch {
          names = []
        }

        return { supported: true, vaults, names }
      } catch {
        // Deliberately not rethrown: the explorer still has its other three
        // sources, and a browse page that renders nothing because one read
        // failed is worse than one that renders what it can.
        return { supported: false, vaults: [] }
      }
    },
  })
}
