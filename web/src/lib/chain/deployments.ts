import deploymentsJson from '../../../../deployments/base-fork.json'

/**
 * Addresses come from `deployments/base-fork.json`, which Lane A's deploy
 * script overwrites — never from a constant in this lane. When Lane A deploys,
 * this app picks the addresses up with no code change, which is the whole point
 * of that file existing.
 *
 * Every field is nullable because the file ships as a shape with nulls in it
 * until Lane A's first deploy lands. The UI has to survive that state, so
 * nothing here throws on a missing address.
 */

type Deployments = {
  chainId: number
  network: string
  rpcUrl: string
  contracts: { VaultFactory: string | null; CuratedVaultImplementation: string | null }
  vaults: Array<string | { address?: string; name?: string }>
  external: Record<string, string | undefined>
  executeAllowlist?: { targets?: string[] }
}

const deployments = deploymentsJson as unknown as Deployments

export const CHAIN_ID = Number(process.env.NEXT_PUBLIC_CHAIN_ID ?? deployments.chainId ?? 8453)

export const KNOWN_TOKENS = {
  USDC: deployments.external?.USDC,
  WETH: deployments.external?.WETH,
} as const

export function vaultFactoryAddress(): `0x${string}` | null {
  return asAddress(deployments.contracts?.VaultFactory)
}

/** Vaults Lane A has deployed, if any. Normalised — the file allows two shapes. */
export function deployedVaults(): Array<{ address: `0x${string}`; name?: string }> {
  const raw = deployments.vaults ?? []
  return raw
    .map((entry) => {
      if (typeof entry === 'string') return { address: asAddress(entry), name: undefined }
      return { address: asAddress(entry.address), name: entry.name }
    })
    .filter((entry): entry is { address: `0x${string}`; name?: string } => entry.address !== null)
}

export function asAddress(value: string | null | undefined): `0x${string}` | null {
  return value && /^0x[a-fA-F0-9]{40}$/.test(value) ? (value as `0x${string}`) : null
}

export function isAddress(value: string | null | undefined): value is `0x${string}` {
  return asAddress(value) !== null
}
