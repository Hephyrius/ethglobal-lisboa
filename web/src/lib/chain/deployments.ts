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
  /** Lane A's deploy script records the demo vault separately, with its symbol. */
  demoVault?: { address?: string; symbol?: string }
  external: Record<string, string | undefined>
  /**
   * Every token the factory can value, written by `scripts/expand-universe.sh`.
   * Distinct from `external`, which mixes tokens with routers, feeds and Permit2
   * — everything in here is a token by construction, so no consumer has to guess.
   */
  assets?: Record<string, string | undefined>
  executeAllowlist?: { targets?: string[] }
}

const deployments = deploymentsJson as unknown as Deployments

export const CHAIN_ID = Number(process.env.NEXT_PUBLIC_CHAIN_ID ?? deployments.chainId ?? 8453)

/**
 * Every token this deployment can hold, keyed by symbol.
 *
 * Derived, not enumerated. This was previously a two-key object naming USDC and
 * WETH by hand, which capped the asset-universe panel at two entries no matter
 * what the factory had registered — six further assets (cbBTC, DAI, AERO, both
 * aTokens and a 4626 share) were live on chain and invisible in the product.
 *
 * `assets` falls back to the two `external` entries so a manifest written by an
 * older deploy — one that predates the block — still yields something rather
 * than an empty universe.
 */
export const KNOWN_TOKENS: Record<string, string | undefined> =
  deployments.assets && Object.keys(deployments.assets).length > 0
    ? deployments.assets
    : { USDC: deployments.external?.USDC, WETH: deployments.external?.WETH }

export function vaultFactoryAddress(): `0x${string}` | null {
  return asAddress(deployments.contracts?.VaultFactory)
}

/** Vaults Lane A has deployed, if any. Normalised — the file allows two shapes. */
export function deployedVaults(): Array<{ address: `0x${string}`; name?: string }> {
  const raw = deployments.vaults ?? []
  const demo = deployments.demoVault

  return raw.flatMap((entry) => {
    const address = asAddress(typeof entry === 'string' ? entry : entry.address)
    if (!address) return []

    const named = typeof entry === 'string' ? undefined : entry.name
    // `vaults` is a bare address list, but the deploy script also records the
    // demo vault with its share symbol — worth using so the list reads
    // "cUSDC vault" rather than a generic label.
    const fromDemo =
      demo?.symbol && asAddress(demo.address)?.toLowerCase() === address.toLowerCase()
        ? `${demo.symbol} vault`
        : undefined

    return [{ address, name: named ?? fromDemo }]
  })
}

export function asAddress(value: string | null | undefined): `0x${string}` | null {
  return value && /^0x[a-fA-F0-9]{40}$/.test(value) ? (value as `0x${string}`) : null
}

export function isAddress(value: string | null | undefined): value is `0x${string}` {
  return asAddress(value) !== null
}
