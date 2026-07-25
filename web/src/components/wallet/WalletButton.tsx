'use client'

import { useAccount, useConnect, useDisconnect } from 'wagmi'
import { Button } from '@/components/ui/Button'
import { shortAddress } from '@/lib/format/units'

/**
 * Injected connector only (see lib/chain/wagmi.ts for why). With one connector
 * there is nothing to choose between, so connecting is a single click rather
 * than a modal.
 */
export function WalletButton() {
  const { address, isConnected } = useAccount()
  const { connect, connectors, isPending, error } = useConnect()
  const { disconnect } = useDisconnect()

  const injected = connectors[0]

  if (isConnected && address) {
    return (
      <Button size="sm" variant="secondary" onClick={() => disconnect()} title={address}>
        <span className="h-1.5 w-1.5 rounded-full bg-ok" />
        <span className="font-mono">{shortAddress(address)}</span>
      </Button>
    )
  }

  return (
    <Button
      size="sm"
      variant="secondary"
      loading={isPending}
      disabled={!injected}
      onClick={() => injected && connect({ connector: injected })}
      title={
        injected
          ? undefined
          : 'No injected wallet detected — install MetaMask, Rabby or a Coinbase Wallet extension'
      }
    >
      {injected ? (isPending ? 'Connecting' : 'Connect wallet') : 'No wallet detected'}
      {error ? <span className="sr-only">{error.message}</span> : null}
    </Button>
  )
}
