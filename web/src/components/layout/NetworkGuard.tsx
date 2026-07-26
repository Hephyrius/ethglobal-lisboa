'use client'

import { useCallback, useState } from 'react'
import { switchChain } from '@wagmi/core'
import { useAccount } from '@/lib/chain/account'
import { chain, wagmiConfig } from '@/lib/chain/wagmi'

/**
 * Says so when the connected wallet is on the wrong chain, and offers to move it.
 *
 * ## Why this is not merely cosmetic
 *
 * Every read in this app is bound to Base by the wagmi transport, so the page
 * renders correct Base data no matter what chain the wallet is on. That is the
 * trap: nothing on screen looks wrong. A visitor arriving with MetaMask left on
 * Ethereum mainnet sees real balances, a real vault, a working deposit form —
 * and their transaction would have gone somewhere else.
 *
 * `vault-contract.ts` pins `chainId` on every write, so the transaction is now
 * refused rather than misrouted. But a refusal surfaces as a wallet error
 * dialog that names a chain id and explains nothing. This is the part that says
 * what happened before they click, in words.
 *
 * ## Why it renders nothing when disconnected
 *
 * A wallet that is not connected has no chain to be wrong about, and warning
 * about a mismatch that cannot exist yet trains people to ignore the banner
 * that matters. `chainId` is undefined until a connector attaches; that is not
 * a mismatch.
 */

const CHAIN_NAMES: Record<number, string> = {
  1: 'Ethereum mainnet',
  8453: 'Base',
  84532: 'Base Sepolia',
  10: 'OP Mainnet',
  42161: 'Arbitrum One',
  137: 'Polygon',
  56: 'BNB Chain',
  43114: 'Avalanche',
  31337: 'a local fork',
}

const named = (id: number): string => CHAIN_NAMES[id] ?? `chain ${id}`

export function NetworkGuard() {
  const account = useAccount()
  const [switching, setSwitching] = useState(false)
  const [failed, setFailed] = useState<string | null>(null)

  const wrong = account.isConnected && account.chainId !== undefined && account.chainId !== chain.id

  const onSwitch = useCallback(async () => {
    setSwitching(true)
    setFailed(null)
    try {
      await switchChain(wagmiConfig, { chainId: chain.id })
    } catch (error) {
      // A rejected switch is a choice, not a fault — but the wallet gives no
      // other signal, so the banner has to keep standing rather than silently
      // resetting as though it had worked.
      setFailed(error instanceof Error ? error.message : 'The wallet refused the switch.')
    } finally {
      setSwitching(false)
    }
  }, [])

  if (!wrong) return null

  return (
    <div className="border-b border-bad/30 bg-bad/[0.08]">
      <div className="mx-auto flex max-w-[1400px] flex-wrap items-center justify-center gap-x-3 gap-y-1.5 px-4 py-2 text-2xs leading-relaxed text-bad sm:px-6">
        <span>
          <span className="font-semibold">Wrong network.</span> Your wallet is on{' '}
          {named(account.chainId as number)}; these vaults are on {named(chain.id)}. Deposits and
          withdrawals will be refused until you switch.
        </span>
        <button
          type="button"
          onClick={onSwitch}
          disabled={switching}
          className="rounded border border-bad/40 bg-bad/10 px-2 py-0.5 font-medium text-bad transition-colors hover:bg-bad/20 disabled:opacity-50"
        >
          {switching ? 'Switching…' : `Switch to ${named(chain.id)}`}
        </button>
        {failed ? <span className="text-bad/80">{failed}</span> : null}
      </div>
    </div>
  )
}
