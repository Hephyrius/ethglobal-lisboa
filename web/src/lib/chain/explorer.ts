import { CHAIN_ID } from './deployments'

/**
 * Block-explorer links, chain-aware.
 *
 * The anvil fork reports chain id 8453 exactly like Base mainnet, so a naive
 * BaseScan link built from the chain id resolves to a transaction that does not
 * exist. A dead explorer link opened in front of a judge is worse than no link
 * at all — it reads as a fabricated transaction. So links are suppressed
 * whenever we are pointed at a local node, and the hash is shown as copyable
 * text with the network stated instead.
 */

const RPC_URL = process.env.NEXT_PUBLIC_RPC_URL ?? ''

const LOCAL_HOSTS = ['localhost', '127.0.0.1', '0.0.0.0', 'host.docker.internal']

export const isForkNetwork: boolean = (() => {
  if (!RPC_URL) return false
  try {
    return LOCAL_HOSTS.includes(new URL(RPC_URL).hostname)
  } catch {
    return false
  }
})()

export const networkLabel: string = isForkNetwork ? 'Base fork (anvil)' : `Base mainnet`

const EXPLORERS: Record<number, string> = {
  8453: 'https://basescan.org',
}

function explorerBase(): string | null {
  if (isForkNetwork) return null
  return EXPLORERS[CHAIN_ID] ?? null
}

export function txUrl(hash: string): string | null {
  const base = explorerBase()
  return base ? `${base}/tx/${hash}` : null
}

export function addressUrl(address: string): string | null {
  const base = explorerBase()
  return base ? `${base}/address/${address}` : null
}
