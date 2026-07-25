'use client'

import { useQuery } from '@tanstack/react-query'
import { readContract } from '@wagmi/core'
import { vaultFactoryAddress } from './deployments'
import { wagmiConfig } from './wagmi'

/**
 * Vaults a wallet *deployed*, which is a different question from vaults it
 * holds shares in.
 *
 * ## Why this cannot be derived from balances
 *
 * The portfolio strip answers ownership by `balanceOf`, and that is the right
 * mechanism for "what am I worth". It cannot see the archetype case at all: a
 * one-click vault is generated and deployed with **no deposit**, so its
 * deployer holds zero shares in it and it is invisible to a balance scan by
 * construction. The two questions need two sources.
 *
 * ## Why the factory view rather than the event
 *
 * Lane A's §A1 makes `VaultCreated`'s indexed `deployer` the source of truth and
 * `vaultsOf` explicitly "optional sugar". Both are written by the same
 * transaction so they cannot disagree, and the view is one `eth_call` against a
 * log scan whose range limits differ per provider. So: the view for the read,
 * and the event remains what an independent indexer would verify it against.
 *
 * ## The distinction this file exists to preserve
 *
 * `vaultsOf` **reverts** on a factory deployed before §A1 — the selector is not
 * there. That is not "this wallet deployed nothing"; it is "this deployment
 * cannot answer the question". Collapsing the two would state, to someone who
 * really did deploy a vault, that they had not — so the two outcomes stay
 * distinct all the way to the UI rather than both becoming an empty array.
 */

const factoryAbi = [
  {
    type: 'function',
    name: 'vaultsOf',
    stateMutability: 'view',
    inputs: [{ name: 'deployer', type: 'address' }],
    outputs: [{ type: 'address[]' }],
  },
] as const

export type DeployedByResult =
  /** The factory answered. The list may legitimately be empty. */
  | { supported: true; vaults: readonly `0x${string}`[] }
  /** The factory predates deployer attribution and cannot answer at all. */
  | { supported: false; vaults: readonly [] }

export function useVaultsDeployedBy(account: `0x${string}` | undefined) {
  const factory = vaultFactoryAddress()

  return useQuery({
    queryKey: ['vaults-deployed-by', factory, account],
    enabled: Boolean(factory && account),
    retry: false,
    staleTime: 15_000,
    queryFn: async (): Promise<DeployedByResult> => {
      if (!factory || !account) throw new Error('No factory or account')
      try {
        const vaults = await readContract(wagmiConfig, {
          address: factory,
          abi: factoryAbi,
          functionName: 'vaultsOf',
          args: [account],
        })
        return { supported: true, vaults }
      } catch {
        // Deliberately not rethrown. A missing selector is a *fact about this
        // deployment*, not a failure to read it, and the caller renders the two
        // differently — an error state here would show a retry button for
        // something no retry can fix.
        return { supported: false, vaults: [] }
      }
    },
  })
}
