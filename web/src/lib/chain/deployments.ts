import forkJson from '../../../../deployments/base-fork.json'
import mainnetJson from '../../../../deployments/base-mainnet.json'

/**
 * Addresses come from `deployments/<network>.json`, which Lane A's deploy
 * script overwrites — never from a constant in this lane. When Lane A deploys,
 * this app picks the addresses up with no code change, which is the whole point
 * of that file existing.
 *
 * Every field is nullable because the file ships as a shape with nulls in it
 * until Lane A's first deploy lands. The UI has to survive that state, so
 * nothing here throws on a missing address.
 *
 * ## Why both files are imported rather than one path being computed
 *
 * `import` is static. Bundlers resolve the specifier at build time, so
 * `../../../../deployments/${network}.json` cannot work — there is no runtime
 * at which the choice could be made, and the Python side's `DEPLOYMENTS_FILE`
 * has no equivalent here. Both are imported and one is selected instead, which
 * costs a few kilobytes of JSON and keeps the selection honest.
 *
 * `NEXT_PUBLIC_DEPLOY_NETWORK` is read the same way as every other
 * `NEXT_PUBLIC_*`: **inlined at build time.** Changing the target network needs
 * a rebuild, not a restart. `deploy/Dockerfile.web` passes it as a build arg for
 * exactly that reason.
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

/**
 * Which manifest this build targets. Defaults to the fork, so a plain
 * `pnpm dev` behaves exactly as it always has and nobody has to set anything to
 * work locally.
 *
 * An unrecognised value falls back to the fork rather than throwing. That is the
 * opposite of `Deploy.s.sol`, where an unrecognised `DEPLOY_NETWORK` is treated
 * as a real network so a typo fails *safe* — there, failing safe means "assume
 * production and apply the strict oracle window". Here the only consequence is
 * which addresses render, and a dApp that refuses to build over a typo in an
 * env var is worse than one showing an undeployed state.
 */
const deployments = (
  process.env.NEXT_PUBLIC_DEPLOY_NETWORK === 'base-mainnet' ? mainnetJson : forkJson
) as unknown as Deployments

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

/**
 * The vault `Deploy.s.sol` creates, which is **not a curated vault** and must
 * not be listed as one.
 *
 * Mandates are written only by `POST /genesis/finalize` and the archetype
 * route, so this one has none — `GET /vault/{addr}/mandate` returns 404 and
 * every tick against it fails with *"no mandate stored"*. Its on-chain
 * `mandateHash` matches no mandate that exists anywhere, so one cannot be
 * supplied after the fact either. `tests/e2e/test_slice_wave2.py` says the same
 * thing from the other side: it is a deployment smoke test.
 *
 * Listing it is worse than cosmetic. It renders as a vault a visitor can
 * deposit into, and a deposit there is real money in something that can never
 * act on it.
 */
export function demoVaultAddress(): `0x${string}` | null {
  return asAddress(deployments.demoVault?.address)
}

/** Whether an address is a vault a curator actually runs. */
export function isCuratedVault(address: string): boolean {
  const demo = demoVaultAddress()
  return !demo || demo.toLowerCase() !== address.toLowerCase()
}

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
    // The deploy script's own vault has no mandate and cannot be curated.
    if (!isCuratedVault(address)) return []

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
