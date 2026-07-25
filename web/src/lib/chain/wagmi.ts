import { createConfig, http, injected } from '@wagmi/core'
import { base } from 'viem/chains'

/**
 * Wallet configuration — `@wagmi/core` + `viem` directly, **not** the `wagmi`
 * React package.
 *
 * Two reasons, and the second is the important one:
 *
 * 1. `wagmi` depends on `@wagmi/connectors`, whose barrel re-exports every
 *    connector it ships. Webpack resolves that barrel eagerly, so a build fails
 *    on `@x402/evm` and `@x402/svm` — optional peers of the Coinbase SDK that
 *    we never call.
 *
 * 2. That same dependency drags in roughly 60 packages we do not use (the
 *    entire `@solana/*` kit, Coinbase's CDP SDK, MetaMask SDK, WalletConnect,
 *    socket.io, lit, preact, axios), and they were the overwhelming majority of
 *    the violations found by `scripts/audit-dependency-age.mjs`. Dependencies
 *    you never import still sit in `node_modules` and still land in the
 *    lockfile. `@wagmi/core` by contrast declares three dependencies, each
 *    pinned to an exact version by its own author.
 *
 * The cost is that we write the React bindings ourselves — see `account.ts`.
 * That is about forty lines, because `@wagmi/core`'s actions are plain async
 * functions and we already have React Query in the stack to drive them.
 *
 * Connector choice: **injected only**. A hackathon demo is driven from a
 * browser extension on the presenter's laptop, so WalletConnect would add a
 * credential that can be missing at 03:00 and a relay that can be down, to
 * serve a QR code nobody will scan. EIP-6963 discovery is on by default, so
 * multiple installed wallets still announce themselves.
 */

const rpcUrl = process.env.NEXT_PUBLIC_RPC_URL

export const wagmiConfig = createConfig({
  chains: [base],
  connectors: [injected()],
  transports: {
    // `http(undefined)` falls back to the chain's public RPC. On the fork the
    // URL is always set, and the fork keeps chain id 8453, so pointing at anvil
    // or at real Base mainnet is purely a matter of this one env var.
    [base.id]: http(rpcUrl),
  },
  ssr: true,
})

export { base as chain }
