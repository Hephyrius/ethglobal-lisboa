'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  getBytecode,
  readContract,
  simulateContract,
  waitForTransactionReceipt,
  writeContract,
} from '@wagmi/core'
import { maxUint256 } from 'viem'
import { erc20Abi, erc4626Abi, pausableVaultAbi } from './abis'
import { readShareDecimals } from './vault-state'
import { wagmiConfig } from './wagmi'

/**
 * On-chain reads and writes for the deposit/withdraw panel.
 *
 * These talk to the *standard* ERC-4626 surface, not to anything Lane A
 * invented, which is why this works before `contracts/out/**` is published.
 * Everything is driven through React Query rather than wagmi's own hooks — see
 * `wagmi.ts` for why the `wagmi` React package is not installed.
 *
 * Reads are expected to fail when no vault is deployed at the address yet. That
 * is a normal state during the build, not an error to hide: the panel reports it
 * plainly instead of rendering zeroes that look like a funded, empty vault.
 */

/**
 * Share decimals, read from the vault.
 *
 * Never assumed: OZ's `_decimalsOffset()` makes shares 18-decimal over a
 * 6-decimal asset in this deployment, so the two scales differ by 1e12 and
 * guessing wrong misprints every derived figure by that factor.
 */
export function useShareDecimals(vault: `0x${string}`) {
  return useQuery({
    queryKey: ['share-decimals', vault],
    queryFn: () => readShareDecimals(vault),
    retry: false,
    staleTime: Number.POSITIVE_INFINITY,
    enabled: Boolean(vault),
  })
}

/**
 * Does a contract actually exist at this address on the configured RPC?
 *
 * Anvil holds fork state in memory, so restarting it destroys every deployed
 * vault while addresses live on in `deployments/base-fork.json`, in this
 * browser's localStorage, and in any URL someone bookmarked. The symptom is
 * listed in the runbook as "vault address 404s", and without this check the
 * page just quietly falls back to fixtures — honest, because the badge says
 * FIXTURES, but it does not tell you *why*, which is the thing that costs
 * twenty minutes at 3am.
 *
 * Distinguishes "no code here" from "cannot reach the node": only a successful
 * read that comes back empty means the vault is gone.
 */
export function useVaultExists(vault: `0x${string}`) {
  return useQuery({
    queryKey: ['vault-exists', vault],
    enabled: Boolean(vault),
    retry: false,
    staleTime: 30_000,
    queryFn: async (): Promise<boolean> => {
      const bytecode = await getBytecode(wagmiConfig, { address: vault })
      return Boolean(bytecode && bytecode !== '0x')
    },
  })
}

export type VaultPosition = {
  assetAddress: `0x${string}`
  assetSymbol: string
  assetDecimals: number
  shareDecimals: number
  walletAssets: bigint
  allowance: bigint
  shares: bigint
  sharesInAssets: bigint
  /** Base asset actually sitting in the vault — what a redemption can be paid from. */
  vaultLiquid: bigint
  /**
   * Shares the vault can pay *right now*, which is not the same as the shares
   * the holder owns.
   *
   * Lane A's request #76, measured on their side: `totalAssets()` 15,000 against
   * 9,000 liquid after the agent rotates USDC→WETH, so a holder whose shares are
   * worth 10,000 cannot redeem them. `maxWithdraw()` and `previewRedeem()` both
   * report the **claim**, not what is payable, and the revert surfaces from the
   * ERC-20 rather than the vault — so on screen an illiquid vault is
   * indistinguishable from a broken one.
   *
   * The value is therefore `min(shares, convertToShares(vaultLiquid))`, and it is
   * asked of the chain rather than derived from a share-price ratio: the two
   * share scales differ by 1e12 in this deployment (#81), and this is exactly
   * the kind of arithmetic where that silently produces a plausible number.
   */
  payableShares: bigint
}

