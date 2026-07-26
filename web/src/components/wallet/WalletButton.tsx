'use client'

import { useState } from 'react'
import { Button } from '@/components/ui/Button'
import { useWallet } from '@/lib/chain/account'
import { shortAddress } from '@/lib/format/units'

/**
 * Injected connector only (see lib/chain/wagmi.ts for why). With one connector
 * there is nothing to choose between, so connecting is a single click rather
 * than a modal.
 */
export function WalletButton() {
  const { address, isConnected, hasConnector, connectWallet, disconnectWallet } = useWallet()
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function run(action: () => Promise<void>) {
    setPending(true)
    setError(null)
    try {
      await action()
    } catch (caught) {
      // A user rejecting the wallet prompt is a normal outcome, not a fault.
      setError(caught instanceof Error ? caught.message : 'Wallet request failed')
    } finally {
      setPending(false)
    }
  }

  if (isConnected && address) {
    return (
      <Button
        size="sm"
        variant="secondary"
        loading={pending}
        onClick={() => void run(disconnectWallet)}
        title={`${address} · click to disconnect`}
      >
        <span className="h-1.5 w-1.5 rounded-full bg-ok" />
        <span className="font-mono">{shortAddress(address)}</span>
      </Button>
    )
  }

  return (
    // Primary, not secondary: connecting is the one action the header is asking
    // for. The connected state above stays secondary on purpose — it reports a
    // status and offers disconnect, so it should not read as a call to action.
    <Button
      size="sm"
      variant="primary"
      // Compact on phones, full size from `sm` up. Fixed at md it crowded the
      // nav off the row below 414px.
      className="sm:h-9 sm:px-4 sm:text-sm"
      loading={pending}
      disabled={!hasConnector}
      onClick={() => void run(connectWallet)}
      title={
        error ??
        (hasConnector
          ? undefined
          : 'No injected wallet detected. Install MetaMask, Rabby or a Coinbase Wallet extension')
      }
    >
      {/* The header is the tightest row in the app at 375px: logo, nav, network
          badge and this button all compete for the same line, and a button that
          refuses to shrink pushes the whole page wider than the viewport. The
          label shortens rather than the layout breaking. */}
      {hasConnector ? (
        pending ? (
          'Connecting'
        ) : (
          <>
            <span className="sm:hidden">Connect</span>
            <span className="hidden sm:inline">Connect wallet</span>
          </>
        )
      ) : (
        <>
          <span className="sm:hidden">No wallet</span>
          <span className="hidden sm:inline">No wallet detected</span>
        </>
      )}
    </Button>
  )
}
