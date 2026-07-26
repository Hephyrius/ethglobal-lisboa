'use client'

import { useEffect, useState, type ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { DataModeProvider } from '@/lib/api/mode-context'
import { reconnectWallet } from '@/lib/chain/account'

export function Providers({ children }: { children: ReactNode }) {
  // Created in state, not at module scope: a module-level client would be
  // shared across server requests and leak one visitor's cache into another's.
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            // One retry, and it costs the fixture path nothing.
            //
            // This was `false`, on the reasoning that `apiFetch` falls back to
            // fixtures rather than throwing, so retrying would only delay a
            // render we can already do. That reasoning is still correct — and
            // it is precisely why a retry is safe: a query that never rejects
            // never retries. The setting therefore only reaches the queries
            // that *do* throw, which are the two that most need it:
            //
            //   * the chain reads (`all-vaults`, `vault-contract`), which hit a
            //     free public RPC and get a 429 often enough that one refusal
            //     was leaving every vault in the list labelled a generic
            //     "Vault" — the batched `name()` multicall failing with no
            //     second attempt.
            //   * `apiFetchStrict`, which health uses.
            retry: 1,
            staleTime: 5_000,
            // ⚠️ Was `false`, and that is the whole of the "it times out and
            // only comes back on a hard refresh" report.
            //
            // Browsers throttle timers in a backgrounded tab and freeze them
            // outright after a few minutes, so `refetchInterval` stops firing
            // the moment attention moves to a terminal or a recording window.
            // With focus refetching also off, *nothing* re-runs on return: the
            // page sits on whatever state it froze in — including a transient
            // fixture fallback — and a manual reload is the only recovery.
            // That is the exact shape of the bug: fine while watched, stale
            // when you come back.
            //
            // Refetching on focus is one request per query per return to the
            // tab, which is far cheaper than the reload it replaces.
            refetchOnWindowFocus: true,
          },
        },
      }),
  )

  // `wagmi`'s WagmiProvider did this for us; using @wagmi/core directly means
  // restoring a previously-authorised wallet is our job. Without it the user
  // has to reconnect on every page load.
  useEffect(() => {
    reconnectWallet()
  }, [])

  return (
    <QueryClientProvider client={queryClient}>
      <DataModeProvider>{children}</DataModeProvider>
    </QueryClientProvider>
  )
}
