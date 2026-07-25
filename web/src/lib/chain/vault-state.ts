import type { VaultState } from '@curator/schema'
import { readContract } from '@wagmi/core'
import { erc20Abi, erc4626Abi } from './abis'
import { KNOWN_TOKENS, asAddress } from './deployments'
import { wagmiConfig } from './wagmi'

/**
 * Build a `VaultState` by reading the vault contract directly.
 *
 * This is the middle rung of the fallback ladder: agent API → chain → fixtures.
 * It exists because the vault's own numbers are *on the chain*, and Lane B's
 * `/vault/{addr}/state` is itself just reading them. When that service is down
 * there is no reason to drop all the way to invented data — total assets, share
 * price and balances are all one `eth_call` away, and they are real.
 *
 * What it cannot reconstruct is anything the agent knows and the contract does
 * not: the decision history, and the mandate behind `mandate_hash`. Those still
 * fall back to fixtures, and the mode badge still reports the page as degraded
 * because part of it is.
 */

/** Tokens to check balances for. The vault is sole custodian, so `balanceOf` is the whole picture. */
function candidateTokens(assetAddress: `0x${string}`): `0x${string}`[] {
  const known = [asAddress(KNOWN_TOKENS.USDC), asAddress(KNOWN_TOKENS.WETH)].filter(
    (token): token is `0x${string}` => token !== null,
  )
  return known.some((token) => token.toLowerCase() === assetAddress.toLowerCase())
    ? known
    : [assetAddress, ...known]
}

export async function readChainVaultState(vault: `0x${string}`): Promise<VaultState> {
  const [assetAddress, shareDecimals, totalAssets, totalSupply] = await Promise.all([
    readContract(wagmiConfig, { address: vault, abi: erc4626Abi, functionName: 'asset' }),
    readContract(wagmiConfig, { address: vault, abi: erc4626Abi, functionName: 'decimals' }),
    readContract(wagmiConfig, { address: vault, abi: erc4626Abi, functionName: 'totalAssets' }),
    readContract(wagmiConfig, { address: vault, abi: erc4626Abi, functionName: 'totalSupply' }),
  ])

  const assetDecimals = Number(
    await readContract(wagmiConfig, {
      address: assetAddress,
      abi: erc20Abi,
      functionName: 'decimals',
    }),
  )

  const holdings = await Promise.all(
    candidateTokens(assetAddress).map(async (token) => {
      try {
        const [balance, symbol, decimals] = await Promise.all([
          readContract(wagmiConfig, {
            address: token,
            abi: erc20Abi,
            functionName: 'balanceOf',
            args: [vault],
          }),
          readContract(wagmiConfig, { address: token, abi: erc20Abi, functionName: 'symbol' }),
          readContract(wagmiConfig, { address: token, abi: erc20Abi, functionName: 'decimals' }),
        ])
        if (balance === 0n) return null
        return {
          token,
          symbol,
          balance: balance.toString(),
          decimals: Number(decimals),
          // `committed_to_venue` is an agent-side fact — the contract cannot
          // know a balance backs an Aqua strategy. Null is honest here; the
          // API path is the one that can fill it in.
          committed_to_venue: null,
        }
      } catch {
        // A token that is not an ERC-20 at this address on this chain. Skip it
        // rather than failing the whole read.
        return null
      }
    }),
  )

  return {
    address: vault,
    asset: assetAddress,
    asset_decimals: assetDecimals,
    total_assets: totalAssets.toString(),
    total_supply: totalSupply.toString(),
    // Reported as assets-per-whole-share in *asset* decimals — the value
    // `convertToAssets(1 whole share)` actually returns. See VaultStats for why
    // the display derives its own figure rather than trusting a scale.
    share_price:
      totalSupply === 0n
        ? undefined
        : (
            await readContract(wagmiConfig, {
              address: vault,
              abi: erc4626Abi,
              functionName: 'convertToAssets',
              args: [10n ** BigInt(shareDecimals)],
            })
          ).toString(),
    holdings: holdings.filter((holding): holding is NonNullable<typeof holding> => holding !== null),
    aqua_strategies: [],
    paused: false,
  }
}

/** Share decimals differ from asset decimals under OZ's decimals offset. Read, never assume. */
export async function readShareDecimals(vault: `0x${string}`): Promise<number> {
  const decimals = await readContract(wagmiConfig, {
    address: vault,
    abi: erc4626Abi,
    functionName: 'decimals',
  })
  return Number(decimals)
}
