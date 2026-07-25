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
            // apiFetch already falls back to fixtures instead of throwing, so a
            // retry would only delay the render of data we can produce now.
            retry: false,
            staleTime: 5_000,
            refetchOnWindowFocus: false,
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
