import { createConfig, http } from 'wagmi'
import { base } from 'wagmi/chains'
import { injected } from 'wagmi/connectors'

/**
 * Wallet configuration: **injected connector only**.
 *
 * WalletConnect would add `NEXT_PUBLIC_WALLETCONNECT_ID` to the critical path
 * (master plan §8.1 lists it as "likely needed" and leaves the choice to this
 * lane). A hackathon demo is driven from a browser extension on the presenter's
 * laptop, so the connector that matters is the injected one — and dropping
 * WalletConnect removes a credential that can be missing at 03:00, a relay that
 * can be down, and a QR modal nobody will scan. It is additive later if anyone
 * wants a phone wallet on stage.
 *
 * The RPC is env-driven so the same build points at the anvil fork or at real
 * Base mainnet without a code change — the fork keeps chain id 8453, so only
 * the transport URL differs.
 */

const rpcUrl = process.env.NEXT_PUBLIC_RPC_URL

export const wagmiConfig = createConfig({
  chains: [base],
  connectors: [injected()],
  transports: {
    // `http(undefined)` falls back to the chain's public RPC, which is fine for
    // reads on mainnet and irrelevant on the fork (where the URL is always set).
    [base.id]: http(rpcUrl),
  },
  ssr: true,
})

declare module 'wagmi' {
  interface Register {
    config: typeof wagmiConfig
  }
}
