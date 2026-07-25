'use client'

import { useCallback, useSyncExternalStore } from 'react'
import { connect, disconnect, getAccount, reconnect, watchAccount } from '@wagmi/core'
import { wagmiConfig } from './wagmi'

/**
 * The React bindings we would otherwise take the whole `wagmi` package for.
 *
 * `@wagmi/core` already keeps the canonical account state and exposes
 * `watchAccount` to observe it, so the React side is just a
 * `useSyncExternalStore` over that — which is, in essence, what wagmi's own
 * hook does. See `wagmi.ts` for why we do not simply install `wagmi`.
 *
 * The one subtlety: `getAccount()` builds a fresh object on every call, and
 * `useSyncExternalStore` re-renders whenever the snapshot's *identity* changes.
 * Returning it directly would loop forever, so the snapshot is cached in module
 * scope and replaced only when `watchAccount` actually fires.
 */

export type AccountSnapshot = {
  address?: `0x${string}`
  chainId?: number
  isConnected: boolean
  status: 'connected' | 'connecting' | 'reconnecting' | 'disconnected'
}

const DISCONNECTED: AccountSnapshot = { isConnected: false, status: 'disconnected' }

let snapshot: AccountSnapshot = DISCONNECTED
let watching = false
const listeners = new Set<() => void>()

function toSnapshot(account: ReturnType<typeof getAccount>): AccountSnapshot {
  return {
    address: account.address,
    chainId: account.chainId,
    isConnected: account.isConnected,
    status: account.status,
  }
}

function emit(): void {
  for (const listener of listeners) listener()
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)

  if (!watching) {
    watching = true
    snapshot = toSnapshot(getAccount(wagmiConfig))
    watchAccount(wagmiConfig, {
      onChange(account) {
        snapshot = toSnapshot(account)
        emit()
      },
    })
  }

  return () => {
    listeners.delete(listener)
  }
}

function getSnapshot(): AccountSnapshot {
  return snapshot
}

/** The server never has a wallet, so it always renders the disconnected state. */
function getServerSnapshot(): AccountSnapshot {
  return DISCONNECTED
}

export function useAccount(): AccountSnapshot {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot)
}

/** Restore a previously-authorised wallet on load. Safe to call more than once. */
export function reconnectWallet(): void {
  void reconnect(wagmiConfig).catch(() => {
    // No previously-authorised connector, or the user revoked it. Not an error.
  })
}

export function useWallet() {
  const account = useAccount()

  const connectWallet = useCallback(async () => {
    const connector = wagmiConfig.connectors[0]
    if (!connector) throw new Error('No injected wallet detected')
    await connect(wagmiConfig, { connector })
  }, [])

  const disconnectWallet = useCallback(async () => {
    await disconnect(wagmiConfig)
  }, [])

  return {
    ...account,
    hasConnector: wagmiConfig.connectors.length > 0,
    connectWallet,
    disconnectWallet,
  }
}
