'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { readContract, waitForTransactionReceipt, writeContract } from '@wagmi/core'
import { maxUint256 } from 'viem'
import { erc20Abi, erc4626Abi } from './abis'
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

export type VaultPosition = {
  assetAddress: `0x${string}`
  assetSymbol: string
  assetDecimals: number
  shareDecimals: number
  walletAssets: bigint
  allowance: bigint
  shares: bigint
  sharesInAssets: bigint
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

      const [assetSymbol, assetDecimals, walletAssets, allowance, sharesInAssets] = await Promise.all([
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
      ])

      return {
        assetAddress,
        assetSymbol,
        assetDecimals: Number(assetDecimals),
        shareDecimals: Number(shareDecimals),
        walletAssets,
        allowance,
        shares,
        sharesInAssets,
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

  return { approve, deposit, redeem }
}

export { maxUint256 }