export function useVaultPosition(vault: `0x${string}`, account?: `0x${string}`) {
  return useQuery({
    queryKey: ['vault-position', vault, account],
    enabled: Boolean(vault && account),
    retry: false,
    staleTime: 8_000,
    queryFn: async (): Promise<VaultPosition> => {
      if (!account) throw new Error('No account')

      const [assetAddress, shareDecimals, shares] = await Promise.all([
        readContract(wagmiConfig, { address: vault, abi: erc4626Abi, functionName: 'asset' }),
        readContract(wagmiConfig, { address: vault, abi: erc4626Abi, functionName: 'decimals' }),
        readContract(wagmiConfig, {
          address: vault,
          abi: erc4626Abi,
          functionName: 'balanceOf',
          args: [account],
        }),
      ])

      const [assetSymbol, assetDecimals, walletAssets, allowance, sharesInAssets, vaultLiquid] =
        await Promise.all([
          readContract(wagmiConfig, { address: assetAddress, abi: erc20Abi, functionName: 'symbol' }),
          readContract(wagmiConfig, { address: assetAddress, abi: erc20Abi, functionName: 'decimals' }),
          readContract(wagmiConfig, {
            address: assetAddress,
            abi: erc20Abi,
            functionName: 'balanceOf',
            args: [account],
          }),
          readContract(wagmiConfig, {
            address: assetAddress,
            abi: erc20Abi,
            functionName: 'allowance',
            args: [account, vault],
          }),
          readContract(wagmiConfig, {
            address: vault,
            abi: erc4626Abi,
            functionName: 'convertToAssets',
            args: [shares],
          }),
          // The vault's own base-asset balance — #76. This is the number a
          // redemption is actually paid out of.
          readContract(wagmiConfig, {
            address: assetAddress,
            abi: erc20Abi,
            functionName: 'balanceOf',
            args: [vault],
          }),
        ])

      // One extra call rather than dividing locally, deliberately. Converting
      // liquidity to shares by hand means picking a share scale, and the two in
      // this deployment differ by 1e12 — the vault's own `convertToShares` is
      // the only source that cannot be wrong about its own offset.
      const liquidInShares = await readContract(wagmiConfig, {
        address: vault,
        abi: erc4626Abi,
        functionName: 'convertToShares',
        args: [vaultLiquid],
      })

      return {
        assetAddress,
        assetSymbol,
        assetDecimals: Number(assetDecimals),
        shareDecimals: Number(shareDecimals),
        walletAssets,
        allowance,
        shares,
        sharesInAssets,
        vaultLiquid,
        payableShares: shares < liquidInShares ? shares : liquidInShares,
      }
    },
  })
}

/**
 * Approve, deposit and redeem, each waiting for its receipt before the UI moves
 * on. Waiting matters: on a fork the next block is instant, and returning
 * before the receipt would let the balance refetch race the state change and
 * show a stale number right after a successful deposit.
 */
export function useVaultActions(vault: `0x${string}`, account?: `0x${string}`) {
  const queryClient = useQueryClient()

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['vault-position', vault, account] })
    void queryClient.invalidateQueries({ queryKey: ['vault-state', vault] })
  }

  const approve = useMutation({
    mutationFn: async ({ token, amount }: { token: `0x${string}`; amount: bigint }) => {
      const hash = await writeContract(wagmiConfig, {
        address: token,
        abi: erc20Abi,
        functionName: 'approve',
        // Exact-amount approval rather than unlimited: this is a brand-new,
        // unaudited vault contract and a hackathon demo. An infinite approval
        // would be the convenient default and the wrong example to set.
        args: [vault, amount],
      })
      return waitForTransactionReceipt(wagmiConfig, { hash })
    },
    onSuccess: refresh,
  })

  const deposit = useMutation({
    mutationFn: async (assets: bigint) => {
      if (!account) throw new Error('Connect a wallet first')
      const hash = await writeContract(wagmiConfig, {
        address: vault,
        abi: erc4626Abi,
        functionName: 'deposit',
        args: [assets, account],
      })
      return waitForTransactionReceipt(wagmiConfig, { hash })
    },
    onSuccess: refresh,
  })

  const redeem = useMutation({
    mutationFn: async (shares: bigint) => {
      if (!account) throw new Error('Connect a wallet first')
      const hash = await writeContract(wagmiConfig, {
        address: vault,
        abi: erc4626Abi,
        functionName: 'redeem',
        args: [shares, account, account],
      })
      return waitForTransactionReceipt(wagmiConfig, { hash })
    },
    onSuccess: refresh,
  })

  /**
   * The in-kind exit — Lane A's §A2b, and the only redemption that is
   * unconditionally payable.
   *
   * Ordinary `redeem` pays in the base asset, so it is capped by what the vault
   * holds in that asset (#76). `redeemInKind` pays a pro-rata slice of *every*
   * token instead: no oracle, no venue, no unwind to wait for. Worse UX, and a
   * strictly better guarantee — which is the right trade for an emergency exit
   * and the reason the paused banner can honestly say nobody is trapped.
   *
   * Simulated before it is signed. Two different things can make this revert —
   * the vault is not paused, or it predates §A2b and has no such selector — and
   * simulating tells the holder which without spending gas to find out. A UI
   * that offers an exit and then reverts is worse than one that never offered
   * it, because it looks like the exit is broken rather than unavailable.
   */
  const redeemInKind = useMutation({
    mutationFn: async (shares: bigint) => {
      if (!account) throw new Error('Connect a wallet first')
      const { request } = await simulateContract(wagmiConfig, {
        address: vault,
        abi: pausableVaultAbi,
        functionName: 'redeemInKind',
        args: [shares, account, account],
        account,
      })
      const hash = await writeContract(wagmiConfig, request)
      return waitForTransactionReceipt(wagmiConfig, { hash })
    },
    onSuccess: refresh,
  })

  return { approve, deposit, redeem, redeemInKind }
}

export { maxUint256 }
