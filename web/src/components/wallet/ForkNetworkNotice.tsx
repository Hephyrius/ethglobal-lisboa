'use client'

import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/Button'
import { useAccount } from '@/lib/chain/account'

/**
 * One click to point the wallet at the local fork.
 *
 * ## The problem this exists for
 *
 * The fork keeps **chain id 8453**, the same id as real Base — deliberately, so
 * every address, ABI and signature behaves exactly as it would in production.
 * The cost is that a wallet cannot tell the two apart. MetaMask sees "Base",
 * uses Base's *public mainnet* RPC, and a deposit is broadcast to a chain where
 * the vault does not exist. Nothing warns you: the network name is right, the
 * chain id is right, and the transaction simply fails or, worse, is signed
 * against real state.
 *
 * `wallet_addEthereumChain` with the loopback RPC is the fix. Modern MetaMask
 * holds several endpoints per chain and prompts to add this one; on a wallet
 * that refuses a duplicate chain id, the fallback is the manual instruction
 * below, which is why the address is rendered as copyable text and not only
 * bound to the button.
 *
 * ## Why it cannot appear in production
 *
 * It renders only when the configured RPC is a **loopback address**, which is
 * provable from the URL rather than from a mode flag someone can set wrongly.
 * A deployed build has a public RPC, so this component returns null there and
 * no "switch your wallet to a local node" affordance can ever reach a user with
 * real funds.
 */

const RPC_URL = process.env.NEXT_PUBLIC_RPC_URL ?? ''

/** True only for 127.0.0.0/8, ::1 and `localhost`. */
function isLoopback(url: string): boolean {
  try {
    const { hostname } = new URL(url)
    return hostname === 'localhost' || hostname === '::1' || /^127(\.\d{1,3}){3}$/.test(hostname)
  } catch {
    return false
  }
}

const FORK_PARAMS = {
  chainId: '0x2105', // 8453
  chainName: 'Base fork (anvil)',
  nativeCurrency: { name: 'Ether', symbol: 'ETH', decimals: 18 },
  rpcUrls: [RPC_URL],
  blockExplorerUrls: ['https://basescan.org'],
}

type Injected = {
  request: (args: { method: string; params?: unknown[] }) => Promise<unknown>
}

export function ForkNetworkNotice({ className }: { className?: string }) {
  const { isConnected } = useAccount()
  // The RPC is inlined at build time, but `window.ethereum` is not knowable
  // during SSR — so mounting gates the render rather than producing markup the
  // client then contradicts.
  const [mounted, setMounted] = useState(false)
  const [state, setState] = useState<'idle' | 'pending' | 'done' | 'failed'>('idle')
  const [detail, setDetail] = useState<string | null>(null)

  useEffect(() => setMounted(true), [])

  if (!mounted || !isLoopback(RPC_URL)) return null

  const injected = (globalThis as { ethereum?: Injected }).ethereum
  if (!injected) return null

  async function point() {
    setState('pending')
    setDetail(null)
    try {
      await injected!.request({ method: 'wallet_addEthereumChain', params: [FORK_PARAMS] })
      await injected!.request({
        method: 'wallet_switchEthereumChain',
        params: [{ chainId: FORK_PARAMS.chainId }],
      })
      setState('done')
    } catch (caught) {
      // Rejecting the prompt is a normal outcome, and so is a wallet that will
      // not take a second network on an existing chain id. Both land here, and
      // both are answered by the manual instruction rather than by a retry.
      setState('failed')
      setDetail(caught instanceof Error ? caught.message : 'the wallet declined the request')
    }
  }

  return (
    <section className={className}>
      <div className="rounded border border-warn/30 bg-warn/[0.05] px-3 py-2.5">
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
          <div className="min-w-0">
            <p className="text-xs font-medium text-ink">
              This app is running against a local Base fork.
            </p>
            <p className="mt-0.5 text-2xs leading-relaxed text-muted">
              The fork keeps chain id 8453, so a wallet cannot distinguish it from Base mainnet.
              Point yours at{' '}
              <code className="font-mono text-ink">{RPC_URL}</code> or transactions are broadcast to
              real Base, where these vaults do not exist.
            </p>
          </div>

          <Button
            size="sm"
            variant="secondary"
            loading={state === 'pending'}
            onClick={() => void point()}
          >
            {state === 'done' ? 'Wallet pointed at the fork' : 'Use the fork network'}
          </Button>
        </div>

        {state === 'failed' ? (
          <p className="mt-2 border-t border-warn/20 pt-2 text-2xs leading-relaxed text-warn/90">
            The wallet did not take it ({detail}). Add it by hand instead: a custom network with RPC{' '}
            <code className="font-mono">{RPC_URL}</code>, chain id <code className="font-mono">8453</code>,
            symbol ETH. Some wallets refuse a second network on a chain id they already hold, in
            which case edit the existing Base network&rsquo;s RPC rather than adding one.
          </p>
        ) : null}

        {state === 'done' && !isConnected ? (
          <p className="mt-2 text-2xs leading-relaxed text-muted">
            Now connect a wallet to deposit.
          </p>
        ) : null}
      </div>
    </section>
  )
}
